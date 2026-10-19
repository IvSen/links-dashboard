# Links Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A page at `http://links.test` that lists every address of the laptop (`winbox`) reachable from the Mac, finds new ones by itself, groups them by project, shows whether they answer, keeps the owner's notes, and shows the health of Mutagen, port forwards, the edge proxy and the laptop.

**Architecture:** A Python web app in a container on the laptop (host network, `127.0.0.1:8099`), exposed to the Mac through the existing edge proxy. On demand it reads Docker (socket), the kind cluster (kubeconfig), the edge proxy config (file), and Mac-only data (Mutagen, `/etc/hosts`, git branches) over SSH to a forced read-only command on the Mac. Owner edits live in one JSON file. The frontend is static HTML/CSS/JS served by the app, no build step.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, httpx, docker (SDK), kubernetes (client), pytest + pytest-asyncio, uv. Mac-side script: Python 3.9 (system `/usr/bin/python3`), stdlib only. Frontend: vanilla HTML/CSS/JS.

**Spec:** `docs/superpowers/specs/2026-10-19-links-dashboard-design.md` (mockup: `docs/superpowers/specs/mockups/final-v4.html`)

## Global Constraints

- Strictly read-only towards Mac, laptop, repositories and Mutagen; the only file the app writes is its state file.
- App listens on `127.0.0.1:8099` on the laptop only; reached from the Mac as `http://links.test` via the edge proxy.
- Nothing resident on the Mac; Mac data is fetched over SSH only on page open, group switch and "Refresh".
- The Mac SSH key is restricted by `command="/Users/i.senishin/bin/links-dashboard-mac-info",restrict` in `authorized_keys`; no shell.
- Never show passwords discovered from containers (any env var whose name contains `PASS`, `SECRET`, `TOKEN` or `KEY` is dropped).
- Each source (Mac SSH, Docker, cluster, edge config) fails independently; the page names the failed source and still renders the rest.
- "Answers": web = HTTP status < 500 within 3 s (redirects, 401, 404 count); conn = TCP connect within 3 s. 5xx, refused, timeout = does not answer.
- Ordering in a subgroup: answering, then not answering, then not reachable from the Mac, then missing.
- UI text is Russian; modern, functional look; light and dark theme via `prefers-color-scheme`; responsive below 700 px.
- Before using any library API, query Context7 for its current docs (owner's rule).
- Commits: the owner approves each commit message before `git commit` (owner's rule); no `Co-Authored-By` trailer.
- Mac LAN address `10.0.100.243`, user `i.senishin`; laptop user `ivan` (uid 501, gid 20).

## Review Focus

1. `/etc/hosts` lines with commas and several names (`127.0.0.1 offer.vip4k.com.local, admin.vip4k.com.local`): every name parsed without the comma. Test in Task 2.
2. Mac unreachable (laptop VPN flap, Mac asleep, IP changed): page renders, Sync/Forwards tiles say «Мак недоступен», hosts-derived items come from the last cached hosts list and are marked as cached. Test in Task 5 and Task 7.
3. kind node stopped / kube API refused: cluster items stay listed from the last snapshot as not answering, nothing else breaks. Test in Task 5.
4. Docker publishes the same port twice (`0.0.0.0` and `::`): one item, not two. Test in Task 4.
5. Double click on "Обновить" or opening two tabs: only one discovery runs at a time; the second request waits for the first result. Test in Task 7.

---

### Task 1: Repository skeleton and state store

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/links_dashboard/__init__.py`, `src/links_dashboard/models.py`, `src/links_dashboard/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces (`models.py`, frozen dataclasses):
  - `CheckTarget(mode: Literal["https_sni","http","tcp","none"], host: str, port: int, server_name: str | None)`
  - `Endpoint(key: str, kind: Literal["web","conn"], label: str, url: str | None, source: Literal["hosts","container","cluster"], group: str | None, subgroup: str | None, reachable_from_mac: bool, check: CheckTarget, details: dict[str, str])` — `key` is stable: `web:<url>` or `conn:<proto>:<host>:<port>` or `unreachable:<container>:<port>`.
  - `Override(title: str | None = None, description: str | None = None, login_hint: str | None = None, group: str | None = None, subgroup: str | None = None, kind: str | None = None, hidden: bool = False)`
- Produces (`store.py`): `class StateStore(path: Path)` with `load() -> State`, `save(state: State) -> None` (atomic: write temp file, `os.replace`), and pure helpers on `State`: `set_override(key, **fields) -> State`, `set_note(scope: str, text: str) -> State` (scope `"<group>/<subgroup>"` or `"<group>"`), `add_group(group: str, subgroup: str | None) -> State`, `mark_seen(keys: Iterable[str]) -> State`, `remember(endpoints: list[Endpoint]) -> State`, `set_forward_purpose(name: str, text: str) -> State`.
- `State` fields: `overrides: dict[str, Override]`, `notes: dict[str, str]`, `groups: list[tuple[str, str | None]]`, `seen: set[str]`, `known: dict[str, dict]` (last serialized endpoint per key), `cached_hosts: list[str]`, `forward_purpose: dict[str, str]`. Helpers return new `State` objects (immutability rule).
- Initial groups when the file does not exist: `("tools", None)`, `("cd_traffic","kvs")`, `("cd_traffic","mp4k_v2")`, `("cd_traffic","content-panel")`, `("carbox","rosfines-dev")`.

- [ ] **Step 1:** `git init` in `~/project/home/links-dashboard`, add `.gitignore` (`.venv/`, `__pycache__/`, `.superpowers/`, `*.pyc`), `uv init --package --python 3.12`, add deps `fastapi uvicorn[standard] httpx docker kubernetes`, dev deps `pytest pytest-asyncio`.
- [ ] **Step 2: Write failing tests** in `tests/test_store.py`:
  - `test_missing_file_gives_initial_groups`: `StateStore(tmp/"s.json").load().groups == [("tools", None), ("cd_traffic","kvs"), ("cd_traffic","mp4k_v2"), ("cd_traffic","content-panel"), ("carbox","rosfines-dev")]`
  - `test_roundtrip_keeps_overrides_notes_seen`: set override `title="Админка"`, note `"cd_traffic/kvs" -> "admin / admin\n"`, seen `{"web:https://vip4k.com.local"}`; save, load; all equal.
  - `test_helpers_do_not_mutate`: `s2 = s.set_note("x","y")`; `"x" not in s.notes`.
  - `test_save_is_atomic`: after `save`, no `*.tmp` file left in the directory and the JSON parses.
  - `test_corrupt_file_is_kept_aside`: write `"{broken"`; `load()` returns initial state and the bad file is renamed to `s.json.corrupt-<timestamp>`.
- [ ] **Step 3:** Run `uv run pytest tests/test_store.py -v` → FAIL (module missing).
- [ ] **Step 4:** Implement `models.py` and `store.py` per Interfaces.
- [ ] **Step 5:** Run `uv run pytest tests/test_store.py -v` → PASS.
- [ ] **Step 6:** Commit `feat: state store and models` (message approved by owner).

### Task 2: Parsers for Mac data and edge proxy config

**Files:**
- Create: `src/links_dashboard/parsers.py`
- Test: `tests/test_parsers.py`, fixtures `tests/fixtures/hosts.txt`, `tests/fixtures/mutagen_sync.json`, `tests/fixtures/mutagen_forward.json`, `tests/fixtures/edge-nginx.conf`

**Interfaces:**
- Produces:
  - `parse_hosts(text: str) -> list[str]`: lowercase names mapped to `127.0.0.1`, commas stripped, deduplicated, order kept; excludes `localhost`, `broadcasthost`, `kubernetes.docker.internal`, comments.
  - `SyncSession(name: str, status: str, status_text: str, path: str, files: int | None, size_bytes: int | None, conflicts: int, problems: int, paused: bool, ok: bool)`; `parse_sync(data: list[dict]) -> list[SyncSession]`. `status_text` (Russian): `watching` → «следит за изменениями», `scanning` → «сканирует», `staging-alpha`/`staging-beta`/`transitioning`/`saving` → «передаёт файлы», `connecting-*`/`disconnected` → «нет связи», paused → «на паузе». `files` from `alpha.files`, `size_bytes` from `alpha.totalFileSize`, `problems` = len of alpha+beta `scanProblems` + `transitionProblems`, `ok` = watching and no conflicts and no problems and not paused.
  - `Forward(name: str, ok: bool, status_text: str, source: str, destination: str, dest_port: int | None, src_port: int | None, reverse: bool, open_connections: int)`; `parse_forwards(data: list[dict]) -> list[Forward]`. `reverse` = source URL starts with `winbox:`. `dest_port`/`src_port` parsed from `tcp:<host>:<port>`.
  - `EdgeRoutes(http_listen: int, tls_listen: int, http: list[tuple[str, bool, int]], tls: list[tuple[str, bool, int]], http_default: int, tls_default: int)` with methods `route_http(host: str) -> int` and `route_tls(host: str) -> int`; `parse_edge_conf(text: str) -> EdgeRoutes` (reads the `map $host $http_upstream` and `map $ssl_preread_server_name $tls_upstream` blocks and the two `listen` lines; tuple is `(pattern, is_regex, port)`).
- [ ] **Step 1:** Capture fixtures from the real system: copy `/etc/hosts`, `mutagen sync list --template '{{json .}}'`, `mutagen forward list --template '{{json .}}'`, and `ssh winbox cat ~/build/edge-proxy/nginx.conf`. Keep them as they are (no secrets in them).
- [ ] **Step 2: Write failing tests:**
  - `test_hosts_strips_commas`: `"127.0.0.1 offer.vip4k.com.local, admin.vip4k.com.local"` → `["offer.vip4k.com.local","admin.vip4k.com.local"]`.
  - `test_hosts_skips_foreign_ip_and_system_names`: `"213.174.151.224 admin.vip4k.com"`, `localhost`, `kubernetes.docker.internal` are absent; `beszel.test` and `netdata.test` present from the fixture.
  - `test_sync_fixture`: 4 sessions, `kvs` has `status_text == "следит за изменениями"`, `files == 22077`-ish (assert `> 0`), `ok is True`.
  - `test_forward_reverse_detected`: forward `xdebug` has `reverse is True`, `src_port == 9003`; `edge-https` has `src_port == 443`, `dest_port == 10443`.
  - `test_edge_routes`: `route_http("beszel.test") == 8095`, `route_http("babylon.local.rf-tech.ru") == 80`, `route_http("vip4k.com.local") == 8080`, `route_tls("vip4k.com.local") == 8443`, `route_tls("babylon.local.rf-tech.ru") == 443`, `http_listen == 10080`, `tls_listen == 10443`.
- [ ] **Step 3:** `uv run pytest tests/test_parsers.py -v` → FAIL.
- [ ] **Step 4:** Implement `parsers.py` per Interfaces.
- [ ] **Step 5:** `uv run pytest tests/test_parsers.py -v` → PASS.
- [ ] **Step 6:** Commit `feat: parsers for hosts, mutagen and edge config`.

### Task 3: Mac-side info command and SSH client

**Files:**
- Create: `mac/links-dashboard-mac-info` (Python 3.9, stdlib only, executable), `src/links_dashboard/mac_source.py`
- Test: `tests/test_mac_info_script.py`, `tests/test_mac_source.py`

**Interfaces:**
- Mac script prints one JSON object to stdout and exits 0: `{"generated_at": iso8601, "hosts": "<raw /etc/hosts>", "sync": <mutagen sync json or null>, "forward": <mutagen forward json or null>, "branches": {"/Users/i.senishin/project/<g>/<sg>": "<branch>"}, "errors": {"sync": str?, "forward": str?}}`. Mutagen is called as `/opt/homebrew/bin/mutagen` with env `MUTAGEN_DISABLE_AUTOSTART=1` (never starts a daemon). Branches: for each `~/project/*/*` that has `.git`, `git -C <dir> branch --show-current` (empty string for detached HEAD). It ignores `SSH_ORIGINAL_COMMAND`.
- Produces (`mac_source.py`): `MacInfo(hosts: list[str], sync: list[SyncSession], forwards: list[Forward], branches: dict[str, str], errors: dict[str, str])`; `async fetch_mac_info(host: str, user: str, key_path: Path, timeout: float = 8.0) -> MacInfo` running `ssh -i key -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=<data>/known_hosts user@host` and parsing with Task 2 parsers; raises `MacUnavailable(reason: str)` on any SSH failure or invalid JSON.
- [ ] **Step 1: Write failing tests:**
  - `test_script_outputs_valid_json` (runs only on macOS, `pytest.mark.skipif(sys.platform != "darwin")`): run `/usr/bin/python3 mac/links-dashboard-mac-info`; JSON has keys `hosts, sync, forward, branches, errors`; `branches` contains `/Users/i.senishin/project/carbox/rosfines-dev`.
  - `test_fetch_parses_payload`: monkeypatch the subprocess runner to return the fixtures from Task 2 wrapped in the payload; `MacInfo.hosts` contains `vip4k.com.local`, `len(sync) == 4`.
  - `test_fetch_raises_on_ssh_failure`: runner returns exit code 255 → `MacUnavailable`.
- [ ] **Step 2:** `uv run pytest tests/test_mac_info_script.py tests/test_mac_source.py -v` → FAIL.
- [ ] **Step 3:** Implement the script and `mac_source.py` (subprocess via `asyncio.create_subprocess_exec`, injectable runner for tests).
- [ ] **Step 4:** Run the same tests → PASS.
- [ ] **Step 5:** Commit `feat: mac info command and ssh source`.

### Task 4: Docker, cluster and laptop sources

**Files:**
- Create: `src/links_dashboard/docker_source.py`, `src/links_dashboard/cluster_source.py`, `src/links_dashboard/laptop_source.py`, `src/links_dashboard/config.py`
- Test: `tests/test_docker_source.py`, `tests/test_cluster_source.py`, fixture `tests/fixtures/containers.json` (captured `docker inspect` of current containers)

**Interfaces:**
- `ContainerInfo(name: str, running: bool, image: str, started_at: str | None, project_dir: str | None, service: str | None, env: dict[str, str], ports: list[tuple[str, int, int, str]])` (host_ip, host_port, container_port, proto); `env` already without secret-looking names (Global Constraints).
- `list_containers(client) -> list[ContainerInfo]`; `from_inspect(attrs: dict) -> ContainerInfo` (pure, testable). Ports deduplicated on `(host_port, container_port, proto)`.
- `project_of(path: str | None) -> tuple[str, str | None] | None`: `/Users/i.senishin/project/<g>/<sg>[/...]` → `(g, sg)`; `/home/ivan/build/<x>[/...]` → `("tools", None)`; else `None`.
- `IngressInfo(namespace: str, name: str, hosts: list[str])`; `list_ingresses(kubeconfig: Path) -> list[IngressInfo]`; raises `ClusterUnavailable(reason)`.
- `LaptopInfo(vpn: bool, docker_version: str | None, kind_running: bool)`; `read_laptop(client, route_file: Path = Path("/proc/net/route")) -> LaptopInfo`; VPN = a route to `10.0.0.0/19` exists.
- `config.py`: `Settings` from env: `LD_STATE` (`/data/state.json`), `LD_EDGE_CONF` (`/config/edge-nginx.conf`), `LD_KUBECONFIG` (`/data/kubeconfig`), `LD_MAC_HOST` (`10.0.100.243`), `LD_MAC_USER` (`i.senishin`), `LD_MAC_KEY` (`/data/mac_key`), `LD_PORT` (`8099`). Constants: `NAMESPACE_GROUPS = {"rosfines-dev": ("carbox","rosfines-dev")}`, `TOOL_CONTAINERS = {"portainer": ("tools", None)}`, `KIND_NODE = "rosfines-dev-control-plane"`, `EDGE_CONTAINER = "edge-proxy"`, `CONN_PORTS = {3306:"MySQL", 5432:"PostgreSQL", 6379:"Redis", 5672:"RabbitMQ", 27017:"MongoDB", 9000:"MinIO API", 8123:"ClickHouse"}`, `DEFAULT_DESCRIPTIONS = {"web:https://portainer.test:9443": "Контейнеры и кластер в вебе", "web:http://beszel.test": "Нагрузка ноутбука и история", "web:http://netdata.test": "Подробные метрики по секундам", ...}` (MinIO console key added after discovery shows its exact key).
- [ ] **Step 1: Write failing tests:**
  - `test_secret_env_dropped`: `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`, `TOKEN` absent; `MYSQL_USER == "db"` kept (from the kvs-mysql fixture).
  - `test_ipv4_ipv6_ports_deduplicated`: inspect with `"3306/tcp": [{"HostIp":"0.0.0.0","HostPort":"3308"},{"HostIp":"::","HostPort":"3308"}]` → one port.
  - `test_project_of`: `/Users/i.senishin/project/cd_traffic/kvs` → `("cd_traffic","kvs")`; `/Users/i.senishin/project/cd_traffic/worktrees/mp4k_v2-set-thumbs` → `("cd_traffic","worktrees")`; `/home/ivan/build/monitoring` → `("tools", None)`; `/tmp/x` → `None`.
  - `test_vpn_route_detected`: a `/proc/net/route` sample with destination `0000000A` and mask `00E0FFFF` → `vpn is True`; without it → `False`.
  - `test_cluster_unavailable`: kubeconfig pointing to a closed port → `ClusterUnavailable`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: docker, cluster and laptop sources`.

### Task 5: Discovery, grouping and reachability

**Files:**
- Create: `src/links_dashboard/discovery.py`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 4.
- Produces: `build_endpoints(hosts: list[str], containers: list[ContainerInfo], ingresses: list[IngressInfo], edge: EdgeRoutes, forwards: list[Forward]) -> list[Endpoint]` and `ProjectInfo(group: str, subgroup: str, folder: str, branch: str | None, running: int, total: int, stopped: list[str])`; `build_projects(containers: list[ContainerInfo], branches: dict[str, str]) -> list[ProjectInfo]`.
- Rules:
  - Hosts name `n`: scheme `http` if `n` has an explicit (non-regex) entry in `edge.http` and no explicit entry in `edge.tls`, else `https`. Group = project of the container that publishes `edge.route_http(n)` (for http) or `edge.route_tls(n)` (for https) on `127.0.0.1`; check `https_sni` to `127.0.0.1:edge.tls_listen` with `server_name=n`, or `http` to `127.0.0.1:edge.http_listen` with `server_name=n` (sent as Host). `source="hosts"`, `reachable_from_mac=True`.
  - Ingress host `h`: `https://h`, group from `NAMESPACE_GROUPS`, check `https_sni` via `edge.tls_listen`, `source="cluster"`, reachable.
  - Container port: skip containers `KIND_NODE` and `EDGE_CONTAINER`, and host ports that are edge backends (any port in `edge.http`/`edge.tls` targets or defaults). Find a non-reverse forward with `dest_port == host_port`: reachable, Mac address `127.0.0.1:<src_port>` (use `localhost` in URLs). `container_port in CONN_PORTS` or image contains `mysql|postgres|redis|rabbitmq|mongo|clickhouse` → `kind="conn"`, label `"<Proto> 127.0.0.1:<src_port> · user <u> · db <d>"` (user/db from env when present), check `tcp` to `127.0.0.1:<host_port>`; else `kind="web"`, url `http://localhost:<src_port>`, check `http`. No forward → `kind` as above, `reachable_from_mac=False`, label `"<container> :<container_port>"`, check `none`. Group from `project_of(project_dir)` or `TOOL_CONTAINERS[name]`.
  - Keys deduplicated; the first rule wins.
- [ ] **Step 1: Write failing tests** (inputs built from Task 2/4 fixtures):
  - `test_vip4k_goes_to_kvs`: endpoint `web:https://vip4k.com.local` has `group == "cd_traffic"`, `subgroup == "kvs"`, `check.port == 10443`, `check.server_name == "vip4k.com.local"`.
  - `test_beszel_is_http_tools`: `web:http://beszel.test` exists, `group == "tools"`.
  - `test_ingress_goes_to_rosfines`: `web:https://babylon.local.rf-tech.ru` → `("carbox","rosfines-dev")`.
  - `test_kvs_mysql_is_connection`: key `conn:mysql:127.0.0.1:3310`, `kind == "conn"`, label contains `user db`, no `PASSWORD` anywhere in `details` or `label`.
  - `test_unforwarded_port_is_grey`: a container port with no forward → `reachable_from_mac is False`, `check.mode == "none"`.
  - `test_edge_backends_not_listed`: no endpoint with key containing `:8080` or `:8095`.
  - `test_projects_running_counts`: kvs `ProjectInfo.total == 4`, a stopped redis in the fixture gives `stopped == ["kvs-redis"]`, `branch` from the branches map.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: discovery and grouping`.

### Task 6: Status checks and health

**Files:**
- Create: `src/links_dashboard/checks.py`, `src/links_dashboard/health.py`
- Test: `tests/test_checks.py`, `tests/test_health.py`

**Interfaces:**
- `async check(target: CheckTarget, timeout: float = 3.0) -> Literal["up","down","na"]` (`na` for mode `none`); `https_sni` connects to `target.host:target.port` with `verify=False`, `Host` header and `extensions={"sni_hostname": target.server_name}`; `http` sends `Host` when `server_name` is set; `tcp` = open and close a connection. `async check_many(targets: dict[str, CheckTarget], limit: int = 20) -> dict[str, str]` (bounded concurrency).
- `Tile(id: str, title: str, value: str, sub: str, bad: bool)`; `Health(tiles: list[Tile], sync: list[SyncSession], forwards: list[Forward], edge: dict, laptop: LaptopInfo | None, errors: dict[str, str])`; `build_health(mac: MacInfo | None, mac_error: str | None, edge_container: ContainerInfo | None, edge: EdgeRoutes | None, laptop: LaptopInfo | None, forward_purpose: dict[str, str]) -> Health`. Tiles in order `sync`, `forwards`, `edge`, `laptop`; titles «Синхронизация», «Пробросы», «edge-proxy», «Ноутбук»; when `mac is None` the first two tiles have `value="Мак недоступен"`, `bad=True`, `sub=mac_error`.
- [ ] **Step 1: Write failing tests:**
  - `test_http_404_is_up`, `test_http_502_is_down`, `test_refused_is_down`, `test_timeout_is_down` (local aiohttp/asyncio servers on random ports; timeout case: server that never answers, `timeout=0.5`).
  - `test_tcp_up_and_down`.
  - `test_sni_sent`: a local TLS server (self-signed cert generated in the test) records the SNI; `check(CheckTarget("https_sni","127.0.0.1",port,"vip4k.com.local"))` → `"up"` and recorded SNI == `"vip4k.com.local"`.
  - `test_mac_down_tiles`: `build_health(None, "timeout", ...)` → tiles 0 and 1 `value == "Мак недоступен"`, `bad is True`; tile 2 and 3 still computed.
  - `test_forward_down_marks_tile`: one forward `ok=False` → forwards tile `bad is True`, `sub` names it.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: checks and health`.

### Task 7: API with snapshot, editing and "new" markers

**Files:**
- Create: `src/links_dashboard/service.py`, `src/links_dashboard/app.py`
- Test: `tests/test_api.py`

**Interfaces:**
- `class DashboardService(settings: Settings, sources: Sources, store: StateStore)` where `Sources` bundles injectable callables (`mac`, `containers`, `ingresses`, `edge`, `laptop`) so tests use fakes.
  - `async refresh() -> Snapshot`: one in-flight discovery at a time (`asyncio.Lock` + shared task: concurrent callers await the same result). Uses cached hosts from the state when Mac is unavailable; stores `cached_hosts`, `remember(endpoints)`.
  - `snapshot() -> Snapshot | None` (last result). `Snapshot(tree: list[TreeNode], health: Health, checked_at: str, failed_sources: dict[str,str])`; `TreeNode(group, subgroup, count, new_count)`, "Без группы" node uses `group=""`.
  - `async group_view(group: str, subgroup: str | None) -> GroupView`: runs `check_many` for that group's visible items now; `GroupView(project: ProjectInfo | None, note: str, items: list[ItemView], hidden: list[ItemView])`. `ItemView` = endpoint fields with overrides applied + `status` (`up|down|na|missing`) + `is_new` (key not in `seen`) + `cached` (came from cached hosts). Items sorted per Global Constraints. Missing = keys in `known` with an override but absent now.
  - `update_item(key, patch: dict)`, `set_note(scope, text)`, `add_group(group, subgroup)`, `mark_seen(keys)`, `set_forward_purpose(name, text)`.
- Routes (`app.py`, FastAPI, static files from `src/links_dashboard/static`): `GET /` → `index.html`; `POST /api/refresh` → Snapshot; `GET /api/snapshot`; `GET /api/group?g=&sg=`; `PATCH /api/items/{key:path}`; `PUT /api/notes` `{scope,text}`; `POST /api/groups` `{group,subgroup}`; `POST /api/seen` `{keys}`; `PUT /api/forward-purpose` `{name,text}`. Requests whose `Host` is not `links.test`, `127.0.0.1:8099` or `localhost:8099` get 403.
- [ ] **Step 1: Write failing tests** (FastAPI `TestClient`, fake sources from fixtures):
  - `test_refresh_returns_tree_and_health`: tree contains `("cd_traffic","kvs")` with `count > 0`; 4 tiles.
  - `test_concurrent_refresh_runs_once`: fake `containers` source counts calls; two concurrent `POST /api/refresh` → counter == 1.
  - `test_mac_down_uses_cached_hosts`: first refresh with Mac up, second with Mac raising `MacUnavailable` → `vip4k.com.local` still in kvs items with `cached is True`; `failed_sources["mac"]` set.
  - `test_cluster_down_keeps_items`: cluster fake raises → rosfines items present with `status == "down"`.
  - `test_new_until_seen`: first view `is_new is True`; after `POST /api/seen` → `False`.
  - `test_patch_moves_group_and_hides`: PATCH `{group:"tools", subgroup:null}` moves the item; PATCH `{hidden:true}` moves it to `hidden`.
  - `test_missing_item_with_override_is_kept`: override an item, remove it from sources, refresh → it appears with `status == "missing"`.
  - `test_foreign_host_rejected`: `Host: evil.example` → 403.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: api and service`.

### Task 8: Frontend

**Files:**
- Create: `src/links_dashboard/static/index.html`, `static/app.js`, `static/styles.css`
- Test: `tests/test_static.py` (served and contains the main regions)

**Interfaces:**
- Consumes the Task 7 routes only. Layout, states and Russian copy from `docs/superpowers/specs/mockups/final-v4.html` and spec 5.1-5.7.
- Behaviour that is not obvious from the mockup:
  - On load: `POST /api/refresh`, render tree and tiles, then `GET /api/group` for the last selected group (remembered in `localStorage`, try/catch around storage) or the first non-empty group.
  - On group switch: `GET /api/group`, then `POST /api/seen` with the keys of the rendered items; "новое" badges stay visible until the next switch.
  - "Обновить": `POST /api/refresh` then `GET /api/group`; button disabled while running; "проверено N сек назад" ticks locally.
  - "Подробное состояние" is a `<details>` closed by default; tables become cards below 700 px; the tree becomes a `<select>` below 700 px.
  - "в группу..." select on items without group calls `PATCH`; "изменить" opens an inline form (название, описание, подсказка для входа, группа/подгруппа, тип); "скрыть" and the collapsed «Скрытые» list with «вернуть».
  - «+ группа / подгруппа» at the bottom of the tree calls `POST /api/groups`; new groups appear in the tree and in every group select.
  - In the forwards table the «Для чего» cell is editable inline and saved with `PUT /api/forward-purpose`.
  - Note editor: inline `<textarea>`, saved by «Сохранить»; rendered with line breaks kept and URLs turned into links (text escaped first, no HTML injection).
  - Search filters across all groups by address, title and description; shows matching items grouped.
  - Failed sources show a thin banner: «Не удалось получить данные: Мак (timeout)».
  - Links `target="_blank" rel="noopener"`; «копировать» uses `navigator.clipboard`.
  - Use the `impeccable` skill for the visual pass: modern, functional, light/dark via `prefers-color-scheme`, centered `max-width` ~1100 px, no horizontal scroll at 360 px.
- [ ] **Step 1: Write failing test** `test_index_served`: `GET /` (Host `links.test`) → 200, body contains `id="tree"`, `id="health"`, `id="project"`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement the three static files. **Step 4:** Run → PASS.
- [ ] **Step 5:** Local visual check: run the app on the Mac against fixture fakes (`LD_FAKE=1` switch in `app.py` that wires fixture sources) and look at 1280 px and 360 px widths in the browser pane; no horizontal scroll, tiles, tree, card, edit form, hidden list and note editor work.
- [ ] **Step 6:** Commit `feat: frontend`.

### Task 9: Deploy on the laptop and wire Mac access

**Files:**
- Create: `deploy/Dockerfile`, `deploy/compose.yml`, `deploy/README.md` (short runbook: how to update, how to reinstall the Mac command, how to refresh the kubeconfig after the cluster is recreated)

**Interfaces:** Consumes everything above. Owner actions are marked **(owner)**.

- [ ] **Step 1:** `deploy/Dockerfile`: `python:3.12-slim`, install `openssh-client`, `uv`, the package; `CMD ["uvicorn","links_dashboard.app:app","--host","127.0.0.1","--port","8099"]`.
- [ ] **Step 2:** `deploy/compose.yml`: service `links-dashboard`, `network_mode: host`, `restart: unless-stopped`, volumes `/var/run/docker.sock:/var/run/docker.sock:ro`, `/home/ivan/build/edge-proxy/nginx.conf:/config/edge-nginx.conf:ro`, `/home/ivan/.config/links-dashboard:/data`; env per `Settings`.
- [ ] **Step 3:** On the laptop: `mkdir -p /home/ivan/.config/links-dashboard`; generate `ssh-keygen -t ed25519 -N "" -C links-dashboard@winbox -f /home/ivan/.config/links-dashboard/mac_key`; write the kind kubeconfig: on the Mac `kubectl config view --minify --flatten --context kind-rosfines-dev`, copy to `/home/ivan/.config/links-dashboard/kubeconfig`.
- [ ] **Step 4 (owner):** enable macOS Remote Login (System Settings → General → Sharing → Remote Login, only user `i.senishin`); reserve `10.0.100.243` for the Mac in the router.
- [ ] **Step 5:** With the owner's go-ahead: install `mac/links-dashboard-mac-info` to `/Users/i.senishin/bin/links-dashboard-mac-info` (chmod 755) and append to `~/.ssh/authorized_keys`: `command="/Users/i.senishin/bin/links-dashboard-mac-info",restrict <mac_key.pub>`.
- [ ] **Step 6:** Verify from the laptop: `ssh -i ~/.config/links-dashboard/mac_key i.senishin@10.0.100.243 | python3 -c 'import json,sys; d=json.load(sys.stdin); print(sorted(d))'` → `['branches', 'errors', 'forward', 'generated_at', 'hosts', 'sync']`; and `ssh -i ... i.senishin@10.0.100.243 whoami` still prints the JSON (forced command ignores the requested command).
- [ ] **Step 7:** From the Mac: `docker compose -f deploy/compose.yml up -d --build` (context `winbox`); `curl -s -H 'Host: links.test' http://127.0.0.1:8099/api/snapshot` via `ssh winbox` → JSON with 4 tiles.
- [ ] **Step 8:** Add `links.test 127.0.0.1:8099;` to the `map $host $http_upstream` block in `~/build/edge-proxy/nginx.conf` on the laptop, `docker exec edge-proxy nginx -t && docker exec edge-proxy nginx -s reload`.
- [ ] **Step 9 (owner):** add `links.test` to the Mac `/etc/hosts` line with `beszel.test netdata.test` (needs `sudo`).
- [ ] **Step 10:** End-to-end in the owner's Chrome at `http://links.test`: kvs, mp4k_v2, rosfines-dev and tools groups filled; tiles show 4 sync sessions and the forwards; stop `kvs-redis` → kvs header says «3 из 4»; start it again.
- [ ] **Step 11:** Update `~/.claude/rules/common/local-docker-winbox.md` Tools section with `http://links.test`, the code path and `deploy/README.md`.
- [ ] **Step 12:** Commit `feat: deploy on winbox`.
