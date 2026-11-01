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
install -m 0755 "$REPO_DIR/src/ark-mods.py" /home/ark/ark-mods.py
# Bestehende panel.json um neue Schlüssel ergänzen (appid, tz + feste Ports),
# ohne vorhandene Werte zu überschreiben. So greift die Port-Sperre auch bei einer
# vor diesem Update angelegten Installation. Ports kommen – falls noch nicht
# gesetzt – aus der runtime.json (sonst Standardwerte).
python3 - "$PANEL_DIR/panel.json" "$PANEL_DIR/runtime.json" <<'PY' || true
import json, os, sys
pj, rj = sys.argv[1], sys.argv[2]
if not os.path.exists(pj):
    sys.exit(0)
conf = json.load(open(pj))
try:
    rt = json.load(open(rj))
except (OSError, ValueError):
    rt = {}
defaults = {
    "appid": "376030",
    "tz": "Europe/Berlin",
    "game_port": int(rt.get("port", 7777)),
    "query_port": int(rt.get("query_port", 27015)),
    "rcon_port": int(rt.get("rcon_port", 27020)),
}
added = [k for k in defaults if k not in conf]
for k in added:
    conf[k] = defaults[k]
if added:
    tmp = pj + ".tmp"
    json.dump(conf, open(tmp, "w"), indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, pj)
    print("panel.json ergänzt:", ", ".join(added))
print("Feste Ports: Spiel %s/UDP · Query %s/UDP · RCON %s/TCP"
      % (conf["game_port"], conf["query_port"], conf["rcon_port"]))
PY

chown -R "$ARK_USER":"$ARK_USER" "$PANEL_DIR" /home/ark/ark-launch.sh /home/ark/ark-update.sh /home/ark/ark-mods.py
chmod 600 "$PANEL_DIR/panel.json" "$PANEL_DIR/users.json" 2>/dev/null || true
systemctl restart ark-panel.service
echo "Panel aktualisiert und neu gestartet."
