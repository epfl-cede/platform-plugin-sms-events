"""
Minimal Django settings for running the package's unit tests outside the
openedx devstack.

Only the task tests need a configured Django settings object (they read
``settings.SMS_EVENTS``). The signal tests live in ``test_signals.py`` and skip
themselves when ``xmodule`` is not importable.
"""

SECRET_KEY = "unit-test-secret"

DEBUG = False
USE_TZ = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

# Do NOT install the openedx_sms_events app here: its ``ready()`` imports
# ``signals`` which pulls in ``xmodule`` / ``opaque_keys`` (unavailable outside
# the openedx environment). The task tests import the task module directly.
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
]

from openedx_sms_events.settings.common import DEFAULT_SMS_EVENTS  # noqa: E402

SMS_EVENTS = dict(DEFAULT_SMS_EVENTS)
