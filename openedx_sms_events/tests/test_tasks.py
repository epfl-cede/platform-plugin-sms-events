"""
Unit tests for ``openedx_sms_events.tasks.notify_course_published``.

These run with a minimal Django + Celery + requests stack (no openedx
platform). The task body is exercised directly via ``Task.run`` so no Celery
broker is required.
"""

from unittest import mock

import pytest
import requests

from openedx_sms_events.tasks import notify_course_published

WEBHOOK_URL = "https://extras.example.edu/api/v1/course-publish/"
PAYLOAD = {
    "course_key": "course-v1:EPFL+DemoX+2025_T1",
    "org": "EPFL",
    "course": "DemoX",
    "run": "2025_T1",
    "instance_name": "epfl",
}


def _config(**overrides):
    config = {
        "course_published_webhook_url": WEBHOOK_URL,
        "auth_token": "secret-token",
        "timeout": 5.0,
    }
    config.update(overrides)
    return config


def test_no_url_configured_skips_request(settings):
    settings.SMS_EVENTS = _config(course_published_webhook_url="")
    with mock.patch("openedx_sms_events.tasks.requests.post") as post:
        result = notify_course_published.run(PAYLOAD)
    post.assert_not_called()
    assert result is None


def test_posts_payload_with_bearer_auth_and_timeout(settings):
    settings.SMS_EVENTS = _config()
    response = mock.Mock(status_code=200)
    with mock.patch("openedx_sms_events.tasks.requests.post", return_value=response) as post:
        result = notify_course_published.run(PAYLOAD)

    post.assert_called_once()
    _, kwargs = post.call_args
    assert kwargs["json"] == PAYLOAD
    assert kwargs["timeout"] == 5.0
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"
    assert result == {"status_code": 200}


def test_no_auth_token_omits_authorization_header(settings):
    settings.SMS_EVENTS = _config(auth_token="")
    response = mock.Mock(status_code=201)
    with mock.patch("openedx_sms_events.tasks.requests.post", return_value=response) as post:
        result = notify_course_published.run(PAYLOAD)

    _, kwargs = post.call_args
    assert "Authorization" not in kwargs["headers"]
    assert result == {"status_code": 201}


def test_timeout_string_is_coerced_to_float(settings):
    settings.SMS_EVENTS = _config(timeout="2.5")
    response = mock.Mock(status_code=200)
    with mock.patch("openedx_sms_events.tasks.requests.post", return_value=response) as post:
        notify_course_published.run(PAYLOAD)

    _, kwargs = post.call_args
    assert kwargs["timeout"] == 2.5


def test_invalid_timeout_falls_back_to_default(settings):
    settings.SMS_EVENTS = _config(timeout="not-a-number")
    response = mock.Mock(status_code=200)
    with mock.patch("openedx_sms_events.tasks.requests.post", return_value=response) as post:
        notify_course_published.run(PAYLOAD)

    _, kwargs = post.call_args
    assert kwargs["timeout"] == 5.0


def test_http_error_is_reraised_for_retry(settings):
    settings.SMS_EVENTS = _config()
    response = mock.Mock(status_code=500)
    response.raise_for_status.side_effect = requests.HTTPError("server error")
    with mock.patch("openedx_sms_events.tasks.requests.post", return_value=response):
        with pytest.raises(requests.HTTPError):
            notify_course_published.run(PAYLOAD)


def test_connection_error_is_reraised_for_retry(settings):
    settings.SMS_EVENTS = _config()
    with mock.patch(
        "openedx_sms_events.tasks.requests.post",
        side_effect=requests.ConnectionError("boom"),
    ):
        with pytest.raises(requests.ConnectionError):
            notify_course_published.run(PAYLOAD)


def test_retry_is_configured_with_backoff():
    """Failed webhook calls must be retried with backoff (acceptance criterion)."""
    assert requests.RequestException in (notify_course_published.autoretry_for or ())
    assert notify_course_published.retry_backoff is True
    assert notify_course_published.max_retries == 5
