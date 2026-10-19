from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class CheckTarget:
    mode: Literal["https_sni", "http", "tcp", "none"]
    host: str
    port: int
    server_name: str | None


@dataclass(frozen=True)
class Endpoint:
    key: str
    kind: Literal["web", "conn"]
    label: str
    url: str | None
    source: Literal["hosts", "container", "cluster"]
    group: str | None
    subgroup: str | None
    reachable_from_mac: bool
    check: CheckTarget
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Override:
    title: str | None = None
    description: str | None = None
    login_hint: str | None = None
    group: str | None = None
    subgroup: str | None = None
    kind: str | None = None
    hidden: bool = False
