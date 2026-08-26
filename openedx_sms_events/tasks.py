"""
Celery tasks for outbound event delivery.

The tasks in this module are intentionally free of any edx-platform imports
(``xmodule``, ``opaque_keys``) so they can be unit-tested with a minimal
Django + Celery + requests environment. The signal receiver in ``signals.py``
is responsible for turning an Open edX ``course_key`` into the plain-dict
payload these tasks consume.
"""

import logging

import requests
from celery import shared_task
from django.conf import settings

log = logging.getLogger(__name__)


def _get_config():
    """Return the ``SMS_EVENTS`` settings dict (never ``None``)."""
    return getattr(settings, "SMS_EVENTS", None) or {}


@shared_task(
    bind=True,
    # Retry any network/HTTP failure with exponential backoff (Celery's
    # autoretry wraps the task body; the body re-raises so the retry kicks in).
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def notify_course_published(self, payload):
    """
    POST a ``course_published`` event to the configured swissmooc-extras webhook.

    ``payload`` is the JSON body expected by the extras endpoint::

        {
            "course_key": "course-v1:EPFL+DemoX+2025_T1",
            "org": "EPFL",
            "course": "DemoX",
            "run": "2025_T1",
            "instance_name": "epfl"
        }

    The call is made here (in a Celery worker), never in the Studio request
    thread that fired the signal. Failures are logged and retried with backoff
    up to ``max_retries`` times.
    """
    config = _get_config()
    url = config.get("course_published_webhook_url") or ""
    course_key = payload.get("course_key", "")

    if not url:
        log.info(
            "SMS_EVENTS: course_published webhook URL not configured; skipping event for %s",
            course_key,
        )
        return None

    headers = {"Content-Type": "application/json"}
    token = config.get("auth_token") or ""
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = config.get("timeout", 5.0)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        timeout = 5.0

    attempt = (self.request.retries or 0) + 1
    log.info(
        "SMS_EVENTS: posting course_published event for %s to %s (attempt %d/%d)",
        course_key,
        url,
        attempt,
        self.max_retries + 1,
    )
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        log.warning(
            "SMS_EVENTS: course_published webhook failed for %s: %s (attempt %d/%d)",
            course_key,
            exc,
            attempt,
            self.max_retries + 1,
        )
        # Re-raise so Celery's autoretry (with backoff) reschedules the task.
        raise

    log.info(
        "SMS_EVENTS: course_published webhook delivered for %s (HTTP %s)",
        course_key,
        response.status_code,
    )
    return {"status_code": response.status_code}
