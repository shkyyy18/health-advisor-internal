# PROJECT_GUIDE.md

## Project scope

- Stable path: `D:\AIWork\repos\health-advisor-internal`.
- This is a local-first, data-driven fat-loss advisor that combines body composition, sleep, activity, Strava, and food logs into explainable weekly actions.
- Mi Fitness acquisition is an external data-source dependency provided by `mi_fitness_data_bridge`; it is not this product's headline or a vendored component.
- This project is for personal fitness and weight management, not medical diagnosis or treatment.

## Working rules

1. Read the workspace rules, `AGENTS.md`, and `README.md` before editing.
2. Do not restore retired tool-specific agents, skills, prompts, memories, or private-path dependencies.
3. Never commit secrets, login tokens, SQLite files, logs, photos, exports, or personal health data.
4. Stop services and sync jobs before moving or maintaining `data/health.db`; SQLite must have one writer.
5. New configuration, scheduled tasks, scripts, and documentation must use the public path.
6. Do not copy the Mi Fitness bridge implementation into this repository. Install it as a dependency.
7. State data gaps and uncertainty; do not make medical claims.
8. Run tests and Python syntax checks after code changes.
9. Preserve third-party licenses. Do not copy GPL project code into this project.
