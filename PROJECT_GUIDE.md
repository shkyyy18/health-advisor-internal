# PROJECT_GUIDE.md

## Project scope

- This is a local-first personal health data hub for Strava and Xiaomi Mi Fitness data.
- Stable public path: `D:\AIWorkspace\projects\health_assistant`.
- The project is maintained with Codex and must not depend on retired tool-specific directories.

## Working rules

1. Read the workspace rules, `AGENTS.md`, and `README.md` before editing.
2. Do not restore retired tool-specific agents, skills, prompts, memories, or private-path dependencies.
3. Never commit secrets, login tokens, SQLite files, logs, or personal health data.
4. Stop services and sync jobs before moving or maintaining `data/health.db`; SQLite must have one writer.
5. New configuration, scheduled tasks, scripts, and documentation must use the public path.
6. Run tests and Python syntax checks after code changes.
7. Preserve third-party licenses. Do not copy GPL project code into this project.
