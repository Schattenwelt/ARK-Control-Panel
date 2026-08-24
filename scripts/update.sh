#!/usr/bin/env bash
# Aktualisiert nur den Panel-Code (app.py, rcon.py, i18n.py, Templates, CSS) aus dem
# ausgecheckten Repo und startet das Panel neu. Nutzerdaten/Runtime bleiben unangetastet.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PANEL_DIR="/opt/ark-panel"; ARK_USER="ark"
[ "$(id -u)" -eq 0 ] || { echo "Bitte als root ausführen." >&2; exit 1; }
[ -d "$PANEL_DIR" ] || { echo "$PANEL_DIR fehlt – zuerst install.sh ausführen." >&2; exit 1; }
cp -r "$REPO_DIR/src/app.py" "$REPO_DIR/src/rcon.py" "$REPO_DIR/src/i18n.py" \
      "$REPO_DIR/src/templates" "$REPO_DIR/src/static" "$PANEL_DIR/"
install -m 0755 "$REPO_DIR/src/ark-launch.sh" /home/ark/ark-launch.sh
install -m 0755 "$REPO_DIR/src/ark-update.sh" /home/ark/ark-update.sh
chown -R "$ARK_USER":"$ARK_USER" "$PANEL_DIR" /home/ark/ark-launch.sh /home/ark/ark-update.sh
chmod 600 "$PANEL_DIR/panel.json" "$PANEL_DIR/users.json" 2>/dev/null || true
systemctl restart ark-panel.service
echo "Panel aktualisiert und neu gestartet."
