# Release checklist

## Local validation

- [x] Editable installation metadata succeeds.
- [x] Tests and Python syntax checks pass.
- [x] `git diff --check` passes.
- [x] A wheel builds with the `app` package and both HTML templates, without `data` or `logs`.
- [x] Tests use a temporary database and never access `data/health.db`.
- [x] No `.env`, token, SQLite file, log, photo, export, or real health metric is tracked.
- [x] Desktop and mobile screenshots contain synthetic data only.

Historical checked items below are not evidence that the current commit CI or a live deployment has been revalidated. See the dated audit evidence.

## GitHub publication

- [x] Maintain `shkyyy18/health-advisor-internal` as the private primary repository.
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
- [ ] Confirm the intended bind address: supplied Windows launchers bind `0.0.0.0` for token-protected LAN access; use `--host 127.0.0.1` for loopback-only deployment. Public tunnels require separate explicit opt-in.

## Product experiment

- [ ] Track successful installations and weekly report generation.
- [ ] Track seven-day food logging coverage and four-week retention.
- [ ] Track whether users execute one food change and one training/recovery change each week.
- [ ] Do not enable default telemetry; collect reports only with explicit user participation.

## Validation evidence

- 2026-07-16: 39 tests and the configured syntax checks passed; `git diff --check` passed.
- 2026-07-16: editable-install metadata dry-run passed. A fresh wheel was built and installed into an isolated target; it contains both templates and excludes `data` and `logs`.
- 2026-07-16: the autouse test fixture redirects database access to `tmp_path`; tracked-file scanning found no secret, database, log, export, or screenshot artifacts. With no tracked screenshots, the synthetic-screenshot requirement is currently satisfied by absence.
- 2026-07-16: the public repository, pushed `main`, and successful Python 3.11/3.12/3.13 CI were verified. The local branch contains local validation fixes; publish only after review (do not push automatically).
- Still open: vulnerability reporting, branch rules, GitHub Release notes, repository metadata for the bridge, deployment checks, and product experiment evidence.

## 2026-09-07 local audit

- `shkyyy18/health-advisor-internal` is the current repository and project URL; legacy `shkyyy18/health-advisor` is not used by the local checkout.
- Fresh-install dashboard, `/health`, summary/API routes, quick meal logging, Xiaomi mock sync, and Strava webhook/security flows were exercised by the regression suite.
- `python -m pytest -q -p no:cacheprovider`: 88 passed, 1 warning.
- `python -m py_compile` passed for application and sync entry points.
- `python -m pip wheel --no-deps --no-build-isolation --wheel-dir output/validation-wheel .` succeeded. An isolated installed-wheel server returned HTTP 200 for `/health`, `/`, `/mobile`, summary/dashboard APIs, and JS/CSS; a synthetic quick meal was persisted. The temporary process was stopped afterwards.
- Seven Windows launcher tests use stub projects (paths with spaces), verifying VBS execution, local venv selection, stdout/stderr capture, exit codes 0/7, BAT backend exit propagation, and PowerShell syntax without touching live services/tasks.
- Tests isolate import-time `.env`/LAN credentials as well as SQLite. Real cloud login, OAuth and meal-analysis-provider integration remain unverified. Existing scheduled tasks and the live service were not changed.
