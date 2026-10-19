import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "mac" / "links-dashboard-mac-info"
REQUIRED_KEYS = {"hosts", "sync", "forward", "branches", "errors", "generated_at"}


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac-only script")
def test_script_outputs_valid_json():
    result = subprocess.run(
        ["/usr/bin/python3", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert REQUIRED_KEYS <= payload.keys()
    assert "/Users/i.senishin/project/carbox/rosfines-dev" in payload["branches"]


def _load_script():
    loader = importlib.machinery.SourceFileLoader("links_dashboard_mac_info", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _fake_tool(tmp_path: Path, name: str, payload: bytes) -> str:
    data = tmp_path / f"{name}.out"
    data.write_bytes(payload)
    tool = tmp_path / name
    tool.write_text(f"#!/bin/sh\ncat '{data}'\n")
    tool.chmod(0o755)
    return str(tool)


@pytest.fixture
def script(tmp_path, monkeypatch):
    module = _load_script()
    hosts = tmp_path / "hosts"
    hosts.write_bytes(b"127.0.0.1 a.test\n")
    monkeypatch.setattr(module, "HOSTS_FILE", str(hosts))
    return module


def test_invalid_bytes_from_tools_do_not_crash(script, tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(script, "MUTAGEN", _fake_tool(tmp_path, "mutagen", b'[{"name": "s\xff"}]'))
    monkeypatch.setattr(script, "GIT", _fake_tool(tmp_path, "git", b"feature/\xfe\n"))
    monkeypatch.setattr(script, "project_dirs", lambda: [str(repo)])
    assert script.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["sync"] == [{"name": "s�"}]
    assert payload["branches"] == {str(repo): "feature/�"}
    assert payload["errors"] == {}


def test_unexpected_error_still_prints_json(script, monkeypatch, capsys):
    def broken():
        raise RuntimeError("kaput")

    monkeypatch.setattr(script, "build_payload", broken)
    assert script.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert REQUIRED_KEYS <= payload.keys()
    assert payload["hosts"] == "127.0.0.1 a.test\n"
    assert "kaput" in payload["errors"]["script"]
    assert payload["errors"]["sync"] == payload["errors"]["forward"] == payload["errors"]["script"]


def test_unreadable_hosts_in_fallback_are_reported(script, monkeypatch, capsys):
    def broken():
        raise RuntimeError("kaput")

    def no_hosts():
        raise ValueError("bad hosts")

    monkeypatch.setattr(script, "build_payload", broken)
    monkeypatch.setattr(script, "read_hosts", no_hosts)
    assert script.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert "hosts" not in payload
    assert "bad hosts" in payload["errors"]["hosts"]
