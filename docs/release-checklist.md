# Release checklist

## Local validation

- [x] Editable installation metadata succeeds.
- [x] Tests and Python syntax checks pass.
- [x] `git diff --check` passes.
- [x] A wheel builds with the `app` package and both HTML templates, without `data` or `logs`.
- [x] Tests use a temporary database and never access `data/health.db`.
- [x] No `.env`, token, SQLite file, log, photo, export, or real health metric is tracked.
- [x] Desktop and mobile screenshots contain synthetic data only.

## GitHub publication

- [x] Create `shkyyy18/health-advisor` as a public repository.
- [x] Push `main`.
- [x] Confirm CI passes for Python 3.11, 3.12, and 3.13.
- [ ] Enable private vulnerability reporting.
- [ ] Configure branch protection or a ruleset after the first push.
- [ ] Publish release notes from `CHANGELOG.md`.
- [ ] Link the independent Mi Fitness Data Bridge repository in repository metadata.

## Service deployment

- [ ] Stop the existing Health Assistant process before deploying new code.
- [ ] Confirm no sync job or second process is writing `data/health.db`.
- [ ] Start exactly one service process and verify `/health`, `/`, and `/mobile`.
- [ ] Confirm the service still binds to `127.0.0.1` unless an authenticated tunnel is intentionally configured.

## Product experiment

- [ ] Track successful installations and weekly report generation.
- [ ] Track seven-day food logging coverage and four-week retention.
- [ ] Track whether users execute one food change and one training/recovery change each week.
- [ ] Do not enable default telemetry; collect reports only with explicit user participation.

## Validation evidence

- 2026-07-16: 39 tests and the configured syntax checks passed; `git diff --check` passed.
- 2026-07-16: editable-install metadata dry-run passed. A fresh wheel was built and installed into an isolated target; it contains both templates and excludes `data` and `logs`.
- 2026-07-16: the autouse test fixture redirects database access to `tmp_path`; tracked-file scanning found no secret, database, log, export, or screenshot artifacts. With no tracked screenshots, the synthetic-screenshot requirement is currently satisfied by absence.
- 2026-07-16: the public repository, pushed `main`, and successful Python 3.11/3.12/3.13 CI were verified. The local branch is ahead of `origin/main`, so current local work is not yet published.
- Still open: vulnerability reporting, branch rules, GitHub Release notes, repository metadata for the bridge, deployment checks, and product experiment evidence.
