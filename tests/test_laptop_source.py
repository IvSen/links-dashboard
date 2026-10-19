from pathlib import Path

from links_dashboard.laptop_source import LaptopInfo, read_laptop

HEADER = "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
DEFAULT = "eth0\t00000000\t0100A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
VPN = "tun0\t0000000A\t00000000\t0001\t0\t0\t0\t00E0FFFF\t0\t0\t0\n"
OTHER_10 = "tun1\t0000000A\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"


class FakeContainers:
    def __init__(self, names):
        self.names = names

    def list(self, **kwargs):
        return [type("C", (), {"name": name, "status": "running"})() for name in self.names]


class FakeClient:
    def __init__(self, names=(), version="27.3.1", fail=False):
        self.containers = FakeContainers(names)
        self._version = version
        self._fail = fail

    def version(self):
        if self._fail:
            raise RuntimeError("down")
        return {"Version": self._version}


def route_file(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "route"
    path.write_text(HEADER + "".join(lines))
    return path


def test_vpn_route_detected(tmp_path):
    info = read_laptop(FakeClient(), route_file(tmp_path, DEFAULT, VPN))
    assert info.vpn is True


def test_vpn_route_absent(tmp_path):
    assert read_laptop(FakeClient(), route_file(tmp_path, DEFAULT)).vpn is False


def test_other_ten_net_route_is_not_vpn(tmp_path):
    assert read_laptop(FakeClient(), route_file(tmp_path, DEFAULT, OTHER_10)).vpn is False


def test_missing_route_file_means_no_vpn(tmp_path):
    assert read_laptop(FakeClient(), tmp_path / "absent").vpn is False


def test_docker_version_and_kind(tmp_path):
    path = route_file(tmp_path, DEFAULT)
    info = read_laptop(FakeClient(["rosfines-dev-control-plane"], "27.3.1"), path)
    assert info == LaptopInfo(vpn=False, docker_version="27.3.1", kind_running=True)


def test_kind_not_running(tmp_path):
    info = read_laptop(FakeClient(["other"]), route_file(tmp_path, DEFAULT))
    assert info.kind_running is False


def test_docker_failure_gives_none(tmp_path):
    info = read_laptop(FakeClient(fail=True), route_file(tmp_path, VPN))
    assert info == LaptopInfo(vpn=True, docker_version=None, kind_running=False)
