# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
