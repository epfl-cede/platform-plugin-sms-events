# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- `course_published` now routes through the generic dispatcher: `on_course_published`
  schedules `deliver_event.delay("course_published", payload)` via
  `transaction.on_commit`, fanning the event out to every configured subscriber.
  The retired single-endpoint `notify_course_published` task and the
  `openedx_sms_events.tasks` module have been removed — there is now one
  delivery path, not two.
- The `course_published` payload is now a self-describing event envelope with
  the `event_type` (so a generic subscriber endpoint can dispatch on it), a
  stable `event_id` (uuid4, generated once in the signal receiver), and
  `occurred_at` (UTC publish time), so downstream consumers can deduplicate
  dispatcher retries on `event_id`.
- The default `SMS_EVENTS` is now the subscriber-list shape: extras as the one
  subscriber (`events: ["*"]`, empty URL -> no-op until configured). The old
  single `course_published_webhook_url` / `auth_token` / `timeout` /
  `org_to_tenant` keys are gone.
- The swissmooc-swarm Tutor runtime patch (`tutor/plugins/sms-events.py`)
  renders the per-instance subscriber list (URLs, per-subscriber tokens,
  event-type routing); a rendered instance config shows extras subscribed.

### Fixed
- Syntax error in `signals.py` (stray double comma on the `course_key`
  payload field) that went undetected because the module is never imported in
  the unit-test environment (it pulls in `xmodule`, so the signal tests skip
  outside the openedx image).

### Added
- Generic event dispatcher (`openedx_sms_events.dispatcher`) that fans one
  event type out to N configured subscribers. The dispatcher separates three
  responsibilities behind a tiny interface: `matching_subscribers` (pure
  routing by event type / `"*"` wildcard), `deliver_event` (fan-out Celery
  task, no autoretry — it only schedules children), and `deliver_to_subscriber`
  (per-subscriber POST with exponential backoff, max 5 retries, 600s cap;
  missing subscriber or empty URL is a logged no-op). Subscribers are looked up
  by name at call time so URL/token changes take effect on the next attempt.
  The module imports no edx-platform code, so it unit-tests outside the
  openedx image.
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
- Byte-compile test (`tests/test_compile.py`) that syntax-checks every module
  in the package, guarding the `xmodule`-gated `signals.py` (unimportable in
  the unit-test env) against silent syntax errors.
