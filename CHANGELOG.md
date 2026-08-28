# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Generic event dispatcher (`openedx_sms_events.dispatcher`) that fans one
  event type out to N configured subscribers, alongside the existing
  single-endpoint `notify_course_published` task (which stays the live path).
  The dispatcher separates three responsibilities behind a tiny interface:
  `matching_subscribers` (pure routing by event type / `"*"` wildcard),
  `deliver_event` (fan-out Celery task, no autoretry — it only schedules
  children), and `deliver_to_subscriber` (per-subscriber POST with exponential
  backoff, max 5 retries, 600s cap; missing subscriber or empty URL is a logged
  no-op). Subscribers are looked up by name at call time so URL/token changes
  take effect on the next attempt. The module imports no edx-platform code,
  so it unit-tests outside the openedx image. Nothing routes through it yet.
- Initial package structure with `OpenedxSMSEventsConfig` Django app registered
  as a `cms.djangoapp` plugin entry point.
- `course_published` signal receiver that schedules a Celery task after the
  Studio publish transaction commits. Payload includes `instance_name`
  (from `settings.INSTANCE_NAME`) so the extras app can distinguish
  deployments, separate from the Open edX internal `org`.
- `notify_course_published` Celery task that POSTs the course key, org, course,
  and run to a configurable swissmooc-extras webhook, with bearer-token auth,
  configurable timeout, and exponential backoff retries.
- Plugin settings (`SMS_EVENTS`) with sensible defaults (webhook URL, auth
  token, timeout, and a reserved `org_to_tenant` mapping), overridable per
  instance via Tutor runtime patches.
- Unit tests for the task and signal wiring.
