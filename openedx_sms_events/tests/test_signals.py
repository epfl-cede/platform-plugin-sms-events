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


def test_receiver_builds_payload_and_defers_to_dispatcher(settings):
    """
    The receiver must schedule ``deliver_event.delay("course_published", payload)``
    via ``transaction.on_commit`` — never on the request thread, never on rollback.
    """
    settings.INSTANCE_NAME = "epfl"
    course_key = _fake_course_key()
    deferred = []

    # Capture the on_commit callback instead of running it.
    with mock.patch.object(signals.transaction, "on_commit", side_effect=deferred.append):
        with mock.patch.object(signals.deliver_event, "delay") as delay:
            signals.on_course_published(sender=None, course_key=course_key)

    delay.assert_not_called()
    assert len(deferred) == 1

    # Running the captured callback should fan the event out via the dispatcher
    # with the course_published event type and the built payload.
    with mock.patch.object(signals.deliver_event, "delay") as delay:
        deferred[0]()

    delay.assert_called_once_with(signals.COURSE_PUBLISHED, mock.ANY)
    _, args, _ = delay.mock_calls[-1]
    assert args[1]["event_type"] == "course_published"
    assert args[1]["course_key"] == "course-v1:EPFL+DemoX+2025_T1"
    assert args[1]["org"] == "EPFL"
    assert args[1]["course"] == "DemoX"
    assert args[1]["run"] == "2025_T1"
    assert args[1]["instance_name"] == "epfl"


def test_payload_carries_stable_event_identity(settings):
    """
    The payload must carry an event_id + occurred_at so consumers can
    deduplicate dispatcher retries (one row per event, not one per delivery).
    event_id is stable for a single publish; two builds produce two distinct
    ids (one per publish event).
    """
    settings.INSTANCE_NAME = "epfl"
    course_key = _fake_course_key()
    payload_a = signals.build_payload(course_key)
    payload_b = signals.build_payload(course_key)

    for payload in (payload_a, payload_b):
        assert payload["event_id"]  # non-empty
        assert payload["event_type"] == "course_published"
        assert payload["occurred_at"]  # non-empty ISO timestamp

    # Two publishes of the same course get distinct identities.
    assert payload_a["event_id"] != payload_b["event_id"]


def test_payload_includes_instance_name_from_settings(settings):
    """instance_name distinguishes the deployment, not the openedx org."""
    settings.INSTANCE_NAME = "ethz"
    course_key = _fake_course_key()
    payload = signals.build_payload(course_key)
    assert payload["instance_name"] == "ethz"
    assert payload["org"] == "EPFL"


def test_payload_instance_name_defaults_to_empty_when_unset(settings):
    """A missing INSTANCE_NAME must not crash the receiver."""
    del settings.INSTANCE_NAME
    course_key = _fake_course_key()
    payload = signals.build_payload(course_key)
    assert payload["instance_name"] == ""


def test_receiver_is_connected_to_course_published():
    """The receiver must be wired to SignalHandler.course_published."""
    from xmodule.modulestore.django import SignalHandler

    receivers = [r() for _, r in SignalHandler.course_published.receivers]
    assert signals.on_course_published in receivers
