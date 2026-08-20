# AGENTS.md

This project is maintained with Codex. Read `PROJECT_GUIDE.md` and `README.md` before work.

- Use `D:\AIWorkspace\projects\health-advisor-internal` as the stable path.
- Do not restore retired tool-specific agents, skills, prompts, memories, or private-path dependencies.
- Do not let multiple tools edit this tree or multiple jobs write the same SQLite database concurrently.
- Keep `.env`, health databases, authentication files, logs, and user health data out of Git.
- Export scheduled-task definitions before changing them and record the final migration state.
- **Operational rule:** After diagnosing and fixing any problem, and for all durable project decisions and user preferences, append them to the project memory file `D:\AIWorkspace\projects\health-advisor-internal\健康顾问-项目记忆.md`. Do not place project-specific notes in the global memory directory or the dispatcher memory file.

## Text encoding

- Python: pass `encoding="utf-8"` on every text file read/write; logs and text exports contain Chinese. Health data lives in SQLite, which stores text natively.
- PowerShell 5.1 (`run.ps1`, `scripts/*.ps1`): use explicit `-Encoding UTF8`, and save every `.ps1` as UTF-8 with BOM — without the BOM, PS 5.1 parses Chinese as GBK and the script breaks (observed 2026-07-20).
