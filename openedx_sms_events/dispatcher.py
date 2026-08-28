"""
Generic event fan-out: one event type → N subscriber webhooks.

This is the delivery shape of the package. It replaces the original
single-endpoint ``notify_course_published`` task, which shipped one event type
to one hardwired URL. As more event types and more satellite apps need events,
that 1:1 shape doesn't scale: every new consumer would mean a new task, and
every new event type would mean touching every task.

The dispatcher inverts it into a small, deep module — a lot of behaviour
(routing, auth, retry, backoff, fan-out, per-subscriber isolation) behind a
tiny interface (:func:`deliver_event`):

  - :func:`deliver_event` (event_type, payload) → fans out to every subscriber
    that opted into ``event_type``, scheduling one :func:`deliver_to_subscriber`
    task per match. Per-subscriber failure isolation: one dead consumer cannot
    stall the others, because each gets its own task with its own retry chain.
  - :func:`deliver_to_subscriber` (name, event_type, payload) → does the actual
    POST, with its own backoff retry. Looks the subscriber up by name in
    ``SMS_EVENTS`` at call time, so URL/token changes take effect on the next
    attempt without re-firing the event.

Adding an event type = a thin ``@receiver`` in ``signals.py`` that builds a
payload and calls ``deliver_event.delay(event_type, payload)``. Adding a
consumer = a new entry in ``SMS_EVENTS["subscribers"]``; zero code in any app.

Both tasks are free of edx-platform imports (``xmodule``/``opaque_keys``), so
they unit-test with a minimal Django + Celery + requests stack, like the
existing task tests. The edx-importing seam stays in ``signals.py``.

Settings shape (the ``subscribers`` list replaced the single
``course_published_webhook_url``/``auth_token`` pair)::

    SMS_EVENTS = {
        "subscribers": [
            {
                "name": "extras",          # stable id used by deliver_to_subscriber
                "url": "https://extras.<instance>/api/v1/events/",
                "auth_token": "shared-bearer",
                "timeout": 5.0,
                "events": ["*"],           # this subscriber wants everything
            },
            {
                "name": "catalog",
                "url": "https://catalog.<instance>/api/v1/events/",
                "auth_token": "catalog-bearer",
                "timeout": 5.0,
                "events": ["course_published", "enrollment"],
            },
        ],
    }
"""

import logging

import requests
from celery import shared_task
from django.conf import settings

log = logging.getLogger(__name__)

# Sentinel placed in a subscriber's ``events`` list to mean "all event types".
# Convenient for the hub subscriber (extras) that wants every event.
ALL_EVENTS = "*"

# Default per-request HTTP timeout (seconds) when a subscriber omits ``timeout``
# or gives a non-numeric value.
DEFAULT_TIMEOUT = 5.0

# Retry policy: any network/HTTP failure retried with exponential backoff,
# capped, jittered, up to 5 times. This covers short reboot windows (~10 min)
# of a consumer app. (The same policy the retired single-endpoint task used.)
MAX_RETRIES = 5
RETRY_BACKOFF_MAX = 600


def _get_config():
    """Return the ``SMS_EVENTS`` settings dict (never ``None``)."""
    return getattr(settings, "SMS_EVENTS", None) or {}


def _subscribers(config):
    """Return the subscriber list (never ``None``)."""
    return config.get("subscribers") or []


def matching_subscribers(event_type, config):
    """
    Pure routing: which subscribers should receive ``event_type``?

    A subscriber matches when its ``events`` list contains ``event_type`` or
    the :data:`ALL_EVENTS` sentinel (``"*"``). An empty or missing ``events``
    list opts the subscriber out of everything (fail safe: never spam a
    consumer that didn't explicitly opt in).

    Pure on ``config`` so it is unit-testable with no Celery and no broker.
    """
    out = []
    for sub in _subscribers(config):
        events = sub.get("events") or []
        if ALL_EVENTS in events or event_type in events:
            out.append(sub)
    return out


def _find_subscriber(config, name):
    """Look up a subscriber by ``name`` (None if not found)."""
    for sub in _subscribers(config):
        if sub.get("name") == name:
            return sub
    return None


def _coerce_timeout(value):
    """Coerce a subscriber ``timeout`` to a float, falling back to the default."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


@shared_task(bind=True)
def deliver_event(self, event_type, payload):
    """
    Fan an event out to every subscriber that opted into ``event_type``.

    Schedules one :func:`deliver_to_subscriber` task per matching subscriber.
    This task deliberately has **no autoretry**: it only schedules child
    tasks, so retrying it would duplicate deliveries to every subscriber on
    any transient broker blip. Per-subscriber delivery failures are isolated
    inside each child task's own retry chain — one dead consumer cannot stall
    the others.

    Returns the list of subscriber names it scheduled (useful for logging /
    tests).
    """
    config = _get_config()
    matches = matching_subscribers(event_type, config)
    if not matches:
        log.info(
            "SMS_EVENTS: no subscribers for %s; skipping (%s)",
            event_type,
            payload.get("course_key", ""),
        )
        return []

    scheduled = []
    for sub in matches:
        name = sub.get("name")
        if not name:
            # ``name`` is the stable id :func:`deliver_to_subscriber` looks up
            # by; without it the subscriber is misconfigured and would be
            # silently dropped at delivery (no key to match). Skip it here
            # (fail safe) rather than schedule a task that can never resolve.
            log.warning(
                "SMS_EVENTS: subscriber without a name skipped for %s (%s)",
                event_type,
                payload.get("course_key", ""),
            )
            continue
        deliver_to_subscriber.delay(name, event_type, payload)
        scheduled.append(name)
        log.info(
            "SMS_EVENTS: dispatched %s for %s to %s",
            event_type,
            payload.get("course_key", ""),
            name,
        )
    return scheduled


@shared_task(
    bind=True,
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
    retry_backoff_max=RETRY_BACKOFF_MAX,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
def deliver_to_subscriber(self, subscriber_name, event_type, payload):
    """
    POST one event to one subscriber's webhook, with backoff retry.

    The subscriber is looked up by ``subscriber_name`` in ``SMS_EVENTS`` at
    call time, so URL/token changes take effect on the next attempt without
    re-firing the event. A missing subscriber (e.g. config edited mid-retry)
    or an empty URL is a logged no-op, not an error — there is nothing to
    retry against.

    Failures (network/HTTP) are re-raised so Celery's autoretry with backoff
    reschedules the task, up to :data:`MAX_RETRIES` times.
    """
    config = _get_config()
    sub = _find_subscriber(config, subscriber_name)
    if sub is None:
        log.warning(
            "SMS_EVENTS: subscriber %r not found in config; dropping %s for %s",
            subscriber_name,
            event_type,
            payload.get("course_key", ""),
        )
        return None

    url = sub.get("url") or ""
    if not url:
        log.info(
            "SMS_EVENTS: subscriber %s has no url; skipping %s for %s",
            subscriber_name,
            event_type,
            payload.get("course_key", ""),
        )
        return None

    headers = {"Content-Type": "application/json"}
    token = sub.get("auth_token") or ""
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = _coerce_timeout(sub.get("timeout"))

    attempt = (self.request.retries or 0) + 1
    log.info(
        "SMS_EVENTS: posting %s to %s (attempt %d/%d) for %s",
        event_type,
        url,
        attempt,
        self.max_retries + 1,
        payload.get("course_key", ""),
    )
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        log.warning(
            "SMS_EVENTS: %s delivery to %s failed: %s (attempt %d/%d)",
            event_type,
            url,
            exc,
            attempt,
            self.max_retries + 1,
        )
        raise

    log.info(
        "SMS_EVENTS: %s delivered to %s (HTTP %s)",
        event_type,
        url,
        response.status_code,
    )
    return {"status_code": response.status_code}
