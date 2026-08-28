"""
Default SMS_EVENTS settings, applied to the CMS ``common`` settings by the
Open edX plugin framework.

The ``plugin_settings`` helper only sets ``SMS_EVENTS`` when it is not already
defined, so values rendered by the Tutor runtime patch
(``openedx-cms-common-settings`` in ``swissmooc-swarm``) always take
precedence. This keeps the package self-contained with safe defaults for local
development and tests.

The default shape is the subscriber list: one event fans out to every
subscriber that opted into it (see :mod:`openedx_sms_events.dispatcher`).
swissmooc-extras is the one subscriber, configured with an empty URL so the
delivery task is a no-op until the Tutor patch populates it — preserving the
pre-dispatcher behaviour where a publish only reaches extras once its webhook
URL is configured per instance.
"""

# Canonical default shape for SMS_EVENTS. Kept in one place so the settings
# hook, the Tutor runtime patch, and the tests all agree on the keys.
#
# extras subscribes to every event type (the ``"*"`` wildcard) because it is
# the durable event store / hub for swissmooc-insights. Its URL is empty by
# default -> delivery is a no-op until configured per instance.
DEFAULT_SMS_EVENTS = {
    "subscribers": [
        {
            "name": "extras",
            "url": "",
            "auth_token": "",
            "timeout": 5.0,
            "events": ["*"],
        },
    ],
}


def plugin_settings(settings):
    """
    Inject default ``SMS_EVENTS`` settings if not already configured.
    """
    if not hasattr(settings, "SMS_EVENTS"):
        settings.SMS_EVENTS = dict(DEFAULT_SMS_EVENTS)
