# Security policy

## Supported versions

Security fixes are applied to the current `main` branch. The project is pre-1.0 and does not yet promise backports to old releases.

## Reporting a vulnerability

Do not open a public Issue for vulnerabilities involving credentials, authentication bypass, arbitrary file access, or exposure of personal health data. Use GitHub private vulnerability reporting after the repository is published, or contact the maintainers through a private channel listed in the repository profile.

Include a minimal reproduction with synthetic data only. Never send a real Xiaomi passToken, Strava token, `.env`, SQLite database, meal photo, or screenshot containing personal metrics.

## Security assumptions

- The FastAPI service is designed to bind to `127.0.0.1` by default.
- Public tunnels are disabled by default and require the explicit local opt-in `HEALTH_ENABLE_NGROK=true`.
- Before enabling a public tunnel, separately review authentication, callback scope, exposed routes, logs, and personal-health-data handling; the mobile page must have a configured Basic Auth password.
- SQLite, credentials, exports, photos, and logs are local sensitive data.
- Mi Fitness cloud access is unofficial and can change without notice.
- The application is not a medical device and does not provide diagnosis or treatment.

## If a secret was exposed

Revoke or rotate the affected Strava/Xiaomi/OpenAI credentials, remove the file from the working tree, and rewrite Git history before publishing. Deleting only the latest copy does not remove a secret from prior commits.
