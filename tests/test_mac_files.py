from pathlib import Path

import pytest

from links_dashboard.mac_files import read_mac_files, with_file_fallback
from links_dashboard.mac_source import MacInfo, MacUnavailable

FIXTURES = Path(__file__).parent / "fixtures"
TOOLS_YML = """
forward:
  beszel:
    source: "tcp:127.0.0.1:18095"
    destination: "winbox:tcp:127.0.0.1:8095"
"""


def _mac_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "mac"
    directory.mkdir()
    (directory / "hosts").write_text("127.0.0.1 localhost\n127.0.0.1 vip4k.com.local beszel.test\n")
    (directory / "cd_traffic.mutagen.yml").write_text((FIXTURES / "cd_traffic.mutagen.yml").read_text())
    (directory / "tools.mutagen.yml").write_text(TOOLS_YML)
    return directory


def test_reads_hosts_and_forwards(tmp_path):
    info = read_mac_files(_mac_dir(tmp_path), "ssh refused")
    assert info.live is False
    assert info.hosts == ["vip4k.com.local", "beszel.test"]
    names = {f.name for f in info.forwards}
    assert {"kvs-mysql", "edge-https", "beszel"} <= names
    assert all(f.configured for f in info.forwards)
    assert info.sync == []
    assert info.branches == {}
    assert info.errors == {"ssh": "ssh refused"}


def test_missing_hosts_fails_like_unreachable_mac(tmp_path):
    directory = _mac_dir(tmp_path)
    (directory / "hosts").unlink()
    with pytest.raises(MacUnavailable) as caught:
        read_mac_files(directory, "ssh refused")
    assert "ssh refused" in caught.value.reason
    assert "hosts" in caught.value.reason


def test_missing_directory_fails(tmp_path):
    with pytest.raises(MacUnavailable):
        read_mac_files(tmp_path / "absent", "ssh refused")


def test_broken_project_file_drops_only_its_forwards(tmp_path):
    directory = _mac_dir(tmp_path)
    (directory / "tools.mutagen.yml").write_text("forward: [oops]")
    info = read_mac_files(directory, "ssh refused")
    names = {f.name for f in info.forwards}
    assert "kvs-mysql" in names
    assert "beszel" not in names
    assert "tools.mutagen.yml" in info.errors["forward"]


def test_non_utf8_hosts_is_read(tmp_path):
    directory = _mac_dir(tmp_path)
    (directory / "hosts").write_bytes(b"# \xff\xfe\n127.0.0.1 a.test\n")
    assert read_mac_files(directory, "x").hosts == ["a.test"]


async def test_fallback_not_used_when_ssh_works(tmp_path):
    live = MacInfo(hosts=["live.test"])

    async def fetch() -> MacInfo:
        return live

    assert await with_file_fallback(fetch, _mac_dir(tmp_path)) is live


async def test_fallback_used_when_ssh_fails(tmp_path):
    async def fetch() -> MacInfo:
        raise MacUnavailable("connection refused")

    info = await with_file_fallback(fetch, _mac_dir(tmp_path))
    assert info.live is False
    assert info.errors["ssh"] == "connection refused"
    assert "vip4k.com.local" in info.hosts


async def test_fallback_without_files_reraises(tmp_path):
    async def fetch() -> MacInfo:
        raise MacUnavailable("connection refused")

    with pytest.raises(MacUnavailable):
        await with_file_fallback(fetch, tmp_path / "absent")
