"""
Signal receivers bridging Open edX lifecycle events to swissmooc satellite apps.

This module is imported from :meth:`OpenedxSMSEventsConfig.ready`, so it is only
loaded inside the CMS (the app is registered as ``cms.djangoapp``). It pulls in
``xmodule`` / ``opaque_keys`` and is therefore only importable from within an
openedx environment; the unit tests in ``tests/test_signals.py`` skip
themselves when those modules are unavailable.

This is the only edx-importing seam in the package. Receivers here build a
plain-dict event payload (including a stable event identity for downstream
deduplication) and hand it to the dispatcher in :mod:`openedx_sms_events.dispatcher`,
which is free of edx-platform imports and unit-testable outside the openedx
image.
"""

import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.dispatch import receiver
from django.utils import timezone
from xmodule.modulestore.django import SignalHandler

from openedx_sms_events.dispatcher import deliver_event

log = logging.getLogger(__name__)

# Event type names. Each wired signal publishes one of these as the
# ``event_type`` argument to :func:`deliver_event.delay`; subscribers opt into
# them (or into ``"*"``) via ``SMS_EVENTS["subscribers"][...]["events"]``.
COURSE_PUBLISHED = "course_published"


def build_payload(course_key):
    """
    Build the ``course_published`` event payload from a course key.

    The payload is a self-describing event envelope: a stable
    :data:`event_id` / :data:`occurred_at` identity plus the course fields
    downstream consumers need. ``event_id`` is generated once, here in the
    signal receiver, and is then immutable for the lifetime of the event —
    every dispatcher retry redelivers the same payload, so consumers can
    deduplicate retries on ``event_id`` (one row, not many).

    ``occurred_at`` is the publish time (when the signal fired), captured in
    UTC. Together with ``event_id`` it gives consumers a natural identity even
    if they cannot trust transport ordering.
    """
    return {
        "event_id": str(uuid.uuid4()),
        "occurred_at": timezone.now().isoformat(),
        "course_key": str(course_key),,
        "org": course_key.org,
        "course": course_key.course,
        "run": course_key.run,
        "instance_name": getattr(settings, "INSTANCE_NAME", ""),
    }


@receiver(SignalHandler.course_published)
def on_course_published(sender, course_key, **kwargs):
    """
    React to ``SignalHandler.course_published`` (Studio course publish).

    The receiver runs in the Studio request thread, so it does as little as
    possible: it builds the plain-dict event payload from the course key and
    defers the actual fan-out to the ``deliver_event`` Celery task, scheduled
    via ``transaction.on_commit`` so it only fires if the surrounding publish
    transaction actually commits — and never on the Studio request thread, never
    on rollback. The dispatcher then fans the event out to every subscriber
    that opted into ``course_published`` (or ``"*"``).
    """
    payload = build_payload(course_key)
    transaction.on_commit(lambda: deliver_event.delay(COURSE_PUBLISHED, payload))
