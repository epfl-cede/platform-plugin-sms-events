"""
Default SMS_EVENTS settings, applied to the CMS ``common`` settings by the
Open edX plugin framework.

The ``plugin_settings`` helper only sets ``SMS_EVENTS`` when it is not already
defined, so values rendered by the Tutor runtime patch
(``openedx-cms-common-settings`` in ``swissmooc-swarm``) always take
precedence. This keeps the package self-contained with safe defaults for local
development and tests.
"""

# Canonical default shape for SMS_EVENTS. Kept in one place so the settings
# hook, the Tutor runtime patch, and the tests all agree on the keys.
DEFAULT_SMS_EVENTS = {
    # swissmooc-extras endpoint that records the publish time, e.g.
    # "https://extras.<instance>/api/v1/course-publish/". Empty by default ->
    # the task becomes a no-op until configured.
    "course_published_webhook_url": "",
    # Shared bearer token authenticating the webhook request.
    "auth_token": "",
    # Per-request HTTP timeout in seconds.
    "timeout": 5.0,
    # Reserved for future per-tenant routing of events to a tenant's satellite
    # apps (see swissmooc-tutor#10). Unused by the course_published listener,
    # which posts to the single per-instance webhook URL above; declared here so
    # the settings shape matches the spec and the Tutor patch can populate it.
    "org_to_tenant": {},
}


def plugin_settings(settings):
    """
    Inject default ``SMS_EVENTS`` settings if not already configured.
    """
    if not hasattr(settings, "SMS_EVENTS"):
        settings.SMS_EVENTS = dict(DEFAULT_SMS_EVENTS)
