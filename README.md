# Health Assistant

`health_assistant` is a local-first personal health data hub available at `http://127.0.0.1:8000/`.

## Capabilities

- Sync Strava activities and training history.
- Sync Xiaomi Mi Fitness steps, sleep, body composition, heart rate, SpO2, and stress.
- Calculate training load, recovery/readiness, weight/body-fat trends, and explainable suggestions.
- Provide food logging, image-assisted nutrition estimates, and a local dashboard.

## Architecture

- **Connector layer:** Strava and Xiaomi Mi Fitness.
- **Storage layer:** `data/health.db`; only one writer is allowed at a time.
- **Analysis layer:** readiness, training load, trends, and recommendations.
- **Presentation layer:** FastAPI and the local dashboard.

Do not recreate compatibility copies for retired tool-specific directories.

## Install and test

```powershell
cd D:\AIWorkspace\projects\health_assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,xiaomi]"
python -m pytest -q -p no:cacheprovider
```

Copy `.env.example` to `.env`, fill local secrets, then run:

```powershell
.\run.ps1
```

## First Xiaomi login

The dashboard refresh button now calls the Mi Fitness cloud connector directly; it no longer imports an old JSON directory. Create a local authentication file once:

```powershell
cd D:\AIWorkspace\projects\health_assistant
python scripts\mijia_health_sync.py login
```

The script creates a QR image. Scan it with the Mi Home app. Credentials are stored in the Git-ignored file `data\.mijia\auth.json`.

```powershell
python scripts\mijia_health_sync.py doctor
python scripts\mijia_health_sync.py sync
```

The authentication file contains sensitive login tokens. Never upload, print, or share it.

## Runtime data

- Database: `data\health.db`
- Xiaomi auth: `data\.mijia\auth.json`
- Logs: `logs\`
- Local config: `.env`

These files are excluded from Git. See `THIRD_PARTY_NOTICES.md` for third-party licenses.
