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

## What it does

`SignalHandler.course_published` (fired by Studio on every course publish) is
connected to `openedx_sms_events.signals.on_course_published`, which:

1. Builds a self-describing event payload from the course key, including a
   stable `event_id` / `occurred_at` identity so downstream consumers can
   deduplicate retries.
2. Schedules the `deliver_event` Celery task (the dispatcher) via
   `transaction.on_commit`, so the fan-out only runs if the publish
   transaction commits — and never on the Studio request thread.

The dispatcher fans the event out to every subscriber that opted into
`course_published` (or `"*"`). Today there is one subscriber, swissmooc-extras,
so a publish reaches extras's existing webhook — now via the dispatcher rather
than the retired single-endpoint task. The payload POSTed to extras:

```json
{
  "event_id": "9f1c...-...-...",
  "occurred_at": "2025-01-31T14:09:00.000000+00:00",
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
extras app uses `instance_name` to tell deployments apart. `event_id` is
generated once in the signal receiver and is immutable across the dispatcher's
retry chain, so a redelivery produces one row on the consumer side, not many.

Failed deliveries are retried per subscriber with exponential backoff (up to 5
retries, 600s cap) and logged; one dead consumer cannot stall another, because
each gets its own task with its own retry chain.

## Generic event dispatcher

`openedx_sms_events.dispatcher` is the delivery machinery. It separates three
responsibilities behind a tiny interface:

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
event type is a thin `@receiver` that builds a payload and calls
`deliver_event.delay(event_type, payload)`; adding a consumer is a row in
`subscribers`.

## Future extensions

Additional signal listeners (enrollment, certificate, grade, library update)
and URL handlers for catalog will live in this same package.

## Configuration

Settings live under the `SMS_EVENTS` dict, in the subscriber-list shape:

| Key | Purpose |
| --- | --- |
| `subscribers` | List of subscriber dicts. Each has `name` (stable id), `url`, `auth_token` (per-subscriber bearer token), `timeout` (per-request HTTP seconds), and `events` (event types to opt into, or `["*"]` for all). An empty `url` makes that subscriber a no-op. |

The package ships safe defaults via its `settings/common.py` plugin hook:
extras as the one subscriber with an empty URL (no-op until configured). Per
instance, the subscriber list is rendered by the Tutor runtime patch
(`openedx-cms-common-settings`) in [swissmooc-swarm][swarm] and overrides the
defaults.

## Build & runtime integration

Build-time (pip-install into the openedx image) and runtime (settings) are
wired in the deployment repos, not here:

- **Build:** `swissmooc-tutor/plugins/sms-build-events.py` pip-installs this
  package from a pinned git SHA into the CMS image.
- **Runtime:** `swissmooc-swarm/tutor/plugins/sms-events.py` renders the
  per-instance `SMS_EVENTS` subscriber list and `SMS_EVENTS_*` config defaults.

See [swissmooc-tutor#10](https://github.com/epfl-cede/swissmooc-tutor/issues/10)
for the full integration plan.

## Development

### Unit tests (no openedx required)

The dispatcher tests run with a minimal Django + Celery + requests stack:

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
