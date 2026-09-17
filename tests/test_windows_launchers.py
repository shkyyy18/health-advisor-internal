"""Execute launchers only in isolated stub projects, never against live services."""

import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parents[1]
pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows launcher integration"
)


@pytest.mark.parametrize(
    ("launcher", "task", "target"),
    [
        ("run-daily-sync-hidden.vbs", "HealthAssistantDailySync", "daily_sync.py"),
        (
            "start-health-services-hidden.vbs",
            "HealthAssistant",
            "start_health_services.py",
        ),
    ],
)
@pytest.mark.parametrize("exit_code", [0, 7])
def test_hidden_launchers_use_venv_capture_logs_and_propagate_exit(
    tmp_path, launcher, task, target, exit_code
):
    project = tmp_path / "synthetic project with spaces"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    venv.EnvBuilder(with_pip=False).create(project / ".venv")
    shutil.copyfile(ROOT / "scripts" / launcher, scripts / launcher)
    (scripts / target).write_text(
        "import sys\nprint('synthetic stdout', flush=True)\n"
        "print('synthetic stderr', file=sys.stderr, flush=True)\n"
        "assert sys.prefix != sys.base_prefix, 'launcher ignored local venv'\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["cscript.exe", "//Nologo", str(scripts / launcher)],
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    log = (project / "logs" / f"{task}.last.log").read_text(encoding="utf-8")
    assert "synthetic stdout" in log and "synthetic stderr" in log
    report = json.loads(
        (project / "logs" / "task-results" / f"{task}.json").read_text(encoding="utf-8")
    )
    assert report["exit_code"] == exit_code
    assert report["console_bytes"] > 0


def test_powershell_entrypoints_parse_without_execution():
    for script in [ROOT / "run.ps1", ROOT / "scripts" / "install_sync_task.ps1"]:
        env = os.environ.copy()
        env["SYNTHETIC_PARSE_TARGET"] = str(script)
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$tokens=$null; $errors=$null; "
                "[System.Management.Automation.Language.Parser]::ParseFile("
                "$env:SYNTHETIC_PARSE_TARGET,[ref]$tokens,[ref]$errors) | Out-Null; "
                "if ($errors.Count) { $errors | Out-String | Write-Output; exit 1 }",
            ],
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("exit_code", [0, 7])
def test_dashboard_batch_uses_venv_and_preserves_backend_exit(tmp_path, exit_code):
    project = tmp_path / "synthetic dashboard with spaces"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    venv.EnvBuilder(with_pip=False).create(project / ".venv")
    shutil.copyfile(ROOT / "scripts" / "healthboard.bat", scripts / "healthboard.bat")
    (scripts / "open_dashboard.py").write_text(
        "# No browser or network in tests.\n", encoding="utf-8"
    )
    # The port probe must not connect to a real service or affect its state.
    (project / "socket.py").write_text(
        "class socket:\n    def connect_ex(self, address): return 1\n", encoding="utf-8"
    )
    (project / "uvicorn.py").write_text(
        "import sys\nassert sys.prefix != sys.base_prefix\n"
        "print('synthetic backend', flush=True)\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(scripts / "healthboard.bat")],
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert "synthetic backend" in (project / "logs" / "app.out.log").read_text(
        encoding="utf-8"
    )
