# Project guide

This is the code-only distribution of Health Advisor, a local-first personal fitness tool, not a medical service.

- Keep the separate Mi Fitness connector as a sibling dependency; preserve all third-party notices and licenses.
- Keep all personal health records, credentials, logs, local configuration and personal project memory out of Git.
- Do not restore historical developer memory or copy real data into fixtures, screenshots or reports.
- Run tests with synthetic data only. The test fixtures isolate settings and databases.
- All publication changes require manual privacy review and a refreshed content manifest.
- Run `python scripts/check_publication.py --history` before publication. No test establishes clinical effectiveness.
