#!/usr/bin/env bash
###############################################################################
#  ARK: Survival Evolved Control Panel – Installer
#
#  Installiert in einem Ubuntu-LXC-Container:
#    * ARK-Dedicated-Server (SteamCMD, AppID 376030) als systemd-Service
#    * Ein login-geschütztes Web-Panel (Start/Stop/Neustart, Update, Config,
#      Karten- und Mod-Verwaltung)
#    * Update-Service + automatische Save-Backups
#
#  Ausführen IM Container als root:   bash install.sh
###############################################################################
set -euo pipefail

# ------------------------- Einstellungen (anpassbar) ------------------------
ARK_USER="ark"
ARK_HOME="/home/ark"
INSTALL_DIR="/home/ark/arkserver"
PANEL_DIR="/opt/ark-panel"
PANEL_PORT="${PANEL_PORT:-80}"         # Port des Web-Panels
APPID="376030"
STEAMCMD="/usr/games/steamcmd"

# Panel-Zugangsdaten: aus Umgebungsvariablen oder interaktiv abfragen
PANEL_USER="${PANEL_USER:-}"
PANEL_PASS="${PANEL_PASS:-}"

msg()  { printf '\n\033[1;36m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Bitte als root ausführen (im LXC-Container)."
command -v apt-get >/dev/null || die "Dieser Installer ist für Debian/Ubuntu-LXC gedacht."

# RAM-Hinweis (ARK braucht ordentlich Speicher; je nach Karte/Mods 8–16 GB)
MEM_GB=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024 ))
if [ "$MEM_GB" -lt 6 ]; then
    warn "Nur ${MEM_GB} GB RAM erkannt. ARK empfiehlt 8–16 GB (min. 6 GB)."
fi

# vm.max_map_count-Hinweis: ARK mappt sehr viele Speicherregionen. Ist der Wert
# zu niedrig, stürzt der Server trotz freiem RAM mit SIGABRT (status=6/ABRT) ab.
# Der Parameter ist HOSTWEIT und im (unprivilegierten) LXC nicht setzbar –
# daher hier nur warnen und den exakten Host-Befehl nennen.
MMC="$(cat /proc/sys/vm/max_map_count 2>/dev/null || echo 0)"
if [ "$MMC" -lt 262144 ]; then
    warn "vm.max_map_count = ${MMC} (zu niedrig – ARK braucht mind. 262144)."
    warn "Auf dem PROXMOX-HOST setzen (nicht im Container):"
    warn "  echo 'vm.max_map_count=262144' > /etc/sysctl.d/99-ark.conf && sysctl -p /etc/sysctl.d/99-ark.conf"
    warn "Ohne diesen Wert stürzt der Server beim/nach dem Laden mit SIGABRT ab."
fi

# Zugangsdaten abfragen, falls nicht gesetzt
if [ -z "$PANEL_USER" ]; then
    read -rp "Panel-Benutzername [admin]: " PANEL_USER
    PANEL_USER="${PANEL_USER:-admin}"
fi
if [ -z "$PANEL_PASS" ]; then
    while :; do
        read -rsp "Panel-Passwort: " PANEL_PASS; echo
        [ -n "$PANEL_PASS" ] || { warn "Passwort darf nicht leer sein."; continue; }
        read -rsp "Passwort wiederholen: " P2; echo
        [ "$PANEL_PASS" = "$P2" ] && break || warn "Passwörter stimmen nicht überein."
    done
fi

# ------------------------- Pakete installieren ------------------------------
msg "Aktualisiere Paketquellen und installiere Abhängigkeiten ..."
export DEBIAN_FRONTEND=noninteractive
dpkg --add-architecture i386
apt-get update -y
apt-get install -y --no-install-recommends software-properties-common ca-certificates
add-apt-repository -y multiverse
add-apt-repository -y universe
apt-get update -y

# SteamCMD-Lizenz vorab akzeptieren (sonst interaktiver Dialog)
echo steam steam/question select "I AGREE" | debconf-set-selections
echo steam steam/license note '' | debconf-set-selections

apt-get install -y --no-install-recommends \
    steamcmd lib32gcc-s1 lib32stdc++6 \
    python3 python3-venv python3-pip \
    sudo curl tar xz-utils locales procps

locale-gen en_US.UTF-8 >/dev/null 2>&1 || true

# ------------------------- Benutzer anlegen ---------------------------------
msg "Lege Benutzer '$ARK_USER' an ..."
if ! id "$ARK_USER" >/dev/null 2>&1; then
    useradd -m -d "$ARK_HOME" -s /bin/bash "$ARK_USER"
fi
usermod -aG systemd-journal "$ARK_USER" || true

# ------------------------- ARK-Server installieren --------------------------
# Hinweis: Beim allerersten SteamCMD-Lauf ist der App-/Depot-Cache noch leer,
# weshalb der erste app_update oft mit "Missing configuration" abbricht (und
# dabei sogar Exit-Code 0 liefern kann). Deshalb wird auf die vorhandene Binary
# geprüft und bis zu 5x wiederholt, statt dem Exit-Code zu vertrauen.
msg "Installiere ARK-Server via SteamCMD (mehrere GB, kann lange dauern) ..."
ARK_BIN="$INSTALL_DIR/ShooterGame/Binaries/Linux/ShooterGameServer"
tries=0
while [ ! -x "$ARK_BIN" ] && [ "$tries" -lt 5 ]; do
    tries=$((tries+1))
    [ "$tries" -gt 1 ] && { warn "SteamCMD-Versuch $tries ('Missing configuration' beim 1. Lauf ist normal) ..."; sleep 5; }
    sudo -u "$ARK_USER" -H bash -c "\
        '$STEAMCMD' +force_install_dir '$INSTALL_DIR' \
        +login anonymous +app_update '$APPID' validate +quit" || true
done
[ -x "$ARK_BIN" ] || die "ARK-Server-Binary nach $tries Versuchen nicht vorhanden – Logs prüfen: ~${ARK_USER}/.local/share/Steam/logs/stderr.txt"

# steamclient.so für das SDK verlinken
msg "Richte steamclient.so ein ..."
sudo -u "$ARK_USER" -H bash -c "\
    SC=\$(find \"\$HOME/.steam\" \"\$HOME/Steam\" '$INSTALL_DIR' -name steamclient.so 2>/dev/null | head -n1 || true); \
    if [ -n \"\$SC\" ]; then mkdir -p \"\$HOME/.steam/sdk64\"; ln -sf \"\$SC\" \"\$HOME/.steam/sdk64/steamclient.so\"; fi"

# ------------------------- Grund-Config + RCON ------------------------------
msg "Bereite GameUserSettings.ini vor (RCON aktiviert, Admin-Passwort erzeugt) ..."
RCON_PW="$(python3 -c 'import secrets;print(secrets.token_urlsafe(12))')"
CFGDIR="$INSTALL_DIR/ShooterGame/Saved/Config/LinuxServer"
sudo -u "$ARK_USER" -H bash -c "mkdir -p '$CFGDIR'"
GUS="$CFGDIR/GameUserSettings.ini"
if [ ! -f "$GUS" ]; then
    cat > "$GUS" <<EOF
[ServerSettings]
ServerAdminPassword=$RCON_PW
RCONEnabled=True
RCONPort=27020
ServerPassword=
allowThirdPersonPlayer=True

[SessionSettings]
SessionName=ARK Server

[/Script/Engine.GameSession]
MaxPlayers=70
EOF
fi
chown -R "$ARK_USER":"$ARK_USER" "$INSTALL_DIR/ShooterGame/Saved" 2>/dev/null || true

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -d "$REPO_DIR/src" ] || die "src/ nicht gefunden – bitte install.sh aus dem Repo-Wurzelverzeichnis ausführen."

msg "Kopiere Panel-Dateien nach $PANEL_DIR ..."
mkdir -p "$PANEL_DIR"
cp -r "$REPO_DIR/src/app.py" "$REPO_DIR/src/rcon.py" "$REPO_DIR/src/i18n.py" \
      "$REPO_DIR/src/templates" "$REPO_DIR/src/static" "$PANEL_DIR/"
install -m 0755 "$REPO_DIR/src/ark-launch.sh"  "$ARK_HOME/ark-launch.sh"
install -m 0755 "$REPO_DIR/src/ark-update.sh"  "$ARK_HOME/ark-update.sh"
install -m 0755 "$REPO_DIR/src/ark-mods.py"    "$ARK_HOME/ark-mods.py"
chown "$ARK_USER":"$ARK_USER" "$ARK_HOME/ark-launch.sh" "$ARK_HOME/ark-update.sh" "$ARK_HOME/ark-mods.py"

# ------------------------- systemd-Units ------------------------------------
msg "Erstelle systemd-Services ..."

cat > /etc/systemd/system/ark.service <<'UNIT'
[Unit]
Description=ARK: Survival Evolved Dedicated Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ark
Group=ark
WorkingDirectory=/home/ark/arkserver/ShooterGame/Binaries/Linux
Environment=INSTALL_DIR=/home/ark/arkserver
Environment=RUNTIME=/opt/ark-panel/runtime.json
ExecStart=/home/ark/ark-launch.sh
# ARK öffnet sehr viele Dateien -> Limit hochsetzen
LimitNOFILE=100000
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/ark-update.service <<'UNIT'
[Unit]
Description=ARK Server Update (SteamCMD)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ark
Group=ark
WorkingDirectory=/home/ark/arkserver
Environment=INSTALL_DIR=/home/ark/arkserver
# Server vor dem Update stoppen (mit Root-Rechten, daher '+')
ExecStartPre=+/usr/bin/systemctl stop ark.service
ExecStart=/home/ark/ark-update.sh
TimeoutStartSec=7200
UNIT

cat > /etc/systemd/system/ark-mods.service <<'UNIT'
[Unit]
Description=ARK Mod Sync (SteamCMD download + extract)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ark
Group=ark
WorkingDirectory=/home/ark/arkserver
Environment=ARK_DIR=/home/ark/arkserver
Environment=RUNTIME=/opt/ark-panel/runtime.json
# Lädt/entpackt alle Mods aus runtime.json nach ShooterGame/Content/Mods.
ExecStart=/home/ark/ark-mods.py --from-runtime /opt/ark-panel/runtime.json
TimeoutStartSec=3600
UNIT

cat > /etc/systemd/system/ark-panel.service <<'UNIT'
[Unit]
Description=ARK Control Panel (Web UI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ark
Group=ark
AmbientCapabilities=CAP_NET_BIND_SERVICE
WorkingDirectory=/opt/ark-panel
Environment=PANEL_CONFIG=/opt/ark-panel/panel.json
ExecStart=/opt/ark-panel/venv/bin/waitress-serve --listen=0.0.0.0:__PANEL_PORT__ app:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sed -i "s/__PANEL_PORT__/${PANEL_PORT}/" /etc/systemd/system/ark-panel.service

# ------------------------- Python-venv + Flask ------------------------------
msg "Richte Python-Umgebung für das Panel ein ..."
python3 -m venv "$PANEL_DIR/venv"
"$PANEL_DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$PANEL_DIR/venv/bin/pip" install flask waitress >/dev/null

# ------------------------- panel.json + Stores ------------------------------
msg "Erzeuge Panel-Konfiguration, Laufzeitdaten und ersten Benutzer ..."
PANEL_USER="$PANEL_USER" PANEL_PASS="$PANEL_PASS" \
"$PANEL_DIR/venv/bin/python" - <<'PY'
import json, os, secrets
from werkzeug.security import generate_password_hash

conf = {
    "secret_key": secrets.token_hex(32),
    "ark_dir": "/home/ark/arkserver",
    "service": "ark.service",
    "update_service": "ark-update.service",
    "mods_service": "ark-mods.service",
    "users_path": "/opt/ark-panel/users.json",
    "runtime_path": "/opt/ark-panel/runtime.json",
    "maps_path": "/opt/ark-panel/maps.json",
    "mods_path": "/opt/ark-panel/mods.json",
    "rcon_host": "127.0.0.1",
}
with open("/opt/ark-panel/panel.json", "w") as fh:
    json.dump(conf, fh, indent=2)

runtime = {
    "map": "TheIsland",
    "session_name": "ARK Server",
    "max_players": 70,
    "port": 7777,
    "query_port": 27015,
    "rcon_port": 27020,
    "battleye": True,
    "automanaged_mods": False,
    "mods": [],
    "extra_args": "",
}
with open("/opt/ark-panel/runtime.json", "w") as fh:
    json.dump(runtime, fh, indent=2)

for path, empty in (("/opt/ark-panel/maps.json", {"maps": []}),
                    ("/opt/ark-panel/mods.json", {"labels": {}})):
    with open(path, "w") as fh:
        json.dump(empty, fh, indent=2)

users = {"users": {
    os.environ["PANEL_USER"]: {"password_hash": generate_password_hash(os.environ["PANEL_PASS"])}
}}
with open("/opt/ark-panel/users.json", "w") as fh:
    json.dump(users, fh, indent=2)
PY

# ------------------------- Rechte ------------------------------------------
chown -R "$ARK_USER":"$ARK_USER" "$PANEL_DIR"
chmod 600 "$PANEL_DIR/panel.json" "$PANEL_DIR/users.json"
chmod 640 "$PANEL_DIR/runtime.json" "$PANEL_DIR/maps.json" "$PANEL_DIR/mods.json"

# ------------------------- sudoers-Regel ------------------------------------
msg "Setze eingeschränkte sudo-Rechte für das Panel ..."
SUDO_FILE=/etc/sudoers.d/ark-panel
cat > "$SUDO_FILE" <<'SUDO'
ark ALL=(root) NOPASSWD: /usr/bin/systemctl enable --now ark.service, /usr/bin/systemctl disable --now ark.service, /usr/bin/systemctl enable ark.service, /usr/bin/systemctl disable ark.service, /usr/bin/systemctl restart ark.service, /usr/bin/systemctl reset-failed ark.service, /usr/bin/systemctl start ark-update.service, /usr/bin/systemctl start ark-mods.service
SUDO
chmod 440 "$SUDO_FILE"
visudo -cf "$SUDO_FILE" >/dev/null || die "sudoers-Regel ungültig."

# ------------------------- Services aktivieren ------------------------------
msg "Aktiviere Services ..."
systemctl daemon-reload
# ark.service startet nach einem Reboot nur, wenn er zuletzt lief (Start=an, Stopp=aus).
systemctl disable ark.service >/dev/null 2>&1 || true
systemctl enable --now ark-panel.service

# ------------------------- Zusammenfassung ----------------------------------
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<DONE

$(printf '\033[1;32m')============================================================$(printf '\033[0m')
  Fertig! Das ARK Control Panel ist eingerichtet.

  Web-Panel:   http://${IP:-<container-ip>}:${PANEL_PORT}
  Login:       Benutzer '${PANEL_USER}' + dein gewähltes Passwort

  Ports (in Firewall/OPNsense freigeben):
    7777/UDP  Spielport        27015/UDP  Query
    27020/TCP RCON (nur intern nötig, kann zu bleiben)

  RCON/Admin:  ServerAdminPassword (= RCON- und In-Game-Admin-Passwort): ${RCON_PW}
               -> bitte notieren.

  Karten:      im Panel unter "Karten" auswählen (Standard: The Island).
  Mods:        im Panel unter "Mods" die Workshop-IDs eintragen.

  Autostart:   Der Server startet nach einem Reboot nur, wenn er zuletzt lief.
               Start im Panel = Autostart an, Stopp = Autostart aus.
               Der LXC selbst startet über Proxmox (Container-Option onboot=1).

  Der Spielserver ist noch NICHT gestartet – erst im Panel Karte/Mods prüfen,
  dann "Starten" klicken. Der erste Start dauert (Weltgenerierung).

  Nützliche Befehle:
    systemctl status ark.service
    journalctl -u ark.service -f
    systemctl status ark-panel.service
$(printf '\033[1;32m')============================================================$(printf '\033[0m')
DONE
