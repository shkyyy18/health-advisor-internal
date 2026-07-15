## Summary

Describe the user problem and the proposed change.

## Validation

- [ ] `python -m pytest -q -p no:cacheprovider`
- [ ] `python -m py_compile app/analytics.py app/db.py app/main.py app/xiaomi_sync.py`
- [ ] `git diff --check`

## Privacy and product boundaries

- [ ] Tests and screenshots use synthetic data and temporary databases only
- [ ] No `.env`, token, SQLite file, log, meal photo, export, or personal metric is included
- [ ] Mi Fitness connector code remains in the separate bridge repository
- [ ] Missing data and uncertainty are stated explicitly
- [ ] The change does not make medical, diagnostic, treatment, or guaranteed weight-loss claims

## User outcome

Explain how this change improves food logging, data completeness, weekly recommendations, action completion, or retention.
