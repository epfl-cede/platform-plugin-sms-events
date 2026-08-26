"""
Tests for ``openedx_sms_events.signals``.

These require the openedx platform (``xmodule``, ``opaque_keys``) and are
therefore skipped outside the openedx devstack / CI image. Run them there with:

    pytest openedx_sms_events/tests/test_signals.py
"""

import types
from unittest import mock

import pytest

pytest.importorskip("xmodule.modulestore.django")

from openedx_sms_events import signals  # noqa: E402


def _fake_course_key():
    """A lightweight stand-in for an opaque_keys CourseKey."""
    return types.SimpleNamespace(
        __str__=lambda self: "course-v1:EPFL+DemoX+2025_T1",
        org="EPFL",
        course="DemoX",
        run="2025_T1",
    )


def test_receiver_builds_payload_and_defers_to_celery():
    course_key = _fake_course_key()
    deferred = []

    # Capture the on_commit callback instead of running it.
    with mock.patch.object(signals.transaction, "on_commit", side_effect=deferred.append):
        with mock.patch.object(signals.notify_course_published, "delay") as delay:
            signals.on_course_published(sender=None, course_key=course_key)

    delay.assert_not_called()
    assert len(deferred) == 1

    # Running the captured callback should schedule the task with the payload.
    with mock.patch.object(signals.notify_course_published, "delay") as delay:
        deferred[0]()

    delay.assert_called_once_with(
        {
            "course_key": "course-v1:EPFL+DemoX+2025_T1",
            "org": "EPFL",
            "course": "DemoX",
            "run": "2025_T1",
        }
    )


def test_receiver_is_connected_to_course_published():
    """The receiver must be wired to SignalHandler.course_published."""
    from xmodule.modulestore.django import SignalHandler

    receivers = [r() for _, r in SignalHandler.course_published.receivers]
    assert signals.on_course_published in receivers
