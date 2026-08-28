"""
Unit tests for the generic event dispatcher (``openedx_sms_events.dispatcher``).

These cover the three responsibilities the dispatcher separates:

  - **routing** — ``matching_subscribers`` picks subscribers by event type
    (pure function, no Celery, no broker).
  - **fan-out** — ``deliver_event`` schedules one ``deliver_to_subscriber``
    per match, with per-subscriber failure isolation.
  - **delivery** — ``deliver_to_subscriber`` does the POST with backoff retry.

Task bodies are exercised via ``Task.run`` (no broker required). The fan-out
step mocks ``deliver_to_subscriber.delay``.
"""

from unittest import mock

import pytest
import requests

from openedx_sms_events.dispatcher import (
    deliver_event,
    deliver_to_subscriber,
    matching_subscribers,
)

COURSE_PAYLOAD = {
    "course_key": "course-v1:EPFL+DemoX+2025_T1",
    "org": "EPFL",
    "course": "DemoX",
    "run": "2025_T1",
    "instance_name": "epfl",
}

EXTRAS_URL = "https://extras.example.edu/api/v1/events/"
CATALOG_URL = "https://catalog.example.edu/api/v1/events/"
INSIGHTS_URL = "https://insights.example.edu/api/v1/events/"


def _subscriber(name, url, events, token="t", timeout=5.0):
    return {
        "name": name,
        "url": url,
        "events": events,
        "auth_token": token,
        "timeout": timeout,
    }


def _config(subscribers):
    return {"subscribers": subscribers}


# ---------------------------------------------------------------------------
# routing: matching_subscribers
# ---------------------------------------------------------------------------

def test_matching_subscribers_selects_explicit_event():
    config = _config([
        _subscriber("extras", EXTRAS_URL, events=["course_published", "enrollment"]),
        _subscriber("catalog", CATALOG_URL, events=["course_published"]),
    ])
    matches = matching_subscribers("enrollment", config)
    assert [m["name"] for m in matches] == ["extras"]


def test_matching_subscribers_wildcard_matches_all():
    config = _config([
        _subscriber("extras", EXTRAS_URL, events=["*"]),
        _subscriber("catalog", CATALOG_URL, events=["course_published"]),
    ])
    matches = matching_subscribers("grade_uploaded", config)
    assert [m["name"] for m in matches] == ["extras"]


def test_matching_subscribers_empty_events_opts_out():
    # Fail safe: a subscriber with no/empty events list gets nothing, but a
    # subscriber that explicitly listed the event still matches.
    config = _config([
        _subscriber("extras", EXTRAS_URL, events=[]),
        _subscriber("catalog", CATALOG_URL, events=["course_published"]),
    ])
    matches = matching_subscribers("course_published", config)
    assert [m["name"] for m in matches] == ["catalog"]


def test_matching_subscribers_missing_events_key_opts_out():
    config = _config([{"name": "extras", "url": EXTRAS_URL}])
    assert matching_subscribers("course_published", config) == []


def test_matching_subscribers_no_subscribers():
    assert matching_subscribers("course_published", {}) == []
    assert matching_subscribers("course_published", {"subscribers": []}) == []


def test_matching_subscribers_multiple_matches_preserve_order():
    config = _config([
        _subscriber("extras", EXTRAS_URL, events=["*"]),
        _subscriber("catalog", CATALOG_URL, events=["course_published"]),
        _subscriber("insights", INSIGHTS_URL, events=["course_published"]),
    ])
    matches = matching_subscribers("course_published", config)
    assert [m["name"] for m in matches] == ["extras", "catalog", "insights"]


# ---------------------------------------------------------------------------
# fan-out: deliver_event
# ---------------------------------------------------------------------------

def test_deliver_event_schedules_one_task_per_matching_subscriber(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", EXTRAS_URL, events=["*"]),
        _subscriber("catalog", CATALOG_URL, events=["course_published"]),
    ])
    with mock.patch("openedx_sms_events.dispatcher.deliver_to_subscriber.delay") as delay:
        scheduled = deliver_event.run("course_published", COURSE_PAYLOAD)

    assert scheduled == ["extras", "catalog"]
    assert delay.call_count == 2
    delay.assert_any_call("extras", "course_published", COURSE_PAYLOAD)
    delay.assert_any_call("catalog", "course_published", COURSE_PAYLOAD)


def test_deliver_event_skips_non_matching_subscribers(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", EXTRAS_URL, events=["enrollment"]),
        _subscriber("catalog", CATALOG_URL, events=["course_published"]),
    ])
    with mock.patch("openedx_sms_events.dispatcher.deliver_to_subscriber.delay") as delay:
        scheduled = deliver_event.run("course_published", COURSE_PAYLOAD)

    assert scheduled == ["catalog"]
    delay.assert_called_once_with("catalog", "course_published", COURSE_PAYLOAD)


def test_deliver_event_no_matches_schedules_nothing(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", EXTRAS_URL, events=["enrollment"]),
    ])
    with mock.patch("openedx_sms_events.dispatcher.deliver_to_subscriber.delay") as delay:
        scheduled = deliver_event.run("course_published", COURSE_PAYLOAD)

    assert scheduled == []
    delay.assert_not_called()


def test_deliver_event_never_raises_isolating_subscribers(settings):
    # The fan-out task must not raise on delivery failure: each subscriber has
    # its own task. Here .delay itself blowing up is the only way deliver_event
    # could fail mid-loop; that is a broker problem, not a subscriber problem,
    # and propagating it would be correct. What we guarantee is that one dead
    # *subscriber config* (bad url) never blocks another.
    settings.SMS_EVENTS = _config([
        _subscriber("broken", "", events=["course_published"]),
        _subscriber("catalog", CATALOG_URL, events=["course_published"]),
    ])
    with mock.patch("openedx_sms_events.dispatcher.deliver_to_subscriber.delay") as delay:
        scheduled = deliver_event.run("course_published", COURSE_PAYLOAD)

    # Both are scheduled; the bad url is handled inside deliver_to_subscriber,
    # not by dropping it from the fan-out.
    assert scheduled == ["broken", "catalog"]
    assert delay.call_count == 2


def test_deliver_event_skips_subscriber_without_name(settings):
    # ``name`` is the stable id deliver_to_subscriber looks up by. A subscriber
    # that matched on event type but has no name is misconfigured: scheduling it
    # would only be silently dropped at delivery. Fan-out skips it (fail safe)
    # and still delivers to the well-formed subscriber.
    settings.SMS_EVENTS = _config([
        {"url": EXTRAS_URL, "events": ["course_published"]},
        _subscriber("catalog", CATALOG_URL, events=["course_published"]),
    ])
    with mock.patch("openedx_sms_events.dispatcher.deliver_to_subscriber.delay") as delay:
        scheduled = deliver_event.run("course_published", COURSE_PAYLOAD)

    assert scheduled == ["catalog"]
    delay.assert_called_once_with("catalog", "course_published", COURSE_PAYLOAD)


# ---------------------------------------------------------------------------
# delivery: deliver_to_subscriber
# ---------------------------------------------------------------------------

def test_deliver_to_subscriber_posts_with_bearer_auth_and_timeout(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", EXTRAS_URL, events=["course_published"], token="secret", timeout=4.0),
    ])
    response = mock.Mock(status_code=202)
    with mock.patch("openedx_sms_events.dispatcher.requests.post", return_value=response) as post:
        result = deliver_to_subscriber.run("extras", "course_published", COURSE_PAYLOAD)

    post.assert_called_once()
    _, kwargs = post.call_args
    assert kwargs["json"] == COURSE_PAYLOAD
    assert kwargs["timeout"] == 4.0
    assert kwargs["headers"]["Authorization"] == "Bearer secret"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert result == {"status_code": 202}


def test_deliver_to_subscriber_no_token_omits_authorization(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", EXTRAS_URL, events=["course_published"], token=""),
    ])
    response = mock.Mock(status_code=202)
    with mock.patch("openedx_sms_events.dispatcher.requests.post", return_value=response) as post:
        deliver_to_subscriber.run("extras", "course_published", COURSE_PAYLOAD)

    _, kwargs = post.call_args
    assert "Authorization" not in kwargs["headers"]


def test_deliver_to_subscriber_timeout_string_coerced(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", EXTRAS_URL, events=["course_published"], timeout="2.5"),
    ])
    response = mock.Mock(status_code=202)
    with mock.patch("openedx_sms_events.dispatcher.requests.post", return_value=response) as post:
        deliver_to_subscriber.run("extras", "course_published", COURSE_PAYLOAD)

    _, kwargs = post.call_args
    assert kwargs["timeout"] == 2.5


def test_deliver_to_subscriber_invalid_timeout_falls_back(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", EXTRAS_URL, events=["course_published"], timeout="nope"),
    ])
    response = mock.Mock(status_code=202)
    with mock.patch("openedx_sms_events.dispatcher.requests.post", return_value=response) as post:
        deliver_to_subscriber.run("extras", "course_published", COURSE_PAYLOAD)

    _, kwargs = post.call_args
    assert kwargs["timeout"] == 5.0


def test_deliver_to_subscriber_missing_subscriber_is_noop(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", EXTRAS_URL, events=["course_published"]),
    ])
    with mock.patch("openedx_sms_events.dispatcher.requests.post") as post:
        result = deliver_to_subscriber.run("ghost", "course_published", COURSE_PAYLOAD)
    post.assert_not_called()
    assert result is None


def test_deliver_to_subscriber_empty_url_is_noop(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", "", events=["course_published"]),
    ])
    with mock.patch("openedx_sms_events.dispatcher.requests.post") as post:
        result = deliver_to_subscriber.run("extras", "course_published", COURSE_PAYLOAD)
    post.assert_not_called()
    assert result is None


def test_deliver_to_subscriber_http_error_reraised_for_retry(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", EXTRAS_URL, events=["course_published"]),
    ])
    response = mock.Mock(status_code=500)
    response.raise_for_status.side_effect = requests.HTTPError("server error")
    with mock.patch("openedx_sms_events.dispatcher.requests.post", return_value=response):
        with pytest.raises(requests.HTTPError):
            deliver_to_subscriber.run("extras", "course_published", COURSE_PAYLOAD)


def test_deliver_to_subscriber_connection_error_reraised_for_retry(settings):
    settings.SMS_EVENTS = _config([
        _subscriber("extras", EXTRAS_URL, events=["course_published"]),
    ])
    with mock.patch(
        "openedx_sms_events.dispatcher.requests.post",
        side_effect=requests.ConnectionError("boom"),
    ):
        with pytest.raises(requests.ConnectionError):
            deliver_to_subscriber.run("extras", "course_published", COURSE_PAYLOAD)


def test_deliver_to_subscriber_retry_configured_with_backoff():
    assert requests.RequestException in (deliver_to_subscriber.autoretry_for or ())
    assert deliver_to_subscriber.retry_backoff is True
    assert deliver_to_subscriber.max_retries == 5
    assert deliver_to_subscriber.retry_backoff_max == 600


def test_deliver_event_has_no_autoretry():
    # The fan-out task must not retry: it only schedules child tasks. Retrying
    # it would duplicate deliveries to every subscriber on any transient blip.
    # ``deliver_event`` is declared without autoretry_for, so the attribute is
    # absent (not just empty) — either way, nothing is configured to retry.
    assert not getattr(deliver_event, "autoretry_for", None)
