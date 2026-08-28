# platform-plugin-sms-events

Open edX plugin that bridges Open edX lifecycle events to the SwissMOOC
satellite apps (swissmooc-extras, swissmooc-insights, swissmooc-catalog).
Installed into the CMS (Studio) image by swissmooc-tutor; registered via the
`cms.djangoapp` plugin entry point.

## Agent skills

### Issue tracker

Issues live as GitHub issues in `epfl-cede/platform-plugin-sms-events` (uses the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary, label string == role name (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
