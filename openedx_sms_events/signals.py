"""
Signal receivers bridging Open edX lifecycle events to swissmooc satellite apps.

This module is imported from :meth:`OpenedxSMSEventsConfig.ready`, so it is only
loaded inside the CMS (the app is registered as ``cms.djangoapp``). It pulls in
``xmodule`` / ``opaque_keys`` and is therefore only importable from within an
openedx environment; the unit tests in ``tests/test_signals.py`` skip
themselves when those modules are unavailable.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.dispatch import receiver
from xmodule.modulestore.django import SignalHandler

from openedx_sms_events.tasks import notify_course_published

log = logging.getLogger(__name__)


def _build_payload(course_key):
    """
    Build the webhook payload from a course key.

    ``instance_name`` is the swissmooc *deployment* instance (epfl, ethz,
    oleg, ...) from ``settings.INSTANCE_NAME`` (injected per instance by the
    Tutor ``openedx-common-settings`` patch). It is distinct from the Open edX
    ``org`` (e.g. EPFL, EPFLx), which is an internal org *within* an instance;
    the extras app uses ``instance_name`` to tell deployments apart.
    """
    return {
        "course_key": str(course_key),
        "org": course_key.org,
        "course": course_key.course,
        "run": course_key.run,
        "instance_name": getattr(settings, "INSTANCE_NAME", "") or "",
    }


@receiver(SignalHandler.course_published)
def on_course_published(sender, course_key, **kwargs):
    """
    React to ``SignalHandler.course_published`` (Studio course publish).

    The receiver runs in the Studio request thread, so it does as little as
    possible: it builds the plain-dict webhook payload from the course key and
    defers the actual HTTP call to the ``notify_course_published`` Celery task,
    scheduled via ``transaction.on_commit`` so it only fires if the surrounding
    publish transaction actually commits.
    """
    payload = _build_payload(course_key)
    transaction.on_commit(lambda: notify_course_published.delay(payload))
