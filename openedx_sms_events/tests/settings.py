"""
Minimal Django settings for running the package's unit tests outside the
openedx devstack.

Only the dispatcher tests need a configured Django settings object (they read
``settings.SMS_EVENTS``). The signal tests live in ``test_signals.py`` and skip
themselves when ``xmodule`` is not importable.
"""

import copy

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
# the openedx environment). The dispatcher tests import the dispatcher module
# directly.
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
]

from openedx_sms_events.settings.common import DEFAULT_SMS_EVENTS  # noqa: E402

# Deep copy so a test mutating the subscriber list cannot leak back into the
# canonical default (the subscribers list and its dicts are otherwise shared by
# reference with a plain dict() copy).
SMS_EVENTS = copy.deepcopy(DEFAULT_SMS_EVENTS)
