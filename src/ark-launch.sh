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
print("BATTLEYE=" + q("1" if d.get("battleye", True) else ""))
print("MODS=" + q(",".join(str(m) for m in d.get("mods", []) if str(m).isdigit())))
print("EXTRA=" + q(d.get("extra_args", "")))
PY
)"
else
    MAP="TheIsland"; SESSION="ARK Server"; MAXP=70; PORT=7777; QUERY=27015
    RCONP=27020; BATTLEYE="1"; MODS=""; EXTRA=""
fi

# --- ServerAdminPassword aus der INI ziehen (für RCON) ----------------------
# encoding-bewusst: ARK schreibt die INI beim Beenden als UTF-16, dann würde ein
# ASCII-grep das Passwort nicht mehr finden (Null-Bytes zwischen den Zeichen).
ADMINPW=""
if [ -f "$GUS" ]; then
    ADMINPW="$(python3 - "$GUS" <<'PY' || true
import sys
raw = open(sys.argv[1], "rb").read()
if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
    enc = "utf-16"
elif raw[:3] == b"\xef\xbb\xbf":
    enc = "utf-8-sig"
else:
    enc = "utf-8"
for line in raw.decode(enc, "ignore").splitlines():
    s = line.strip()
    if s.lower().startswith("serveradminpassword="):
        print(s.split("=", 1)[1].strip()); break
PY
)"
fi

# --- ActiveMods in die INI schreiben ----------------------------------------
# ARK: Survival Evolved aktiviert Mods über ActiveMods= in [ServerSettings],
# nicht über -mods= allein. ARK schreibt die GameUserSettings.ini beim Beenden
# neu (als UTF-16!) und räumt dabei ActiveMods weg – deshalb setzen wir es bei
# JEDEM Start frisch, encoding-bewusst (BOM erkennen), Zeile ersetzend.
if [ -f "$GUS" ]; then
    MODS="$MODS" python3 - "$GUS" <<'PY' || echo "[ark-launch] Warnung: ActiveMods konnte nicht gesetzt werden" >&2
import os, sys
p = sys.argv[1]
mods = os.environ.get("MODS", "")
raw = open(p, "rb").read()
if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
    enc = "utf-16"
elif raw[:3] == b"\xef\xbb\xbf":
    enc = "utf-8-sig"
else:
    enc = "utf-8"
lines = [l for l in raw.decode(enc, "ignore").splitlines()
         if not l.strip().lower().startswith("activemods=")]
if mods:  # nur setzen, wenn Mods vorhanden – sonst Zeile weglassen
    out, placed = [], False
    for l in lines:
        out.append(l)
        if l.strip().lower() == "[serversettings]" and not placed:
            out.append("ActiveMods=" + mods); placed = True
    if not placed:
        out.append("[ServerSettings]"); out.append("ActiveMods=" + mods)
else:
    out = lines
open(p, "w", encoding=enc).write("\n".join(out) + "\n")
print("[ark-launch] ActiveMods=%s (encoding=%s)" % (mods or "–", enc))
PY
fi

# --- ?-Optionsteil zusammenbauen --------------------------------------------
OPTS="${MAP}?listen?SessionName=${SESSION}?MaxPlayers=${MAXP}?Port=${PORT}?QueryPort=${QUERY}?RCONEnabled=True?RCONPort=${RCONP}"
[ -n "$ADMINPW" ] && OPTS="${OPTS}?ServerAdminPassword=${ADMINPW}"

# --- Startargumente ----------------------------------------------------------
ARGS=(-server -log)
[ -n "$MODS" ] && ARGS+=("-mods=${MODS}")
[ -z "$BATTLEYE" ] && ARGS+=(-NoBattlEye)
if [ -n "$EXTRA" ]; then
    read -r -a EXTRA_ARR <<< "$EXTRA"
    ARGS+=("${EXTRA_ARR[@]}")
fi

# --- Umgebung (ARK-Server braucht seine eigenen Libs im Pfad) ---------------
cd "$(dirname "$BIN")"
export LD_LIBRARY_PATH="$(dirname "$BIN"):${LD_LIBRARY_PATH:-}"

echo "[ark-launch] Karte=$MAP  Mods=${MODS:-–}  Port=$PORT/$QUERY  RCON=$RCONP"
exec "$BIN" "$OPTS" "${ARGS[@]}"
