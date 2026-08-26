"""
openedx_sms_events Django application initialization.

Registered as a ``cms.djangoapp`` plugin entry point (see ``pyproject.toml``),
so Open edX's plugin framework loads this AppConfig into Studio automatically.

Settings defaults are injected through the ``settings_config`` block below; per
instance overrides come from the Tutor runtime patch in ``swissmooc-swarm``.
"""

from django.apps import AppConfig


class OpenedxSmsEventsConfig(AppConfig):
    """
    Configuration for the openedx_sms_events Django application.
    """

    name = "openedx_sms_events"
    verbose_name = "Open edX SMS Events"

    plugin_app = {
        # Inject default SMS_EVENTS settings into the CMS. The ``plugin_settings``
        # helper only sets ``SMS_EVENTS`` when it is not already defined, so
        # per-instance values rendered by the Tutor runtime patch
        # (openedx-cms-common-settings) always win.
        "settings_config": {
            "cms.djangoapp": {
                "common": {
                    "relative_path": "settings.common",
                },
            },
        },
    }

    def ready(self):
        # Imported for its side effect: connecting the course_published
        # receiver. Done in ``ready`` so it only runs once Django is fully
        # initialised, and only in the CMS (this app is cms-only).
        from openedx_sms_events import signals  # noqa: F401, pylint: disable=unused-import
