# PROJECT_GUIDE.md

## Project scope

- Stable local working path: `D:\AIWork\projects\health-advisor-internal`.
- Reviewed public releases use `D:\AIWork\publishing\health-advisor-internal`; do not publish the personal working tree or its old history.
- The personal goal is healthy exercise and everyday life, confirmed on 2026-11-09. Do not reuse retired weight-loss targets, training plans, readiness scores or nutrition prescriptions. The current local plan and its evidence limitations are in data/current_plan/.
- Mi Fitness acquisition is an external data-source dependency provided by `mi_fitness_data_bridge`; it is not this product's headline or a vendored component.
- This project supports personal health habits and fitness. Clinical findings and unresolved symptoms require appropriate professional assessment; do not invent missing medical results.

## Working rules

1. Read the workspace rules, `AGENTS.md`, and `README.md` before editing.
2. Do not restore retired tool-specific agents, skills, prompts, memories, or private-path dependencies.
3. Never commit secrets, login tokens, SQLite files, logs, photos, exports, or personal health data.
4. Stop services and sync jobs before moving or maintaining `data/health.db`; SQLite must have one writer.
5. Personal runtime configuration, scheduled tasks and operational documentation use `D:/AIWork/projects/health-advisor-internal`. Only reviewed public release artifacts use `D:/AIWork/publishing/health-advisor-internal`; never move personal configuration or data into that publishing tree. (Clarified 2026-11-02 to match the current boundary above.)
6. Do not copy the Mi Fitness bridge implementation into this repository. Install it as a dependency.
7. State data gaps and uncertainty; do not make medical claims.
8. Run tests and Python syntax checks after code changes.
9. Preserve third-party licenses. Do not copy GPL project code into this project.

2026-11-09最新本人授权：11/10起温和减重，历史数据作暂定起点立即行动，不等待两周；data/current_plan/adaptive-policy.md为动态调整规则。每日21:05同步、当日复盘和次日卡片，周日21:20趋势复盘；旧引擎/网页看板仍不恢复。
