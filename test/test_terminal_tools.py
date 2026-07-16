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


def test_run_command_truncates_large_output():
    result = terminal_tools._run_command("printf 1234567890", timeout_seconds=2, max_output_chars=5)

    assert "[输出已截断" in result
    assert len(result) < 200
