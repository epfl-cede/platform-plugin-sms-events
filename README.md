# platform-plugin-sms-events

Open edX plugin that bridges Open edX lifecycle events to the SwissMOOC
satellite apps ([swissmooc-extras][extras], [swissmooc-insights][insights],
[swissmooc-catalog][catalog]).

Installed into the **CMS (Studio)** image by [swissmooc-tutor][tutor]; the app
is registered through the `cms.djangoapp` plugin entry point, so no manual
`INSTALLED_APPS` edit is needed in `edx-platform`.

## Why

SwissMOOC satellite apps need to react to Open edX events as they happen,
instead of polling. The first use case is the
[`course_xml_dump`][extras-issue] pipeline in swissmooc-extras: avoid nightly
re-dumps of unchanged courses by learning about Studio publishes in real time.

Packaging the listeners here (rather than patching the `epfl-cede/edx-platform`
fork) keeps the fork close to upstream and lets the satellite apps evolve
independently.

## What it does today

`SignalHandler.course_published` (fired by Studio on every course publish) is
connected to `openedx_sms_events.signals.on_course_published`, which:

1. Builds a plain-dict payload from the course key.
2. Schedules the `notify_course_published` Celery task via
   `transaction.on_commit`, so the HTTP call only runs if the publish
   transaction commits — and never on the Studio request thread.

The task POSTs the payload to the configured swissmooc-extras webhook:

```json
{
  "course_key": "course-v1:EPFL+DemoX+2025_T1",
  "org": "EPFL",
  "course": "DemoX",
  "run": "2025_T1",
  "instance_name": "epfl"
}
```

`instance_name` is the swissmooc *deployment* instance (`epfl`, `ethz`,
`oleg`, …) from `settings.INSTANCE_NAME`, injected per instance by the Tutor
`openedx-common-settings` patch. It is distinct from the Open edX `org`
(`EPFL`, `EPFLx`, …), which is an internal org *within* an instance; the
extras app uses `instance_name` to tell deployments apart.

Failed calls are retried with exponential backoff (up to 5 retries) and logged.

## Generic event dispatcher (expand phase)

`openedx_sms_events.dispatcher` is the generalized delivery machinery that
will replace the single-endpoint task above. It is landed **alongside**
`notify_course_published`, which remains the live path; nothing routes through
the dispatcher yet. The module separates three responsibilities behind a tiny
interface:

- **Routing** — `matching_subscribers(event_type, config)`, a pure function.
  A subscriber matches if its `events` list contains the event type or the
  `"*"` wildcard; an empty/missing `events` list opts out (fail safe).
- **Fan-out** — `deliver_event(event_type, payload)`, a Celery task that
  schedules one delivery task per matching subscriber. It has **no autoretry**:
  it only schedules children, so retrying it would duplicate every delivery.
- **Delivery** — `deliver_to_subscriber(name, event_type, payload)`, a Celery
  task that POSTs to one subscriber, looked up by name at call time so
  URL/token changes take effect on the next attempt. Autoretry with exponential
  backoff (max 5, 600s cap). A missing subscriber or empty URL is a logged
  no-op, not an error.

The subscriber list is configured under `SMS_EVENTS["subscribers"]`:

```python
SMS_EVENTS = {
    "subscribers": [
        {"name": "extras",  "url": "...", "auth_token": "...", "timeout": 5.0, "events": ["*"]},
        {"name": "catalog", "url": "...", "auth_token": "...", "timeout": 5.0, "events": ["course_published", "enrollment"]},
    ],
}
```

The dispatcher imports no edx-platform modules (`xmodule`/`opaque_keys`), so
it unit-tests with the same minimal Django + Celery + requests stack as the
task tests. The edx-importing seam stays isolated in `signals.py`. Adding an
event type will be a thin `@receiver` that builds a payload and calls
`deliver_event.delay(event_type, payload)`; adding a consumer will be a row in
`subscribers`.

## Future extensions

Additional signal listeners (enrollment, certificate, grade, library update)
and URL handlers for insights/catalog will live in this same package.

## Configuration

Settings live under the `SMS_EVENTS` dict:

| Key | Default | Purpose |
| --- | --- | --- |
| `course_published_webhook_url` | `""` | swissmooc-extras endpoint. Empty => the task is a no-op. |
| `auth_token` | `""` | Shared bearer token sent as `Authorization: Bearer <token>`. |
| `timeout` | `5.0` | Per-request HTTP timeout in seconds. |
| `org_to_tenant` | `{}` | Reserved for future per-tenant event routing; unused by the `course_published` listener. |

The package ships safe defaults via its `settings/common.py` plugin hook. Per
instance, values are rendered by the Tutor runtime patch
(`openedx-cms-common-settings`) in [swissmooc-swarm][swarm] and override the
defaults.

## Build & runtime integration

Build-time (pip-install into the openedx image) and runtime (settings) are
wired in the deployment repos, not here:

- **Build:** `swissmooc-tutor/plugins/sms-build-events.py` pip-installs this
  package from a pinned git SHA into the CMS image.
- **Runtime:** `swissmooc-swarm/tutor/plugins/sms-events.py` injects the
  `SMS_EVENTS` settings and `SMS_EVENTS_*` config defaults.

See [swissmooc-tutor#10](https://github.com/epfl-cede/swissmooc-tutor/issues/10)
for the full integration plan.

## Development

### Unit tests (no openedx required)

The task tests run with a minimal Django + Celery + requests stack:

```bash
pip install -r test_requirements.txt
pytest
```

### Signal tests (openedx environment required)

`openedx_sms_events/tests/test_signals.py` imports `xmodule` and
`opaque_keys`, so it is skipped outside an openedx environment. Run it inside
the openedx devstack / CI image where `edx-platform` is importable.

[extras]: https://github.com/epfl-cede/swissmooc-extras
[insights]: https://github.com/epfl-cede/swissmooc-insights
[catalog]: https://github.com/epfl-cede/swissmooc-catalog
[tutor]: https://github.com/epfl-cede/swissmooc-tutor
[swarm]: https://github.com/epfl-cede/swissmooc-swarm
[extras-issue]: https://github.com/epfl-cede/swissmooc-extras/issues/28
