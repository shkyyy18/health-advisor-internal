# dailysync-rev architecture review

Reviewed: 2026-07-14

## Positioning

`gooin/dailysync-rev` is primarily an activity transport and automation project. It downloads original Garmin activity files from one Garmin region and uploads them to the other. It also contains optional RunningQuotient and Google Sheets collection helpers. It explicitly excludes physiological data such as sleep, Body Battery, and daily steps from its main migration scope.

The local Health Assistant is an analysis product: it unifies Strava activities with Xiaomi sleep, body composition, daily metrics, heart rate, SpO2, stress, and nutrition, then calculates transparent readiness and training recommendations.

## Main differences

| Area | dailysync-rev | Health Assistant |
|---|---|---|
| Primary job | Cross-region activity transport | Local health storage, analysis, and advice |
| Main data | Garmin activity files | Strava activities plus Xiaomi health and nutrition |
| Automation | GitHub Actions, Docker, cron, manual scripts | Windows scheduled task, webhook, dashboard refresh |
| State | Latest activity comparison plus saved Garmin sessions | Normalized SQLite health history |
| Analysis | Mostly passes through Garmin/RQ fields | Transparent load proxy, sleep debt, readiness, body/nutrition trends |
| Deployment | Fork/secrets historically made self-hosting easy | Local-first Windows service |
| License | GPL-3.0 | Do not copy its source; borrow patterns only |

## Why it attracted stars and forks

1. It solves a painful China/global Garmin ecosystem split with a narrow, visible outcome.
2. Bidirectional migration unlocks Strava and domestic-app workflows.
3. Historical GitHub Actions deployment made a fork function like a personal hosted instance; the unusually high fork count is consistent with that usage pattern.
4. The README is long, visual, Chinese-language, and includes multiple deployment paths and troubleshooting.
5. The project provides immediate utility without requiring users to understand training science.

## Current caveat

The current README says newly forked GitHub Actions deployments no longer work for accounts affected by Garmin verification/ECG login behavior and recommends a Web version instead. Therefore GitHub Actions should not be copied as the only automation path.

## Recommended patterns to borrow

1. Separate connector/transport code from analysis code.
2. Add a connector status page with last success, rows fetched, cursor, error, and retry.
3. Store idempotency keys and per-source sync cursors instead of comparing only the latest timestamp.
4. Preserve original activity files in a deduplicated raw archive before normalization.
5. Offer one-command scheduled-task templates, Docker only as an optional path, and explicit health checks.
6. Keep each source independently operable: Strava, Xiaomi, and a future Garmin connector.
7. Provide practical Chinese setup screenshots and troubleshooting.

## Patterns not to copy

- Do not copy GPL-3.0 source into this project.
- Do not rely on a default/fixed AES passphrase for session storage or auto-commit an encrypted session database to a fork.
- Do not use long-lived account passwords in GitHub Secrets as the default for sensitive health data.
- Do not run both synchronization directions without collision protection.
- Do not use latest-timestamp-only logic as the sole deduplication strategy.
- Add automated connector tests; the reviewed repository does not contain a normal test suite even though `package.json` declares a test script.
