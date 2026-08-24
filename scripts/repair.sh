#!/usr/bin/env bash
# Stellt sicher, dass RCON in der GameUserSettings.ini aktiv ist und ein
# ServerAdminPassword existiert. Stoppt/startet den Server dafür kurz.
set -euo pipefail
GUS="/home/ark/arkserver/ShooterGame/Saved/Config/LinuxServer/GameUserSettings.ini"
SERVICE="ark.service"; RCON_PORT="27020"; WAIT_SECONDS=240
[ "$(id -u)" -eq 0 ] || { echo "Bitte als root ausführen." >&2; exit 1; }
mkdir -p "$(dirname "$GUS")"
cp -a "$GUS" "${GUS}.bak.$(date +%s)" 2>/dev/null || true
systemctl stop "$SERVICE" || true; sleep 2

python3 - "$GUS" "$RCON_PORT" <<'PY'
import sys, secrets, configparser, os
gus, port = sys.argv[1], sys.argv[2]
cp = configparser.ConfigParser(strict=False)
cp.optionxform = str
if os.path.exists(gus):
    cp.read(gus, encoding="utf-8")
if not cp.has_section("ServerSettings"):
    cp.add_section("ServerSettings")
cp.set("ServerSettings", "RCONEnabled", "True")
cp.set("ServerSettings", "RCONPort", port)
pw = cp.get("ServerSettings", "ServerAdminPassword", fallback="").strip()
if not pw:
    pw = secrets.token_urlsafe(12)
    cp.set("ServerSettings", "ServerAdminPassword", pw)
    print("Neues ServerAdminPassword: %s  (bitte notieren)" % pw)
with open(gus, "w", encoding="utf-8") as fh:
    cp.write(fh, space_around_delimiters=False)
PY

chown ark:ark "$GUS" 2>/dev/null || true
systemctl start "$SERVICE"
echo "Warte auf RCON-Port $RCON_PORT (ARK-Start dauert je nach Karte einige Minuten) ..."
waited=0
while [ "$waited" -lt "$WAIT_SECONDS" ]; do
  ss -tlnH 2>/dev/null | grep -q ":${RCON_PORT}\b" && { echo "RCON lauscht auf $RCON_PORT."; exit 0; }
  sleep 5; waited=$((waited+5))
done
echo "RCON nicht erreichbar – Logs prüfen: journalctl -u $SERVICE -n 40"
