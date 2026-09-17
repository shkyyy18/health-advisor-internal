# Project guide

This is the code-only distribution of Health Advisor, a local-first tool for cyclists and other sports enthusiasts who want to analyze Strava activities alongside their own health data, not a medical service.

Cyclists using Strava are the primary audience; other sports enthusiasts with the same combined-analysis need are also in scope. Training load, recovery, body-composition trends and nutrition records are the current focus. Fat loss is one use case, not the sole product identity. Current device-health integration uses Mi Fitness Data Bridge; do not imply universal device support or sport-specific performance models. Preserve this positioning in public descriptions without including any individual user's background or records.

- Keep the separate Mi Fitness connector as a sibling dependency; preserve all third-party notices and licenses.
- Keep all personal health records, credentials, logs, local configuration and personal project memory out of Git.
- Do not restore historical developer memory or copy real data into fixtures, screenshots or reports.
- Run tests with synthetic data only. The test fixtures isolate settings and databases.
- All publication changes require manual privacy review and a refreshed content manifest.
- Run `python scripts/check_publication.py --history` before publication. No test establishes clinical effectiveness.
