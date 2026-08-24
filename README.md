# ARK Control Panel

Ein schlankes, selbst-gehostetes Web-Panel zum Installieren, Konfigurieren und
Steuern eines **ARK: Survival Evolved Dedicated Servers** in einem Proxmox-LXC-
Container – mit login-geschützter Oberfläche, Live-Status, Ein-Klick-Update,
Config-Editor sowie **Karten-** und **Mod-Verwaltung** und RCON (Spielerliste,
Speichern, sauberes Herunterfahren, Broadcasts).

Die Oberfläche ist auf **Deutsch und Englisch** (oben umschaltbar).

> Inoffizielles Community-Projekt. Nicht mit Studio Wildcard / Snail Games
> verbunden. „ARK: Survival Evolved“ ist eine Marke des jeweiligen Inhabers.

## Features

- Serversteuerung: **Start / Neustart / Stopp** und **Update** (SteamCMD, AppID 376030)
- **Reboot-bewusst**: der Server kommt nach einem Reboot nur hoch, wenn er vorher lief
  (Start = Autostart an, Stopp = aus); der LXC selbst startet über Proxmox `onboot`
- **Kartenverwaltung**: offizielle Karten per Klick auswählen, eigene/Mod-Karten
  (Karten-Code + optionale Mod-ID) eintragen. Die Karte wird als Startparameter gesetzt.
- **Mod-Verwaltung**: Steam-Workshop-IDs in Ladereihenfolge eintragen, sortieren und
  entfernen; optional **-automanagedmods** (Server lädt/aktualisiert Mods selbst).
- **Startparameter** (Servername, Max-Spieler, Ports, BattlEye, Zusatzargumente)
- **Config-Editor** für `GameUserSettings.ini` **und** `Game.ini` – strukturierte
  Felder je Section *und* ein Roh-Editor
- **RCON, server-intern**: nutzt das ServerAdminPassword; Live-Spielerliste mit
  **Kick / Ban**, Welt speichern, „Speichern & Stoppen“ und Broadcasts
- **Mehrere Benutzerkonten**: anlegen / zurücksetzen / löschen; alle gleichberechtigt
- Läuft als unprivilegierter Benutzer mit einer engen `sudo`-Whitelist

## Voraussetzungen

- Ein **Proxmox-LXC-Container** (Ubuntu 24.04, unprivilegiert ist ok),
  **8–16 GB RAM empfohlen** (min. 6 GB; je nach Karte/Mods mehr), ~40+ GB Disk
- Root-Zugriff im Container

## Installation

Auf dem Proxmox-Host den Container anlegen (Beispiel):

```bash
pct create 210 local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst \
  --hostname ark --cores 4 --memory 16384 --swap 4096 \
  --rootfs local-lvm:60 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1 --onboot 1
pct start 210 && pct enter 210
```

Im Container:

```bash
git clone https://github.com/Schattenwelt/ark-control-panel.git
cd ark-control-panel
bash install.sh
```

Der Installer fragt nach Panel-Benutzer und -Passwort (oder nicht-interaktiv via
`PANEL_USER=... PANEL_PASS=... bash install.sh`). Das Panel läuft standardmäßig auf
**Port 80**; mit `PANEL_PORT=8080 bash install.sh` überschreibbar.

Danach `http://<container-ip>` öffnen, unter **Karten** die Karte wählen, unter
**Mods** ggf. Workshop-IDs eintragen, unter **Konfiguration** die Einstellungen
prüfen und **Starten** klicken. Der erste Start dauert (Weltgenerierung).

Freizugebende Ports: **7777/UDP** (Spiel) und **27015/UDP** (Query).

## Karten

Offizielle Karten sind vorhanden (The Island, The Center, Scorched Earth, Ragnarok,
Aberration, Extinction, Valguero, Genesis 1/2, Crystal Isles, Lost Island, Fjordur).
Für Mod-Karten den **Karten-Code** (z. B. `Ragnarok`) und die **Mod-ID** eintragen –
die Mod muss zusätzlich unter „Mods“ gelistet sein (oder `-automanagedmods` aktiv).

## Mods

Die Workshop-IDs werden beim Start als `-mods=ID1,ID2,…` übergeben – **Reihenfolge
= Ladereihenfolge**. Mit **„Mods automatisch verwalten“** lädt der Server die Mods
beim Start selbst aus dem Workshop; ohne diese Option müssen sie bereits im
Server-Ordner liegen.

## Aktualisieren des Panels

```bash
git pull
sudo bash scripts/update.sh
```

Benutzer, Karten, Mods und Config bleiben dabei unangetastet.

## RCON reparieren

Falls RCON nicht erreichbar ist:

```bash
sudo bash scripts/repair.sh
```

Setzt `RCONEnabled=True`, den RCON-Port und bei Bedarf ein `ServerAdminPassword`,
startet den Server neu und prüft den Port.

## Projektstruktur

```
install.sh            Voll-Installer (einmal im frischen Container ausführen)
scripts/update.sh     Panel-Code aus dem Repo aktualisieren, Panel neu starten
scripts/repair.sh     RCON in GameUserSettings.ini sicherstellen
src/                  Panel-Quellcode (Flask-App, RCON, i18n, Templates, CSS)
src/ark-launch.sh     Startwrapper (baut die Startzeile aus runtime.json)
src/ark-update.sh     SteamCMD-Update + Save-Backups
```

## Datenablage (im Panel-Verzeichnis /opt/ark-panel)

- `panel.json` – Grundkonfiguration (Pfade, Secret Key)
- `users.json` – Benutzerkonten (gehashte Passwörter)
- `runtime.json` – Startparameter: Karte, Mods, Ports, Zusatzargumente
- `maps.json` – eigene/Mod-Karten
- `mods.json` – optionale Namen zu Mod-IDs

## Sicherheitshinweise

Passwörter werden gehasht (Werkzeug), alle ändernden Aktionen sind CSRF-geschützt.
Das Panel liefert reines HTTP aus – für Zugriff über das LAN hinaus hinter einen
Reverse-Proxy mit TLS setzen. `panel.json` und `users.json` enthalten sensible
Daten und werden beim Installieren mit `600` angelegt (git-ignoriert).

## Lizenz

MIT – siehe [LICENSE](LICENSE).
