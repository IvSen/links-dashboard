# Links Dashboard: design

Date: 2026-10-19. Status: draft for owner approval.

## 1. Intent

The owner develops on a Mac, while every container, compose stack and the kind Kubernetes cluster runs on a
second machine, a Windows laptop with WSL2 (SSH alias `winbox`). New tools and projects keep appearing, and each
brings its own addresses: kvs alone answers on dozens of `*.local` domains, rosfines-dev exposes several
`*.local.rf-tech.ru` hosts, tools like Portainer, Beszel and Netdata each have their own URL.

The owner does not want to remember or hunt for these addresses. The dashboard is one page that lists every
address reachable from the Mac, finds new ones by itself, groups them by project, shows whether each one answers,
and keeps the owner's own notes (test users, hints) next to the project they belong to. It also shows, at a
glance, whether the plumbing between Mac and laptop (Mutagen sync, port forwards, edge proxy, SSH, VPN) is healthy.

## 2. Goals

1. One page at a stable Mac address listing all links, grouped into groups and subgroups.
2. New addresses appear automatically; nothing has to be registered by hand.
3. Each item shows whether it answers right now, as seen from the Mac.
4. The owner can assign groups, edit titles and descriptions, and keep free-form notes on the page itself.
5. A health section shows the state of Mutagen sync sessions, port forwards, the edge proxy and the laptop.
6. Modern, functional look; works in a narrow window and on a phone-width screen.

## 3. Non-goals

- Starting, stopping or editing containers, compose stacks or Kubernetes objects (Portainer does that).
- Resource graphs and history (Beszel and Netdata do that).
- Authentication, multiple users, access from other devices on the network.
- Background polling or alerts: checks happen only when the owner looks (see 5.6).

## 4. Anti-goals (would make it a failure even if it works)

- It runs anything permanently on the Mac or uses Mac resources while the page is not open. The owner explicitly
  does not want a resident process on the Mac.
- It changes anything on the Mac, the laptop, in project repositories or in Mutagen sessions. It is strictly
  read-only towards everything it observes; it writes only its own state file.
- It is reachable from the network: on the laptop it listens on `127.0.0.1` only and is exposed to the Mac through
  the edge proxy, the same way as Beszel and Netdata.
- A failing source (Mac unreachable over SSH, VPN down, kind node stopped) breaks the whole page. Each source fails
  on its own and the page says which one.
- It shows passwords it discovered (for example from container environment variables). Only the owner's own
  notes may contain passwords, because the owner typed them there.
- It requires Docker Desktop on the Mac, or starts it.

## 5. What the owner decided

### 5.1 Layout (approved mockup `mockups/final-v4.html` next to this document)

The mockup is an HTML fragment rendered inside a brainstorming frame; take layout, content and states from it, not
its exact styling. The text below wins where they differ (for example the detailed status is collapsed by default).

- Centered page with a max width, responsive. Wide screen: tree of groups on the left, selected project card on
  the right. Narrow screen (below ~700 px): the tree turns into a group dropdown at the top; health tiles go two
  per row; health tables turn into cards.
- Top bar: machine name, "checked N seconds ago", search across addresses, titles and descriptions, and a
  "Refresh" button.
- Health tiles under the top bar (always visible): Sync, Port forwards, edge-proxy, Laptop. A tile turns red when
  anything in it is wrong.
- "Detailed status" section under the tiles, collapsed by default, opened by click (see 5.5).
- Links are real clickable links that open in a new tab.
- Look: modern and functional. Clean typography, generous but compact spacing, light and dark theme following the
  system setting, clear colored status dots and badges, no visual clutter. Readable at a glance, not decorative.

### 5.2 Groups

- Two levels: group and subgroup. Initial groups: `tools`, `cd_traffic`, `carbox`. Initial subgroups follow
  the project folders: `cd_traffic / kvs`, `cd_traffic / mp4k_v2`, `cd_traffic / content-panel`,
  `carbox / rosfines-dev`. (The owner's "etc" meant "and so on", not a group; my reading.)
- Groups and subgroups for other folders under `~/project/<group>/<subgroup>` are created automatically when a
  container from there appears. Paths deeper than that (for example `cd_traffic/worktrees/<name>`) map to the
  nearest sensible subgroup; exact rule left to the builder.
- A special "Without group" section at the top of the tree for items whose group cannot be determined.
- New groups and subgroups can be created on the page.
- If an item's group can be determined automatically (see 5.4), it is placed there directly.

### 5.3 The project card (subgroup)

Header:
- Mac folder of the project and its current git branch (git lives only on the Mac).
- Containers: "3 of 4 running, stopped: kvs-redis" for the compose project behind this subgroup.
- Free-form note, edited in place. Keeps line breaks; URLs in it are clickable. The owner will keep test users and
  passwords there; storing them in plain text locally is accepted.

Two lists:
- "Open in browser": web addresses.
- "Connections": things not meant for a browser but needed to connect (MySQL, PostgreSQL, Redis, RabbitMQ, Mongo,
  MinIO API and similar), shown as `MySQL 127.0.0.1:3310 · user db · database ksv_paysite`, with a "copy" button.
  User name and database name may be taken from container environment; passwords never.

Each item shows:
- status dot: green = answers, red = does not answer, grey = not reachable from the Mac (exists on the laptop but
  there is no forward or domain for it); grey items still show what they are;
- address (clickable for browser items), optional title, description, login hint (for example "login in the note");
- "new" badge (see 5.4);
- source badge: where the item came from (Mac hosts, container, cluster);
- "edit" action.

Ordering inside a subgroup: answering items first, then not answering, then not reachable.

### 5.4 Discovery and the "new" marker

New addresses must appear without any registration. Sources (all read-only):
- Docker on the laptop: containers with published ports; their compose project folder gives group and subgroup
  (`/Users/i.senishin/project/<group>/<subgroup>`); containers from `~/build/*` on the laptop belong to `tools`.
- Kubernetes (kind cluster `kind-rosfines-dev`): ingress hosts.
- The Mac `/etc/hosts`: names pointing to `127.0.0.1`.
- The edge proxy routes (which name goes to which backend), to connect a hostname to the container behind it.
- Mutagen forwards on the Mac, to decide which laptop ports are reachable from the Mac and under which Mac address.

Every item seen for the first time gets a "new" marker, and the tree shows a counter of new items per group, so the
owner notices on the next visit that something appeared. The marker goes away once the owner has seen it.

Items that disappear from all sources should not vanish silently while they carry owner edits (title, description,
group, note); how to show them is left to the builder.

### 5.5 Detailed status (collapsed by default)

- Mutagen sync sessions: name, status in plain words ("watching for changes", "transferring files, 63%"), Mac
  folder, file count and size, conflicts, problems.
- Port forwards: name, status, Mac side, laptop side, open connections, "what for" (editable short text).
- edge-proxy: container status and uptime, listening ports, routing summary.
- Laptop: SSH reachable, VPN connected, Docker version, kind cluster running.

### 5.6 When checks run

No background polling. Discovery and status checks run:
- when the page is opened,
- when the owner switches to another group (status of that group),
- when the owner presses "Refresh" (everything).

"Answers" means: for web items, an HTTP response with status below 500 arrives within a short timeout (redirects,
401 and 404 count as answering; 5xx, connection refused and timeout do not). For connections, a TCP connect
succeeds. Checks are made from the laptop against the real targets; whether an item is reachable from the Mac is
decided from the Mac's Mutagen forwards and hosts (see 6).

### 5.7 Editing on the page

- New items in "Without group" have a "to group..." dropdown that moves them in one click.
- Every item has "edit": title, description, login hint, group and subgroup, and type (browser or connection),
  because automatic classification can be wrong.
- Every item has "hide". Hidden items move to a separate collapsed "Hidden" list from which they can be restored,
  and stay hidden when discovery finds them again. This is for stale or noise entries (old `/etc/hosts` names,
  service ports nobody opens). Stale names from old projects were also removed from the Mac hosts file on
  2026-10-19, so hiding is for what appears later.
- Edits and notes persist across restarts.
- Descriptions for service tools are pre-filled once: Portainer, Beszel, Netdata, MinIO console, edge proxy.
  Other descriptions the owner adds when needed.

## 6. Constraints and environment

- Mac: macOS, no Docker daemon. Docker CLI talks to the laptop through the docker context `winbox`
  (`ssh://winbox`). `kubectl` context `kind-rosfines-dev`. `mutagen` CLI and daemon run on the Mac.
- Laptop reachable as `ssh winbox` (key auth). It may be off, asleep, without VPN, or the kind node may be stopped;
  the dashboard must handle every source failing independently and say which one failed.
- Data that exists only on the Mac (Mutagen sync and forward status, `/etc/hosts`, git branches of project
  folders) is fetched by the laptop over SSH to the Mac, only at the moments listed in 5.6. The owner chose this
  and will enable macOS Remote Login and authorize a dedicated key. That key must be restricted on the Mac to a
  single read-only command (forced command in `authorized_keys`) that prints the needed data; it must not give a
  shell. When the Mac is unreachable over SSH, those parts show "Mac unreachable" and the rest still works.
- The Mac's LAN address may change (DHCP); how the laptop finds the Mac is to be settled in the plan.
- The Mac `/etc/hosts` is read-only for the dashboard.
- No Mac port is needed: the page is reached through the existing Mac 80 -> laptop edge proxy forward. Laptop ports
  already in use: 80/443 (kind ingress), 8080/8443 (kvs nginx), 8090, 3308, 3310, 8095 (Beszel), 9003, 9443,
  10080/10443 (edge proxy), 19000, 19001, 19999. Pick a free laptop port on `127.0.0.1` for the app.
- Context for the environment: `~/.claude/rules/common/local-docker-winbox.md` on the Mac.

## 7. My calls (made for the owner, not asked)

- Runs on the laptop as a container next to Portainer, Beszel and Netdata (owner's decision: nothing resident on
  the Mac). Consequence accepted by the owner: when the laptop is down, the page is down too.
- Address: `http://links.test`, routed by the laptop edge proxy like `beszel.test`, with `links.test` added to the
  Mac hosts.
- Code lives in `~/project/home/links-dashboard` on the Mac, its own git repository; how it gets onto the laptop
  (build through the `winbox` docker context, or a Mutagen sync) is settled in the plan.
- Search across addresses, titles and descriptions was added by me.
- Plain-text local storage of owner notes, including test passwords.
- Names from the Mac hosts that the edge proxy sends to its default route land in kvs nginx, which answers any
  name. Such names are grouped into `cd_traffic / kvs` and the plain "answers" rule from 5.6 applies to them as is.
  Stale names are handled by the hosts cleanup and the "hide" action, not by extra detection logic.

## 8. Left to the builder

- Language, framework and frontend approach, as long as it stays light (no heavy build pipeline is required) and
  matches 5.1.
- Storage format for owner edits and the "seen" markers.
- Exact classification rules for browser items vs connections (known ports and images are a fine start).
- How long checks may take, timeouts, and how to show partial results while slow sources (SSH) are still loading.
- How items that disappeared from all sources are shown.
- How exactly a "new" marker is cleared (on opening the group, on hover, or by an explicit action).
