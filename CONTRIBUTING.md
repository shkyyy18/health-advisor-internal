# Contributing

Thanks for helping improve Health Advisor.

## Good first contributions

- Add synthetic fixtures for another supported device or activity type.
- Reduce the time needed to record a meal.
- Improve explainability and data-gap warnings.
- Add setup documentation for another operating system.
- Improve tests without adding real personal data.

## Development

```bash
python -m venv .venv
pip install -e '.[dev,xiaomi]'
pip install -e ../mi_fitness_data_bridge
python -m pytest -q -p no:cacheprovider
```

## Rules

- Use synthetic data in tests, screenshots, Issues, and pull requests.
- Never commit tokens, `.env`, SQLite files, logs, exports, or meal photos.
- Do not copy the Mi Fitness connector source into this repository.
- Do not make medical, diagnostic, or guaranteed weight-loss claims.
- Explain assumptions, missing data, and uncertainty in recommendation changes.
- Keep one SQLite writer at a time.

Open an Issue before a large architecture change so the product boundary stays focused on turning data into sustainable fat-loss actions.
