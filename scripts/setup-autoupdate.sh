#!/usr/bin/env bash
###############################################################################
# Richtet einen täglichen systemd-Timer ein, der dieses Repo per git pull
# aktualisiert und das Panel neu deployt (scripts/update.sh). Es wird nur das
# Panel neu gestartet – der Spielserver, deine Benutzer, Karten, Mods und die
# Konfiguration bleiben unangetastet. In der UI wird kein Git/Commit angezeigt,
# nur die Panel-Version im Footer.
#
#   sudo bash scripts/setup-autoupdate.sh              # Timer einrichten (~04:30)
#   sudo bash scripts/setup-autoupdate.sh --run-now    # + sofort einmal updaten
#   UPDATE_TIME=03:15 sudo bash scripts/setup-autoupdate.sh
#   PANEL_REPO_URL=https://github.com/Schattenwelt/ARK-Control-Panel.git sudo bash scripts/setup-autoupdate.sh
#
#   Deaktivieren: sudo systemctl disable --now ark-panel-update.timer
###############################################################################
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Bitte als root ausführen." >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UPDATE_TIME="${UPDATE_TIME:-04:30}"
RUN_NOW=0
[ "${1:-}" = "--run-now" ] && RUN_NOW=1
[ -d "$REPO_DIR/.git" ] || echo "Hinweis: $REPO_DIR ist kein git-Repo – 'git pull' wird fehlschlagen, bis es eins ist."

# optionale Remote-URL setzen
if [ -n "${PANEL_REPO_URL:-}" ] && [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" remote set-url origin "$PANEL_REPO_URL" 2>/dev/null \
        || git -C "$REPO_DIR" remote add origin "$PANEL_REPO_URL"
fi

cat > /etc/systemd/system/ark-panel-update.service <<UNIT
[Unit]
Description=ARK Control Panel self-update (git pull + redeploy)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$REPO_DIR
# git als root; danach das Panel-Deploy-Skript (kopiert Code, startet nur das Panel neu)
ExecStart=/usr/bin/git -C $REPO_DIR pull --ff-only
ExecStart=/usr/bin/env bash $REPO_DIR/scripts/update.sh
UNIT

cat > /etc/systemd/system/ark-panel-update.timer <<UNIT
[Unit]
Description=Täglicher Selbst-Update-Timer für das ARK Control Panel

[Timer]
OnCalendar=*-*-* ${UPDATE_TIME}:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now ark-panel-update.timer
echo "Auto-Update-Timer aktiv (täglich ~${UPDATE_TIME}). Nächste Läufe:"
systemctl list-timers ark-panel-update.timer --no-pager 2>/dev/null | sed -n '1,2p' || true

if [ "$RUN_NOW" -eq 1 ]; then
    echo "Starte Update jetzt ..."
    systemctl start ark-panel-update.service
    echo "Fertig. Panel-Log: journalctl -u ark-panel-update.service -n 20"
fi
