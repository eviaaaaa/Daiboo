import os
import time
from pathlib import Path

import pytest

from tools import terminal_tools


def test_select_shell_prefers_pwsh_on_windows(monkeypatch):
    monkeypatch.setattr(terminal_tools.shutil, "which", lambda name: "C:/pwsh.exe" if name == "pwsh" else None)

    assert terminal_tools._select_shell("win32") == ["C:/pwsh.exe", "-Command"]


def test_select_shell_uses_bash_on_linux(monkeypatch):
    monkeypatch.setattr(terminal_tools.shutil, "which", lambda name: "/bin/bash" if name == "bash" else None)

    assert terminal_tools._select_shell("linux") == ["/bin/bash", "-lc"]


def test_run_command_reports_exit_code():
    result = terminal_tools._run_command("printf hello; exit 7", timeout_seconds=2, max_output_chars=1000)

    assert "hello" in result
    assert "[Exit code: 7]" in result


def test_run_command_times_out():
    result = terminal_tools._run_command("sleep 2", timeout_seconds=0.01, max_output_chars=1000)

    assert "执行超时" in result


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_run_command_timeout_stops_descendants(tmp_path: Path):
    pid_file = tmp_path / "child.pid"
    result = terminal_tools._run_command(
        f"sleep 30 & echo $! > {pid_file}; wait",
        # Leave room for login-shell startup on shared CI runners.
        timeout_seconds=2,
        max_output_chars=1000,
    )
    child_pid = int(pid_file.read_text())

    def child_is_running() -> bool:
        try:
            state = Path(f"/proc/{child_pid}/stat").read_text().split()[2]
        except FileNotFoundError:
            return False
        return state not in {"Z", "X"}

    deadline = time.monotonic() + 1
    while child_is_running() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert "执行超时" in result
    assert not child_is_running()


def test_run_command_truncates_large_output():
    result = terminal_tools._run_command("printf 1234567890", timeout_seconds=2, max_output_chars=5)

    assert "[输出已截断" in result
    assert len(result) < 200
