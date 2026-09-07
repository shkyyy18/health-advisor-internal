# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed (2026-09-07 audit)

- Correct hidden daily-sync VBS syntax; use the local venv interpreter, capture console logs, and propagate process failures through Windows launchers.
- Prefer the local interpreter in the task installer and export existing task XML before replacement/removal.
- Isolate test-collection configuration and LAN tokens with `HEALTH_ENV_FILE`, in addition to temporary test databases.
- Correct bridge dependency license attribution and distinguish mocked/local verification from live cloud integration.


### Added

- Mobile daily coaching card linking training, nutrition, recovery, and measurement actions.
- Mobile rotating meal plan with workout-aware carbohydrate portions and per-meal rationale.

### Changed

- Refresh the mobile plan after a quick meal log so seven-day coverage and confidence update immediately.

## [0.2.0] - 2026-07-15

### Added

- Fast manual meal logging through `POST /api/meals/quick` and the mobile page.
- Optional calorie and macronutrient fields without forcing users to invent values.
- Seven-day food logging coverage, record count, confidence, and data-gap messaging.
- Product positioning, food capture design, and GitHub experiment documentation.
- Synthetic desktop and mobile screenshots with no personal health data.
- Security, contribution, and CI documentation.

### Changed

- Repositioned the product as a local-first, data-driven fat-loss advisor.
- Moved Mi Fitness acquisition to the independent `mi_fitness_data_bridge` dependency.
- Removed the vendored connector implementation.
- Reduced recommendation confidence when food logging coverage is insufficient.

[0.2.0]: https://github.com/shkyyy18/health-advisor-internal/releases/tag/v0.2.0
