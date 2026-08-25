# ARK Control Panel

A lightweight, self-hosted web panel to install, configure and control an
**ARK: Survival Evolved dedicated server** inside a Proxmox LXC container —
with a login-protected UI, live status, one-click update, a config editor,
**map and mod management** and RCON (player list, save, clean shutdown,
broadcasts).

The interface is available in **English and German** (switchable at the top).

> Unofficial community project. Not affiliated with Studio Wildcard / Snail
> Games. "ARK: Survival Evolved" is a trademark of its respective owner.

## Features

- Server control: **start / restart / stop** and **update** (SteamCMD, app 376030)
- **Reboot-aware**: the server only comes back after a reboot if it was running
  before (start = autostart on, stop = off); the LXC itself starts via Proxmox
  `onboot`
- **Map management**: pick official maps with one click, add custom/mod maps
  (map code + optional mod ID). Paid expansion maps are flagged with a `DLC` badge.
- **Mod management**: enter Steam Workshop IDs in load order, reorder and remove
  them, then **download and install them with one click** — the panel handles the
  Linux mod-extraction that the ARK server itself does not (see [Mods](#mods)).
- **Launch parameters** (session name, max players, ports, BattlEye, extra args)
- **Config editor** for both `GameUserSettings.ini` **and** `Game.ini` — grouped
  fields per section *and* a raw editor
- **RCON, server-local**: uses the ServerAdminPassword; live player list with
  **kick / ban**, save world, "save & stop" and broadcasts
- **Connect box** on the dashboard: shows the address to join with, auto-detects
  the public IP (falls back to the local address), and distinguishes the Steam
  server-browser port (query) from the in-game `open` port (game)
- **Multiple user accounts**: create / reset / delete; all equal
- Runs as an unprivileged user behind a narrow `sudo` allow-list

## Requirements

- A **Proxmox LXC container** (Ubuntu 24.04, unprivileged is fine),
  **8–16 GB RAM recommended** (min. 6 GB; more depending on map/mods), ~40+ GB disk
- Root access inside the container
- On the **Proxmox host**: `vm.max_map_count` must be high enough (ARK maps a huge
  number of memory regions). Modern kernels already default high; if the installer
  warns, set it on the host:
  ```bash
  echo 'vm.max_map_count=262144' > /etc/sysctl.d/99-ark.conf
  sysctl -p /etc/sysctl.d/99-ark.conf
  ```
  This is host-wide and cannot be set from inside an unprivileged LXC. Giving the
  container some swap (`pct set <VMID> --swap 4096`) also helps absorb the memory
  spike during first-time world generation.

## Installation

Create the container on the Proxmox host (example):

```bash
pct create 210 local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst \
  --hostname ark --cores 4 --memory 16384 --swap 4096 \
  --rootfs local-lvm:60 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1 --onboot 1
pct start 210 && pct enter 210
```

Inside the container:

```bash
git clone https://github.com/Schattenwelt/ARK-Control-Panel.git
cd ARK-Control-Panel
bash install.sh
```

The installer asks for a panel username and password (or run it non-interactively
with `PANEL_USER=... PANEL_PASS=... bash install.sh`). The panel listens on
**port 80** by default; override with `PANEL_PORT=8080 bash install.sh`.

Then open `http://<container-ip>`, pick a map under **Maps**, add Workshop IDs
under **Mods** and click **Sync mods**, review settings under **Config**, and hit
**Start**. The first start takes a while (world generation).

Ports to open in your firewall: **7777/UDP** (game) and **27015/UDP** (query).
Join from the Steam server browser via `IP:27015`.

## Maps

The official maps are built in (The Island, The Center, Scorched Earth, Ragnarok,
Aberration, Extinction, Valguero, Genesis 1/2, Crystal Isles, Lost Island,
Fjordur). The paid expansions (Scorched Earth, Aberration, Extinction, both
Genesis parts) carry a **DLC** badge — the server downloads every map for free,
but players must own the DLC on Steam to join those maps.

For a mod map, enter the **map code** (e.g. `Ragnarok`) and the **mod ID**; the mod
must also be listed under Mods so its files get installed.

## Mods

Mod management on a Linux ARK: Survival Evolved server has two non-obvious
requirements that this panel handles for you:

1. **The server does not extract mods on Linux.** SteamCMD delivers Workshop mods
   as compressed `.z` archives. The Windows server unpacks them on boot and writes
   the result to `ShooterGame/Content/Mods/<id>/`; the Linux server never does this
   (even with `-automanagedmods`). The panel's **Sync mods** button runs
   `ark-mods.py`, which downloads each mod via SteamCMD, extracts the `.z` files,
   builds the `.mod` file and installs everything into the server.
2. **Mods are activated via `ActiveMods=`, not the command line.** ARK: SE reads
   the mod list from `ActiveMods=` in `[ServerSettings]` of `GameUserSettings.ini`.
   ARK rewrites that file (as UTF-16) on shutdown and drops the line, so the start
   wrapper writes `ActiveMods=` fresh on **every** start, encoding-aware.

Workflow: add the Workshop ID under **Mods**, click **Sync mods** (wait for it to
finish — large mods take a while), then restart the server. Load order in the list
is the load order passed to the server; map mods generally go first.

Leave **auto-managed mods** *off* once you sync manually — on Linux it does not
install mods reliably and can interfere with the manually installed files.

> This applies to ARK: **Survival Evolved** (Steam Workshop). ARK: **Survival
> Ascended** uses a different mod system (CurseForge) and is not supported here.

## Updating the panel

```bash
git pull
sudo bash scripts/update.sh
```

Users, maps, mods and config are left untouched.

## Repairing RCON

If RCON is unreachable:

```bash
sudo bash scripts/repair.sh
```

Sets `RCONEnabled=True`, the RCON port and, if missing, a `ServerAdminPassword`,
restarts the server and checks the port.

## Project layout

```
install.sh            Full installer (run once in a fresh container)
scripts/update.sh     Refresh panel code from the repo, restart the panel
scripts/repair.sh     Ensure RCON is set up in GameUserSettings.ini
src/                  Panel source (Flask app, RCON, i18n, templates, CSS)
src/ark-launch.sh     Start wrapper (builds the start line, writes ActiveMods)
src/ark-update.sh     SteamCMD update + save backups
src/ark-mods.py       Mod sync: download, .z extraction, .mod generation
```

## Data storage (in the panel directory /opt/ark-panel)

- `panel.json` – base config (paths, service names, secret key)
- `users.json` – user accounts (hashed passwords)
- `runtime.json` – launch parameters: map, mods, ports, public address, extra args
- `maps.json` – custom/mod maps
- `mods.json` – optional display names for mod IDs

## systemd services

- `ark.service` – the game server (started via `ark-launch.sh`)
- `ark-panel.service` – the web panel (waitress)
- `ark-update.service` – SteamCMD update (oneshot)
- `ark-mods.service` – mod sync (oneshot, triggered by the Sync button)

## Security notes

Passwords are hashed (Werkzeug) and all mutating actions are CSRF-protected. The
panel serves plain HTTP — put it behind a reverse proxy with TLS for access beyond
your LAN. `panel.json` and `users.json` hold sensitive data and are created with
`600` (git-ignored).

## Credits

The ARK `.z` archive and `.mod` file formats implemented in `ark-mods.py` follow
the publicly documented structure; the reference behaviour was cross-checked
against the community project [Ark_Mod_Downloader](https://github.com/barrycarey/Ark_Mod_Downloader)
and [arkit.py](https://github.com/project-umbrella/arkit.py).

## License

MIT — see [LICENSE](LICENSE).
