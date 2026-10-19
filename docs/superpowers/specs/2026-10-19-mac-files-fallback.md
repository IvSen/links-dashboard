# Mac data from synced files: design addendum

Date: 2026-10-19. Status: approved by the owner in chat. Extends `2026-10-19-links-dashboard-design.md`, section 6.

## Why

The main design reads Mac-only data (hosts, Mutagen status, git branches) over SSH to the Mac. The owner does not
want macOS Remote Login on for now: an SSH server on a laptop that travels is exposed on every public Wi-Fi. Without
it the dashboard lost every hosts domain (kvs sites, `beszel.test`, `netdata.test`, `links.test`) and could not say
under which Mac address a container port is reachable.

## What

- Mutagen on the Mac pushes, one way, a copy of `/etc/hosts` and of every Mutagen project file that defines forwards
  into `/home/ivan/.config/links-dashboard/mac/` on the laptop. The existing outgoing Mac -> laptop SSH is used;
  nothing listens on the Mac, nothing on the Mac is written.
- The standalone tool forwards (portainer, netdata, beszel) move into a Mutagen project file
  `mac/mutagen.yml` in this repository, together with the file sync sessions above, so every forward the
  dashboard needs is described in a file it can read. `kind-api` stays standalone (its port changes with the
  cluster and it is not a link).
- When SSH to the Mac fails, the dashboard builds the Mac data from these files: hosts from `hosts`, forwards from
  the `forward:` sections of `*.mutagen.yml`. SSH stays the first choice, so enabling Remote Login later brings live
  status back without changes.

## Behaviour in file mode

- Links: the same as with SSH (domains from hosts, containers mapped to Mac addresses through forwards).
- "Sync" tile: neutral, "нет живого статуса", explains that the data comes from files.
- "Port forwards" tile: neutral, number of forwards from the config; each forward shows status "из конфига".
- Git branch: not shown (`.git` is not synced).
- Files missing or unreadable `hosts`: the Mac source fails as before ("Мак недоступен"). A broken `*.mutagen.yml`
  only drops its forwards and is reported in the details and the log. A project file that never arrived cannot be
  told apart from one that does not exist, so its forwards are simply absent.
- The SSH failure reason is shown as a neutral note under the detailed status, not as an error.

## My calls

- Forward project file lives in this repository (`mac/mutagen.yml`), next to the Mac info script. Cost if wrong:
  moving one file and restarting the project.
- File mode tiles are not red: it is the mode the owner chose, not a failure.
- Mutagen `defaults` entries in a `forward:` section are skipped; only named sessions count.
- The fallback to files is logged at INFO: with Remote Login off it happens on every refresh by design.
