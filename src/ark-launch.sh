#!/usr/bin/env bash
###############################################################################
# ARK-Startwrapper
# Baut die ShooterGameServer-Startzeile aus runtime.json (Karte, Mods, Ports,
# Startargumente) + ServerAdminPassword aus GameUserSettings.ini.
# Wird per systemd (ark.service, ExecStart) aufgerufen.
###############################################################################
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/home/ark/arkserver}"
RUNTIME="${RUNTIME:-/opt/ark-panel/runtime.json}"
GUS="$INSTALL_DIR/ShooterGame/Saved/Config/LinuxServer/GameUserSettings.ini"
BIN="$INSTALL_DIR/ShooterGame/Binaries/Linux/ShooterGameServer"

[ -x "$BIN" ] || { echo "ShooterGameServer nicht gefunden: $BIN" >&2; exit 1; }

# --- runtime.json einlesen (als Shell-Variablen) ----------------------------
if [ -f "$RUNTIME" ]; then
    eval "$(python3 - "$RUNTIME" <<'PY'
import json, sys, shlex
d = json.load(open(sys.argv[1]))
def q(v): return shlex.quote(str(v))
print("MAP=" + q(d.get("map", "TheIsland")))
print("SESSION=" + q(d.get("session_name", "ARK Server")))
print("MAXP=" + q(d.get("max_players", 70)))
print("PORT=" + q(d.get("port", 7777)))
print("QUERY=" + q(d.get("query_port", 27015)))
print("RCONP=" + q(d.get("rcon_port", 27020)))
print("AUTOMODS=" + q("1" if d.get("automanaged_mods") else ""))
print("BATTLEYE=" + q("1" if d.get("battleye", True) else ""))
print("MODS=" + q(",".join(str(m) for m in d.get("mods", []) if str(m).isdigit())))
print("EXTRA=" + q(d.get("extra_args", "")))
PY
)"
else
    MAP="TheIsland"; SESSION="ARK Server"; MAXP=70; PORT=7777; QUERY=27015
    RCONP=27020; AUTOMODS=""; BATTLEYE="1"; MODS=""; EXTRA=""
fi

# --- ServerAdminPassword aus der INI ziehen (für RCON) ----------------------
ADMINPW=""
if [ -f "$GUS" ]; then
    ADMINPW="$(grep -ioP '^\s*ServerAdminPassword\s*=\s*\K.*' "$GUS" 2>/dev/null \
                | head -n1 | tr -d '\r' || true)"
fi

# --- ?-Optionsteil zusammenbauen --------------------------------------------
OPTS="${MAP}?listen?SessionName=${SESSION}?MaxPlayers=${MAXP}?Port=${PORT}?QueryPort=${QUERY}?RCONEnabled=True?RCONPort=${RCONP}"
[ -n "$ADMINPW" ] && OPTS="${OPTS}?ServerAdminPassword=${ADMINPW}"

# --- Startargumente ----------------------------------------------------------
ARGS=(-server -log)
[ -n "$AUTOMODS" ] && ARGS+=(-automanagedmods)
[ -n "$MODS" ] && ARGS+=("-mods=${MODS}")
[ -z "$BATTLEYE" ] && ARGS+=(-NoBattlEye)
if [ -n "$EXTRA" ]; then
    read -r -a EXTRA_ARR <<< "$EXTRA"
    ARGS+=("${EXTRA_ARR[@]}")
fi

# --- Umgebung (ARK-Server braucht seine eigenen Libs im Pfad) ---------------
cd "$(dirname "$BIN")"
export LD_LIBRARY_PATH="$(dirname "$BIN"):${LD_LIBRARY_PATH:-}"

echo "[ark-launch] Karte=$MAP  Mods=${MODS:-–}  Automanaged=${AUTOMODS:-0}  Port=$PORT/$QUERY  RCON=$RCONP"
exec "$BIN" "$OPTS" "${ARGS[@]}"
