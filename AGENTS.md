# AGENTS.md

This project is maintained with Codex. Read `PROJECT_GUIDE.md` and `README.md` before work.

- Use `D:\CodexWorkspace\projects\health_assistant` as the stable path.
- Do not restore retired tool-specific agents, skills, prompts, memories, or private-path dependencies.
- Do not let multiple tools edit this tree or multiple jobs write the same SQLite database concurrently.
- Keep `.env`, health databases, authentication files, logs, and user health data out of Git.
- Export scheduled-task definitions before changing them and record the final migration state.
