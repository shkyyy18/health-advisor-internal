# Release checklist

## Local validation

- [ ] Editable installation metadata succeeds.
- [ ] Tests and Python syntax checks pass.
- [ ] `git diff --check` passes.
- [ ] A wheel builds with the `app` package and both HTML templates, without `data` or `logs`.
- [ ] Tests use a temporary database and never access `data/health.db`.
- [ ] No `.env`, token, SQLite file, log, photo, export, or real health metric is tracked.
- [ ] Desktop and mobile screenshots contain synthetic data only.

## GitHub publication

- [ ] Create `shkyyy18/health-advisor` as a public repository.
- [ ] Push `main`.
- [ ] Confirm CI passes for Python 3.11, 3.12, and 3.13.
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
