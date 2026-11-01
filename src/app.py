#!/usr/bin/env python3
"""
ARK: Survival Evolved Control Panel
Ein schlankes, login-geschütztes Web-Panel zum Starten, Stoppen, Aktualisieren
und Konfigurieren eines ARK-Dedicated-Servers (systemd), inkl. Karten- und
Mod-Verwaltung.
"""
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from functools import wraps

from flask import (Flask, redirect, render_template, request,
                   session, url_for, flash, jsonify)
from werkzeug.security import check_password_hash, generate_password_hash

from rcon import ArkRCON, RCONError
from i18n import translate, LANGS, DEFAULT_LANG

# ---------------------------------------------------------------------------
# Konfiguration laden
# ---------------------------------------------------------------------------
CONFIG_PATH = os.environ.get("PANEL_CONFIG", "/opt/ark-panel/panel.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
    CONF = json.load(fh)

ARK_DIR = CONF["ark_dir"]
SERVICE = CONF.get("service", "ark.service")
UPDATE_SERVICE = CONF.get("update_service", "ark-update.service")
MODS_SERVICE = CONF.get("mods_service", "ark-mods.service")
CONFIG_DIR = os.path.join(ARK_DIR, "ShooterGame", "Saved", "Config", "LinuxServer")
INI_FILES = {
    "gus": os.path.join(CONFIG_DIR, "GameUserSettings.ini"),
    "game": os.path.join(CONFIG_DIR, "Game.ini"),
}
INI_LABELS = {"gus": "GameUserSettings.ini", "game": "Game.ini"}
GUS_PATH = INI_FILES["gus"]

PANEL_DIR = os.path.dirname(CONFIG_PATH)
RUNTIME_PATH = CONF.get("runtime_path", os.path.join(PANEL_DIR, "runtime.json"))
MAPS_PATH = CONF.get("maps_path", os.path.join(PANEL_DIR, "maps.json"))
MODS_PATH = CONF.get("mods_path", os.path.join(PANEL_DIR, "mods.json"))

# Steam-AppID des ARK-Dedicated-Servers (für die Update-Prüfung)
APPID = str(CONF.get("appid", "376030"))
# Panel-Version (wird im Footer angezeigt; kein Git-/Commit-Bezug in der UI)
PANEL_VERSION = "1.1.0"

app = Flask(__name__)
app.secret_key = CONF["secret_key"]

_state_lock = threading.Lock()

# Offizielle Karten (Code -> Anzeigename). Reihenfolge = Anzeige.
OFFICIAL_MAPS = [
    # (code, name, paid)  -- paid=True = kostenpflichtiges Expansion-Pack,
    # das Spieler besitzen müssen, um beizutreten (der Server lädt alle Karten gratis).
    ("TheIsland",     "The Island",      False),
    ("TheCenter",     "The Center",      False),
    ("ScorchedEarth_P", "Scorched Earth", True),
    ("Ragnarok",      "Ragnarok",        False),
    ("Aberration_P",  "Aberration",      True),
    ("Extinction",    "Extinction",      True),
    ("Valguero_P",    "Valguero",        False),
    ("Genesis",       "Genesis: Part 1", True),
    ("CrystalIsles",  "Crystal Isles",   False),
    ("Gen2",          "Genesis: Part 2", True),
    ("LostIsland",    "Lost Island",     False),
    ("Fjordur",       "Fjordur",         False),
]
OFFICIAL_CODES = {c for c, _, _ in OFFICIAL_MAPS}

RUNTIME_DEFAULTS = {
    "map": "TheIsland",
    "session_name": "ARK Server",
    "max_players": 70,
    "port": 7777,
    "query_port": 27015,
    "rcon_port": 27020,
    "public_address": "",   # optionale öffentliche IP / DDNS-Hostname für die Anzeige
    "battleye": True,
    "server_password": "",  # Beitrittspasswort (leer = offener Server)
    "mods": [],
    "extra_args": "",
}

MAP_CODE_RE = re.compile(r"^[A-Za-z0-9_]{2,64}$")
MOD_ID_RE = re.compile(r"^\d{2,15}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{2,32}$")
MIN_PW = 6

# ---------------------------------------------------------------------------
# kleine JSON-Stores (runtime / maps / mods / users)
# ---------------------------------------------------------------------------
def _load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return json.loads(json.dumps(default))
    return json.loads(json.dumps(default))


def _save_json(path, data, mode=0o600):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def load_runtime():
    data = _load_json(RUNTIME_PATH, RUNTIME_DEFAULTS)
    merged = dict(RUNTIME_DEFAULTS)
    merged.update({k: data.get(k, v) for k, v in RUNTIME_DEFAULTS.items()})
    merged["mods"] = [str(m) for m in merged.get("mods", []) if str(m).isdigit()]
    return merged


def save_runtime(rt):
    _save_json(RUNTIME_PATH, rt)


def load_custom_maps():
    """Eigene/Mod-Karten: Liste aus {code, name, mod_id}."""
    data = _load_json(MAPS_PATH, {"maps": []})
    out = []
    for m in data.get("maps", []):
        if m.get("code"):
            out.append({"code": m["code"], "name": m.get("name", m["code"]),
                        "mod_id": str(m.get("mod_id", "") or "")})
    return out


def save_custom_maps(maps):
    _save_json(MAPS_PATH, {"maps": maps})


def load_mod_labels():
    """Optionale Namen zu Mod-IDs: {id: name}."""
    return _load_json(MODS_PATH, {"labels": {}}).get("labels", {})


def save_mod_labels(labels):
    _save_json(MODS_PATH, {"labels": labels})


# ---------------------------------------------------------------------------
# Benutzer-Store (users.json) – alle Konten sind gleichberechtigt
# ---------------------------------------------------------------------------
USERS_PATH = CONF.get("users_path", os.path.join(PANEL_DIR, "users.json"))
_users_lock = threading.Lock()


def load_users():
    if os.path.exists(USERS_PATH):
        with open(USERS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh).get("users", {})
    if "username" in CONF and "password_hash" in CONF:
        return {CONF["username"]: {"password_hash": CONF["password_hash"]}}
    return {}


def save_users(users):
    _save_json(USERS_PATH, {"users": users})


def current_user():
    name = session.get("user")
    if not name or name not in load_users():
        return None
    return {"name": name}


# ---------------------------------------------------------------------------
# Auth / CSRF / i18n
# ---------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            session.clear()
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    tok = session.get("csrf")
    if not tok:
        tok = secrets.token_hex(16)
        session["csrf"] = tok
    return tok


def check_csrf():
    return request.form.get("csrf") and request.form.get("csrf") == session.get("csrf")


app.jinja_env.globals["csrf_token"] = csrf_token


def current_lang():
    lang = request.cookies.get("lang", DEFAULT_LANG)
    return lang if lang in LANGS else DEFAULT_LANG


def t(key, **kw):
    return translate(current_lang(), key, **kw)


app.jinja_env.globals["t"] = t
app.jinja_env.globals["current_lang"] = current_lang
app.jinja_env.globals["LANGS"] = LANGS
app.jinja_env.globals["PANEL_VERSION"] = PANEL_VERSION


@app.context_processor
def inject_me():
    return {"me": current_user()}


@app.route("/lang/<code>")
def set_lang(code):
    resp = redirect(request.referrer or url_for("dashboard"))
    if code in LANGS:
        resp.set_cookie("lang", code, max_age=31536000, samesite="Lax")
    return resp


# ---------------------------------------------------------------------------
# systemd-Steuerung
# ---------------------------------------------------------------------------
def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "Zeitüberschreitung beim Ausführen des Befehls."
    except (FileNotFoundError, OSError) as e:
        # z. B. 'sudo' oder 'journalctl' nicht vorhanden -> nicht crashen,
        # sondern als Fehlschlag melden (Aufrufer haben Fallbacks)
        return 1, str(e)


def service_active(name):
    _rc, out = run(["systemctl", "is-active", name])
    return out


def service_enabled(name):
    _rc, out = run(["systemctl", "is-enabled", name])
    return out


def svc(*args):
    return run(["sudo", "-n", "systemctl", *args])


def stop_service():
    """ARK-Dienst stoppen und Erfolg am tatsächlichen Zustand messen.

    ARK beendet sich bei SIGTERM (systemctl stop) nicht mit Exit 0, sondern mit
    SIGABRT. systemd meldet das als 'failed' und 'disable --now' gibt einen
    Fehlercode zurück – obwohl der Server sauber gestoppt wurde. Deshalb wird
    hier nicht der Exit-Code ausgewertet, sondern ob der Dienst danach noch
    läuft. reset-failed räumt den kosmetischen 'failed'-Marker weg (best effort;
    schlägt ohne passenden sudoers-Eintrag still fehl, ohne den Stop zu stören).
    """
    svc("disable", "--now", SERVICE)
    svc("reset-failed", SERVICE)
    return service_active(SERVICE) != "active"


def recent_logs(name, lines=60):
    """Journal einer Unit lesen (der ark-User ist in der systemd-journal-Gruppe)."""
    rc, out = run(["journalctl", "-u", name, "-n", str(lines),
                   "--no-pager", "-o", "short-iso"])
    if rc == 0 and out.strip() and "-- No entries --" not in out:
        return out
    return "Keine Logs verfügbar (Rechte prüfen)."


def _tail_file(path, lines):
    """Letzte n Zeilen einer (ggf. großen) Datei effizient lesen."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            data = b""
            block = 8192
            while size > 0 and data.count(b"\n") <= lines:
                step = min(block, size)
                size -= step
                fh.seek(size)
                data = fh.read(step) + data
        text = data.decode("utf-8", "ignore")
        return "\n".join(text.splitlines()[-lines:])
    except OSError:
        return ""


def game_log_tail(lines=60):
    """Letzte Zeilen der ARK-eigenen Logdatei (überlebt Reboots; journald im LXC
    ist oft flüchtig). Fällt auf das neueste Log-Backup zurück."""
    logs_dir = os.path.join(ARK_DIR, "ShooterGame", "Saved", "Logs")
    active = os.path.join(logs_dir, "ShooterGame.log")
    if os.path.isfile(active):
        tail = _tail_file(active, lines)
        if tail.strip():
            return tail
    try:
        backups = sorted(
            (os.path.join(logs_dir, f) for f in os.listdir(logs_dir) if f.endswith(".log")),
            key=os.path.getmtime, reverse=True)
    except OSError:
        backups = []
    for path in backups:
        tail = _tail_file(path, lines)
        if tail.strip():
            return tail
    return ""


def server_log(lines=60):
    """Server-Log fürs Dashboard: bevorzugt das Unit-Journal (zeigt auch Startfehler
    des Wrappers), fällt aber auf die ARK-Logdatei zurück, wenn journald leer ist."""
    j = recent_logs(SERVICE, lines)
    if "Keine Logs verfügbar" not in j:
        return j
    g = game_log_tail(lines)
    return g if g.strip() else j


# ---------------------------------------------------------------------------
# INI-Handling (GameUserSettings.ini / Game.ini) – zeilenbasiert, robust
# ---------------------------------------------------------------------------
def _read_text(path):
    with open(path, "rb") as fh:
        data = fh.read()
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def parse_ini(text):
    """Zeilenweise in Einträge zerlegen (Struktur bleibt erhalten):
    {'type':'section'|'kv'|'raw', ...}. Doppelte Keys werden unterstützt."""
    entries = []
    idx = 0
    for line in text.replace("\r", "").split("\n"):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            entries.append({"type": "section", "name": s[1:-1], "raw": line})
        elif s and not s.startswith((";", "#")) and "=" in line:
            key, val = line.split("=", 1)
            entries.append({"type": "kv", "key": key.strip(), "value": val.strip(),
                            "id": "f%d" % idx, "raw": line})
            idx += 1
        else:
            entries.append({"type": "raw", "raw": line})
    return entries


def group_ini(entries):
    """Fürs Template: kv-Felder unter ihre Section gruppieren."""
    groups, cur = [], {"name": "", "fields": []}
    for e in entries:
        if e["type"] == "section":
            if cur["name"] or cur["fields"]:
                groups.append(cur)
            cur = {"name": e["name"], "fields": []}
        elif e["type"] == "kv":
            cur["fields"].append(e)
    if cur["name"] or cur["fields"]:
        groups.append(cur)
    return groups


def apply_ini(entries, edits):
    out = []
    for e in entries:
        if e["type"] == "kv" and e["id"] in edits:
            out.append("%s=%s" % (e["key"], edits[e["id"]]))
        else:
            out.append(e["raw"])
    text = "\n".join(out)
    return text if text.endswith("\n") else text + "\n"


def read_ini(key):
    path = INI_FILES[key]
    raw = _read_text(path) if os.path.exists(path) else ""
    return raw, parse_ini(raw)


def write_ini(key, text):
    """INI atomar schreiben (Temp-Datei + os.replace) – ein Abbruch mitten im
    Schreiben hinterlässt so nie eine halbe Datei. Dateirechte bleiben erhalten."""
    path = INI_FILES[key]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        mode = 0o644
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass
    os.replace(tmp, path)


def ini_get(path, section, key):
    """Wert eines Keys in einer bestimmten Section lesen (oder None)."""
    if not os.path.exists(path):
        return None
    in_sec = False
    for line in _read_text(path).replace("\r", "").split("\n"):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_sec = (s[1:-1] == section)
        elif in_sec and "=" in s and not s.startswith((";", "#")):
            k, v = s.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return None


def ini_set(path, section, key, value):
    """Key in Section setzen/ergänzen; Section bei Bedarf anlegen. Erhält den Rest."""
    raw = _read_text(path) if os.path.exists(path) else ""
    lines = raw.replace("\r", "").split("\n")
    out, in_sec, done, sec_seen = [], False, False, False
    sec_end_idx = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if in_sec and not done:
                sec_end_idx = len(out)  # Section endet hier
            in_sec = (s[1:-1] == section)
            if in_sec:
                sec_seen = True
            out.append(line)
            continue
        if in_sec and not done and "=" in s and not s.startswith((";", "#")):
            k = s.split("=", 1)[0].strip()
            if k == key:
                out.append("%s=%s" % (key, value))
                done = True
                continue
        out.append(line)
    if not done:
        if sec_seen:
            # ans Ende der Section einfügen (vor der nächsten Section bzw. am Ende)
            insert_at = sec_end_idx if sec_end_idx is not None else len(out)
            out.insert(insert_at, "%s=%s" % (key, value))
        else:
            if out and out[-1].strip() != "":
                out.append("")
            out.append("[%s]" % section)
            out.append("%s=%s" % (key, value))
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# RCON (Passwort/Port aus GameUserSettings.ini bzw. runtime.json)
# ---------------------------------------------------------------------------
def rcon_config():
    rt = load_runtime()
    port = str(rt.get("rcon_port") or "27020")
    password = ini_get(GUS_PATH, "ServerSettings", "ServerAdminPassword") or ""
    # RCON wird beim Start ohnehin aktiviert -> „verfügbar“, sobald ein Passwort existiert.
    enabled = bool(password)
    return enabled, port, password


def rcon_connect():
    enabled, port, password = rcon_config()
    if not password:
        raise RCONError("Kein ServerAdminPassword gesetzt – RCON braucht ein Passwort.")
    return ArkRCON(CONF.get("rcon_host", "127.0.0.1"), port, password, timeout=4)


def ensure_rcon_configured():
    """Setzt RCONEnabled/RCONPort in der INI und erzeugt bei Bedarf ein
    ServerAdminPassword. Gibt das erzeugte Passwort zurück (oder None)."""
    rt = load_runtime()
    ini_set(GUS_PATH, "ServerSettings", "RCONEnabled", "True")
    ini_set(GUS_PATH, "ServerSettings", "RCONPort", str(rt.get("rcon_port") or "27020"))
    password = ini_get(GUS_PATH, "ServerSettings", "ServerAdminPassword")
    generated = None
    if not password:
        generated = secrets.token_urlsafe(12)
        ini_set(GUS_PATH, "ServerSettings", "ServerAdminPassword", generated)
    return generated


# ---------------------------------------------------------------------------
# Karten-/Mod-Helfer
# ---------------------------------------------------------------------------
def local_ipv4():
    """Primäre lokale IPv4 des Containers (ausgehendes Interface), ohne echten Verbindungsaufbau."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # nichts wird gesendet; ermittelt nur die Quell-IP
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()


# Öffentliche IP über externe Echo-Dienste ermitteln (für Server hinter NAT).
# Ergebnis wird gecacht; auch Fehlschläge werden kurz gecacht, damit das
# Dashboard ohne Internet-Egress nicht bei jedem Aufruf blockiert.
_PUBIP_SERVICES = [
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
    "https://ifconfig.me/ip",
]
_PUBIP_TTL = 600        # gültige IP 10 Minuten cachen
_PUBIP_FAIL_TTL = 120   # Fehlschlag 2 Minuten cachen
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_pubip_cache = {"ip": None, "ts": 0.0, "ok": False}


def detect_public_ip(timeout=2.0):
    """Öffentliche IPv4 ermitteln (gecacht). Gibt die IP oder None zurück."""
    now = time.time()
    ttl = _PUBIP_TTL if _pubip_cache["ok"] else _PUBIP_FAIL_TTL
    if now - _pubip_cache["ts"] < ttl:
        return _pubip_cache["ip"]
    ip = None
    for url in _PUBIP_SERVICES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ark-panel"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                candidate = resp.read().decode("utf-8", "ignore").strip()
            if _IPV4_RE.match(candidate):
                ip = candidate
                break
        except Exception:
            continue
    _pubip_cache.update(ip=ip, ts=now, ok=bool(ip))
    return ip


def all_maps():
    """Offizielle + eigene Karten als Liste aus dicts {code, name, mod_id, official}."""
    maps = [{"code": c, "name": n, "mod_id": "", "official": True, "paid": p}
            for c, n, p in OFFICIAL_MAPS]
    for m in load_custom_maps():
        maps.append({"code": m["code"], "name": m["name"],
                     "mod_id": m.get("mod_id", ""), "official": False, "paid": False})
    return maps


def map_name_for(code):
    for m in all_maps():
        if m["code"] == code:
            return m["name"]
    return code


def active_mods_view():
    """Aktive Mods mit optionalem Namen für die Anzeige."""
    labels = load_mod_labels()
    return [{"id": mid, "name": labels.get(mid, "")} for mid in load_runtime()["mods"]]


# ---------------------------------------------------------------------------
# Routen: Auth
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "")
        pw = request.form.get("password", "")
        info = load_users().get(user)
        if info and check_password_hash(info["password_hash"], pw):
            session["user"] = user
            session.permanent = False
            nxt = request.args.get("next") or url_for("dashboard")
            if not nxt.startswith("/"):
                nxt = url_for("dashboard")
            return redirect(nxt)
        flash(t("login_bad"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routen: Dashboard
# ---------------------------------------------------------------------------
_cpu_prev = {}          # gecachter /proc/stat-Snapshot für nicht-blockierende CPU%-Messung
_cpu_lock = threading.Lock()


def _read_cpu_times():
    """Gesamt- und Idle-Jiffies aus /proc/stat (erste Zeile)."""
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
    except OSError:
        return None
    if len(parts) < 5 or parts[0] != "cpu":
        return None
    vals = [int(x) for x in parts[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)   # idle + iowait
    total = sum(vals)
    return total, idle


def _cpu_percent():
    """CPU-Auslastung in % über das Delta zum letzten Aufruf (nicht blockierend).
    Beim ersten Aufruf noch kein Delta -> None."""
    cur = _read_cpu_times()
    if not cur:
        return None
    with _cpu_lock:
        prev = _cpu_prev.get("v")
        _cpu_prev["v"] = cur
    if not prev:
        return None
    dtotal = cur[0] - prev[0]
    didle = cur[1] - prev[1]
    if dtotal <= 0:
        return None
    return round((1.0 - didle / dtotal) * 100.0, 1)


def _mem_info():
    """(genutzt_MB, gesamt_MB, prozent) aus /proc/meminfo."""
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k.strip()] = int(v.split()[0])   # in kB
    except OSError:
        return None
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    if not total:
        return None
    used = total - avail
    return round(used / 1024), round(total / 1024), round(used / total * 100, 1)


def _disk_info(path):
    """(genutzt_GB, gesamt_GB, prozent) für den Mount von path."""
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    if not total:
        return None
    used = total - free
    return round(used / 1024**3, 1), round(total / 1024**3, 1), round(used / total * 100, 1)


_ark_version_cache = {"v": None, "t": 0}


def ark_version():
    """Liest die ARK-Serverversion aus dem Log (Zeile 'ARK Version: X').
    Gecacht (60s), da sich die Version nur bei Update/Neustart ändert."""
    now = time.time()
    if _ark_version_cache["v"] and now - _ark_version_cache["t"] < 60:
        return _ark_version_cache["v"]
    logs_dir = os.path.join(ARK_DIR, "ShooterGame", "Saved", "Logs")
    candidates = []
    active = os.path.join(logs_dir, "ShooterGame.log")
    if os.path.isfile(active):
        candidates.append(active)
    try:
        backups = sorted(
            (os.path.join(logs_dir, f) for f in os.listdir(logs_dir)
             if f.startswith("ShooterGame-backup-") and f.endswith(".log")),
            key=os.path.getmtime, reverse=True)
        candidates.extend(backups[:3])   # aktives + die letzten Backups
    except OSError:
        pass
    ver = None
    for path in candidates:
        try:
            with open(path, "r", errors="ignore") as f:
                for line in f:
                    m = re.search(r"ARK Version:\s*([\d.]+)", line)
                    if m:
                        ver = m.group(1)
                        break
        except OSError:
            continue
        if ver:
            break
    if ver:
        _ark_version_cache.update(v=ver, t=now)
    return ver


def installed_build():
    """Installierte Build-ID aus steamapps/appmanifest_<APPID>.acf (oder None)."""
    acf = os.path.join(ARK_DIR, "steamapps", "appmanifest_%s.acf" % APPID)
    try:
        with open(acf, "r", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return None
    m = re.search(r'"buildid"\s+"(\d+)"', text)
    return m.group(1) if m else None


_latest_cache = {"build": None, "ts": 0.0}


def latest_build():
    """Neueste öffentliche Build-ID von api.steamcmd.net (gecacht, 30 min)."""
    now = time.time()
    if _latest_cache["build"] and now - _latest_cache["ts"] < 1800:
        return _latest_cache["build"]
    try:
        req = urllib.request.Request("https://api.steamcmd.net/v1/info/%s" % APPID,
                                     headers={"User-Agent": "ark-panel"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.load(resp)
        build = str(data["data"][APPID]["depots"]["branches"]["public"]["buildid"])
        _latest_cache.update(build=build, ts=now)
        return build
    except Exception:
        return None


def update_status():
    """Vergleicht installierte vs. neueste Build-ID.
    Gibt (installed, latest, status) mit status in current|available|unknown."""
    inst = installed_build()
    lat = latest_build()
    if not inst or not lat:
        return inst, lat, "unknown"
    return inst, lat, ("current" if inst == lat else "available")


def system_stats():
    """Sammelt CPU/RAM/Disk für den Ressourcen-Monitor + ARK-Version."""
    cpu = _cpu_percent()
    mem = _mem_info()
    disk = _disk_info(ARK_DIR)
    stats = {"cpu": cpu}
    if mem:
        stats.update(mem_used=mem[0], mem_total=mem[1], mem_pct=mem[2])
    if disk:
        stats.update(disk_used=disk[0], disk_total=disk[1], disk_pct=disk[2])
    ver = ark_version()
    if ver:
        stats["version"] = ver
    return stats


@app.route("/")
@login_required
def dashboard():
    rt = load_runtime()
    manual = rt.get("public_address", "").strip()
    if manual:
        ip, kind = manual, "manual"
    else:
        pub = detect_public_ip()
        if pub:
            ip, kind = pub, "auto"
        else:
            ip, kind = local_ipv4(), "local"
    return render_template(
        "dashboard.html",
        state=service_active(SERVICE),
        update_state=service_active(UPDATE_SERVICE),
        enabled=service_enabled(SERVICE),
        rcon_enabled=rcon_config()[0],
        logs=server_log(),
        active_map=map_name_for(rt["map"]),
        mods_count=len(rt["mods"]),
        service=SERVICE,
        stats=system_stats(),
        connect_ip=ip,
        connect_query=rt.get("query_port", 27015),
        connect_game=rt.get("port", 7777),
        connect_kind=kind,
        installed_build=installed_build(),
    )


@app.route("/status")
@login_required
def status():
    return jsonify(
        server=service_active(SERVICE),
        update=service_active(UPDATE_SERVICE),
        enabled=service_enabled(SERVICE),
        stats=system_stats(),
        logs=server_log(60),
    )


@app.route("/action", methods=["POST"])
@login_required
def action():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("dashboard"))
    act = request.form.get("act")
    if act == "start":
        rc, out = svc("enable", "--now", SERVICE)
        flash(t("srv_started") if rc == 0 else out)
    elif act == "stop":
        flash(t("srv_stopped") if stop_service() else t("srv_stop_failed"))
    elif act == "restart":
        svc("enable", SERVICE)
        rc, out = svc("restart", SERVICE)
        flash(t("srv_restarted") if rc == 0 else out)
    elif act == "update":
        rc, out = svc("start", UPDATE_SERVICE)
        flash(t("update_started") if rc == 0 else t("update_failed", out=out))
    else:
        flash(t("unknown_action"))
    return redirect(url_for("dashboard"))


@app.route("/update-logs")
@login_required
def update_logs():
    return jsonify(state=service_active(UPDATE_SERVICE),
                   logs=recent_logs(UPDATE_SERVICE, 80))


@app.route("/update-check", methods=["POST"])
@login_required
def update_check():
    if not check_csrf():
        return jsonify(ok=False, msg=t("csrf_invalid"))
    inst, lat, st = update_status()
    return jsonify(ok=True, installed=inst, latest=lat, status=st)


# ---------------------------------------------------------------------------
# Routen: Karten
# ---------------------------------------------------------------------------
@app.route("/maps")
@login_required
def maps_page():
    rt = load_runtime()
    return render_template("maps.html", rt=rt,
                           official=[{"code": c, "name": n, "paid": p}
                                     for c, n, p in OFFICIAL_MAPS],
                           custom=load_custom_maps(),
                           active=rt["map"])


@app.route("/maps/select", methods=["POST"])
@login_required
def maps_select():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("maps_page"))
    code = request.form.get("code", "")
    if code not in {m["code"] for m in all_maps()}:
        flash(t("map_not_found"))
    else:
        with _state_lock:
            rt = load_runtime()
            rt["map"] = code
            save_runtime(rt)
        flash(t("map_selected", name=map_name_for(code)))
    return redirect(url_for("maps_page"))


@app.route("/maps/add", methods=["POST"])
@login_required
def maps_add():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("maps_page"))
    code = request.form.get("code", "").strip()
    name = request.form.get("name", "").strip() or code
    mod_id = request.form.get("mod_id", "").strip()
    if not MAP_CODE_RE.match(code):
        flash(t("map_code_invalid"))
    elif code in OFFICIAL_CODES or any(m["code"] == code for m in load_custom_maps()):
        flash(t("map_exists"))
    elif mod_id and not MOD_ID_RE.match(mod_id):
        flash(t("mod_id_invalid"))
    else:
        with _state_lock:
            maps = load_custom_maps()
            maps.append({"code": code, "name": name, "mod_id": mod_id})
            save_custom_maps(maps)
        flash(t("map_added", name=name))
    return redirect(url_for("maps_page"))


@app.route("/maps/delete", methods=["POST"])
@login_required
def maps_delete():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("maps_page"))
    code = request.form.get("code", "")
    with _state_lock:
        maps = load_custom_maps()
        if not any(m["code"] == code for m in maps):
            flash(t("map_not_found"))
        else:
            maps = [m for m in maps if m["code"] != code]
            save_custom_maps(maps)
            flash(t("map_deleted"))
    return redirect(url_for("maps_page"))


@app.route("/maps/launch", methods=["POST"])
@login_required
def maps_launch():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("maps_page"))
    try:
        session_name = request.form.get("session_name", "").strip() or "ARK Server"
        session_name = session_name.replace("?", "").replace("\n", "").replace("\r", "")
        public_address = request.form.get("public_address", "").strip()
        public_address = public_address.replace(" ", "").replace("\n", "").replace("\r", "")
        server_password = request.form.get("server_password", "").strip()
        server_password = server_password.replace("?", "").replace(" ", "").replace("\n", "").replace("\r", "")
        max_players = int(request.form.get("max_players", "70"))
        port = int(request.form.get("port", "7777"))
        query_port = int(request.form.get("query_port", "27015"))
        rcon_port = int(request.form.get("rcon_port", "27020"))
    except ValueError:
        flash(t("launch_bad_number"))
        return redirect(url_for("maps_page"))
    with _state_lock:
        rt = load_runtime()
        rt.update({
            "session_name": session_name,
            "max_players": max(1, max_players),
            "port": port, "query_port": query_port, "rcon_port": rcon_port,
            "public_address": public_address,
            "battleye": bool(request.form.get("battleye")),
            "server_password": server_password,
            "extra_args": request.form.get("extra_args", "").strip(),
        })
        save_runtime(rt)
    flash(t("launch_saved"))
    return redirect(url_for("maps_page"))


# ---------------------------------------------------------------------------
# Routen: Speicherstände (Save/Backup-Verwaltung)
#
# ARK: Survival Evolved legt alle Karten FLACH in ShooterGame/Saved/SavedArks/ ab:
#   <Karte>.ark                               aktive Welt
#   <Karte>_DD.MM.YYYY_HH.MM.SS.ark           automatische Backups des Servers
#   <Karte>_manual_DD.MM.YYYY_HH.MM.SS.ark    manuelle Backups aus dem Panel
#   *.arkprofile / *.arktribe (+ .profilebak/.tribebak)  Spieler & Stämme (für
#                                             alle Karten in diesem Ordner gemeinsam)
# Panel und Server laufen als derselbe User (ark) -> kein sudo-Helfer nötig.
# Es wird nie etwas gelöscht: Ersetztes wird als .corrupt-<ts> bzw. in den
# Unterordner _alt/ weggelegt.
# ---------------------------------------------------------------------------
_SAVE_MAP_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_SAVE_BACKUP_RE = re.compile(
    r"^(?P<map>[A-Za-z0-9_]+?)_(?:manual_)?\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2}\.\d{2}\.ark$")
_SAVE_PLAYER_EXT = (".arkprofile", ".arktribe", ".profilebak", ".tribebak")
SAVES_ARCHIVE_DIR = "_alt"


class SaveError(Exception):
    pass


def saves_base():
    return os.path.join(ARK_DIR, "ShooterGame", "Saved", "SavedArks")


def _save_file(name):
    """Pfad einer Datei direkt in SavedArks/ – ohne Pfad-Ausbruch."""
    base = os.path.realpath(saves_base())
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise SaveError("ungültiger Dateiname")
    path = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(path) != base:
        raise SaveError("ungültiger Dateiname")
    return path


def _file_info(path):
    st = os.stat(path)
    return {"size": round(st.st_size / 1048576, 1), "ts": st.st_mtime,
            "when": time.strftime("%d.%m.%Y %H:%M", time.localtime(st.st_mtime))}


def list_saves():
    """Pro Karte: aktive Save + Backups (neueste zuerst)."""
    base = saves_base()
    try:
        names = os.listdir(base)
    except OSError:
        return [], 0
    maps = {}
    players = 0
    for f in names:
        full = os.path.join(base, f)
        if not os.path.isfile(full):
            continue
        if f.endswith((".arkprofile", ".arktribe")):
            players += 1
            continue
        if not f.endswith(".ark"):
            continue
        mb = _SAVE_BACKUP_RE.match(f)
        try:
            info = _file_info(full)
        except OSError:
            continue
        if mb:
            maps.setdefault(mb.group("map"), {"active": None, "backups": []})["backups"].append(
                dict(info, name=f))
        elif _SAVE_MAP_RE.match(f[:-4]):
            maps.setdefault(f[:-4], {"active": None, "backups": []})["active"] = info
    active_map = load_runtime().get("map")
    out = []
    for m in sorted(maps):
        d = maps[m]
        d["backups"].sort(key=lambda b: b["ts"], reverse=True)
        out.append({"map": m, "name": map_name_for(m), "active": d["active"],
                    "backups": d["backups"], "is_current": (m == active_map)})
    return out, players


def save_backup(m):
    import shutil
    if not _SAVE_MAP_RE.match(m):
        raise SaveError("ungültiger Kartenname")
    src = _save_file(m + ".ark")
    if not os.path.isfile(src):
        raise SaveError("keine aktive Save vorhanden (%s.ark)" % m)
    dst = _save_file("%s_manual_%s.ark" % (m, time.strftime("%d.%m.%Y_%H.%M.%S")))
    shutil.copy2(src, dst)
    return os.path.basename(dst)


def save_restore(m, backup):
    import shutil
    if not _SAVE_MAP_RE.match(m):
        raise SaveError("ungültiger Kartenname")
    mb = _SAVE_BACKUP_RE.match(backup or "")
    if not mb or mb.group("map") != m:
        raise SaveError("ungültiger Backup-Dateiname")
    src = _save_file(backup)
    if not os.path.isfile(src):
        raise SaveError("Backup nicht gefunden: %s" % backup)
    active = _save_file(m + ".ark")
    if os.path.isfile(active):
        os.replace(active, "%s.corrupt-%d" % (active, int(time.time())))   # aufheben
    shutil.copy2(src, active)


def save_fresh(m, with_players=False):
    """Welt einer Karte beiseitelegen -> der Server erzeugt beim Start eine frische.
    Optional auch Spielerprofile/Stämme (gelten für alle Karten im Ordner)."""
    if not _SAVE_MAP_RE.match(m):
        raise SaveError("ungültiger Kartenname")
    base = saves_base()
    dest = os.path.join(base, SAVES_ARCHIVE_DIR, "%s_%s" % (m, time.strftime("%Y%m%d-%H%M%S")))
    moved = []
    for f in sorted(os.listdir(base)):
        full = os.path.join(base, f)
        if not os.path.isfile(full):
            continue
        mb = _SAVE_BACKUP_RE.match(f)
        mine = (f == m + ".ark" or (mb and mb.group("map") == m)
                or f.startswith(m + ".ark.corrupt-")
                or (f.startswith(m + "_") and f.endswith(".bak")))
        if with_players and f.endswith(_SAVE_PLAYER_EXT):
            mine = True
        if mine:
            os.makedirs(dest, mode=0o750, exist_ok=True)
            os.replace(full, os.path.join(dest, f))
            moved.append(f)
    if not moved:
        raise SaveError("keine Dateien für %s gefunden" % m)
    return os.path.relpath(dest, base)


@app.route("/saves")
@login_required
def saves_page():
    saves, players = list_saves()
    return render_template("saves.html", saves=saves, player_files=players,
                           archive_dir=SAVES_ARCHIVE_DIR,
                           running=(service_active(SERVICE) == "active"))


def _saves_guard():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return False
    if service_active(SERVICE) == "active":
        flash(t("saves_stop_first"))
        return False
    return True


@app.route("/saves/backup", methods=["POST"])
@login_required
def saves_backup():
    if _saves_guard():
        try:
            name = save_backup(request.form.get("map", ""))
            flash(t("saves_backup_done", name=name))
        except (SaveError, OSError) as e:
            flash(t("saves_error", err=str(e)))
    return redirect(url_for("saves_page"))


@app.route("/saves/restore", methods=["POST"])
@login_required
def saves_restore():
    if _saves_guard():
        backup = request.form.get("backup", "")
        if not backup:
            flash(t("saves_pick_backup"))
        else:
            try:
                save_restore(request.form.get("map", ""), backup)
                flash(t("saves_restored", name=backup))
            except (SaveError, OSError) as e:
                flash(t("saves_error", err=str(e)))
    return redirect(url_for("saves_page"))


@app.route("/saves/fresh", methods=["POST"])
@login_required
def saves_fresh():
    if _saves_guard():
        try:
            where = save_fresh(request.form.get("map", ""),
                               with_players=bool(request.form.get("players")))
            flash(t("saves_fresh_done", where=where))
        except (SaveError, OSError) as e:
            flash(t("saves_error", err=str(e)))
    return redirect(url_for("saves_page"))


# ---------------------------------------------------------------------------
# Routen: Mods
# ---------------------------------------------------------------------------
@app.route("/mods")
@login_required
def mods_page():
    rt = load_runtime()
    return render_template("mods.html", rt=rt, mods=active_mods_view(),
                           sync_state=service_active(MODS_SERVICE),
                           last_sync=read_last_sync())


LAST_SYNC_PATH = os.path.join(PANEL_DIR, "last_sync.json")


def read_last_sync():
    """Liest das letzte Sync-Ergebnis (last_sync.json) für die dauerhafte Anzeige.
    Gibt ein Dict mit ok/total/failed/when (lesbarer Zeitpunkt) zurück, oder None."""
    try:
        with open(LAST_SYNC_PATH) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    ts = d.get("time")
    when = ""
    if ts:
        import time
        when = time.strftime("%d.%m. %H:%M", time.localtime(ts))
    return {
        "ok": d.get("ok", 0),
        "total": d.get("total", 0),
        "failed": d.get("failed", []),
        "when": when,
    }


@app.route("/mods/sync", methods=["POST"])
@login_required
def mods_sync():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("mods_page"))
    rt = load_runtime()
    if not rt["mods"]:
        flash(t("mods_sync_empty"))
        return redirect(url_for("mods_page"))
    rc, out = svc("start", "--no-block", MODS_SERVICE)
    # Kein "gestartet"-Hinweis mehr – die Live-Statusanzeige übernimmt das.
    # Nur einen echten Startfehler (sudo/systemctl) melden, den die Anzeige nicht zeigt.
    if rc != 0:
        flash(t("mods_sync_failed", out=out))
    return redirect(url_for("mods_page"))


@app.route("/mods/sync-status")
@login_required
def mods_sync_status():
    logs = recent_logs(MODS_SERVICE, 80)
    return jsonify(state=service_active(MODS_SERVICE),
                   progress=parse_sync_progress(logs),
                   logs=logs)


def parse_sync_progress(logs):
    """Zieht den aktuellen Fortschritt aus den Log-Zeilen des Sync-Skripts.
    Gibt einen kurzen, menschenlesbaren Text zurück (oder '')."""
    import re
    cur = pos = total = None
    done = False
    last_action = ""
    for line in logs.splitlines():
        m = re.search(r"Fortschritt: Mod (\d+)/(\d+) \((\d+)\)", line)
        if m:
            pos, total, cur = m.group(1), m.group(2), m.group(3)
            last_action = "download"
            continue
        if "Entpacke Mod" in line:
            last_action = "extract"
        elif "installiert." in line and "Mod" in line:
            last_action = "installed"
        elif "Bilanz:" in line:
            done = True
            mb = re.search(r"Bilanz: (\d+)/(\d+)", line)
            if mb:
                pos, total = mb.group(1), mb.group(2)
    if done and total:
        return t("mods_progress_done", ok=pos, total=total)
    if pos and total:
        phase = {
            "download": t("mods_phase_download"),
            "extract": t("mods_phase_extract"),
            "installed": t("mods_phase_installed"),
        }.get(last_action, t("mods_phase_download"))
        return t("mods_progress_running", pos=pos, total=total, mod=cur or "", phase=phase)
    return ""


@app.route("/mods/add", methods=["POST"])
@login_required
def mods_add():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("mods_page"))
    mod_id = request.form.get("mod_id", "").strip()
    name = request.form.get("name", "").strip()
    if not MOD_ID_RE.match(mod_id):
        flash(t("mod_id_invalid"))
    else:
        with _state_lock:
            rt = load_runtime()
            if mod_id in rt["mods"]:
                flash(t("mod_exists"))
                return redirect(url_for("mods_page"))
            rt["mods"].append(mod_id)
            save_runtime(rt)
            if name:
                labels = load_mod_labels()
                labels[mod_id] = name
                save_mod_labels(labels)
        flash(t("mod_added", id=mod_id))
    return redirect(url_for("mods_page"))


@app.route("/mods/remove", methods=["POST"])
@login_required
def mods_remove():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("mods_page"))
    mod_id = request.form.get("mod_id", "")
    with _state_lock:
        rt = load_runtime()
        if mod_id not in rt["mods"]:
            flash(t("mod_not_found"))
        else:
            rt["mods"] = [m for m in rt["mods"] if m != mod_id]
            save_runtime(rt)
            flash(t("mod_removed"))
    return redirect(url_for("mods_page"))


@app.route("/mods/move", methods=["POST"])
@login_required
def mods_move():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("mods_page"))
    mod_id = request.form.get("mod_id", "")
    direction = request.form.get("dir", "")
    with _state_lock:
        rt = load_runtime()
        mods = rt["mods"]
        if mod_id in mods:
            i = mods.index(mod_id)
            j = i - 1 if direction == "up" else i + 1
            if 0 <= j < len(mods):
                mods[i], mods[j] = mods[j], mods[i]
                rt["mods"] = mods
                save_runtime(rt)
    return redirect(url_for("mods_page"))


# ---------------------------------------------------------------------------
# Routen: Konfiguration (GameUserSettings.ini / Game.ini)
# ---------------------------------------------------------------------------
def _current_file_key():
    key = request.args.get("file") or request.form.get("file") or "gus"
    return key if key in INI_FILES else "gus"


# Diese Keys steuert das Panel selbst (Startzeile bzw. ark-launch.sh) – im
# Feld-Editor ausblenden. ActiveMods schreibt ark-launch.sh bei jedem Start neu.
HIDDEN_KEYS = {"RCONPort", "RCONEnabled", "SessionName", "Port", "QueryPort", "ActiveMods"}


def strip_wrap(v):
    """Umschließende Klammern (…) oder Anführungszeichen "…" für die Anzeige
    entfernen. Der Wert bleibt editierbar; beim Speichern wird die Umrandung
    per rewrap wieder ergänzt."""
    if len(v) >= 2 and v[0] == "(" and v[-1] == ")":
        return v[1:-1]
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1]
    return v


def rewrap(orig, new):
    """Beim Speichern die Umrandung des Originalwerts wieder anwenden. Falls der
    Nutzer die Klammern/Quotes selbst mit eingegeben hat, werden sie nicht doppelt
    gesetzt."""
    if len(orig) >= 2 and orig[0] == "(" and orig[-1] == ")":
        inner = new[1:-1] if len(new) >= 2 and new[0] == "(" and new[-1] == ")" else new
        return "(" + inner + ")"
    if len(orig) >= 2 and orig[0] == '"' and orig[-1] == '"':
        inner = new[1:-1] if len(new) >= 2 and new[0] == '"' and new[-1] == '"' else new
        return '"' + inner + '"'
    return new


def display_groups(entries):
    """Sektionen fürs Template: panel-verwaltete Keys ausblenden, sonst alle Felder
    zeigen – aber mit „nacktem" Anzeigewert (ohne umschließende ()/"")."""
    groups = []
    for g in group_ini(entries):
        fields = []
        for f in g["fields"]:
            if f["key"] in HIDDEN_KEYS:
                continue
            f = dict(f)
            f["display"] = strip_wrap(f["value"])
            fields.append(f)
        if fields:
            groups.append({"name": g["name"], "fields": fields})
    return groups


def enforce_rcon(key):
    """RCON ist fürs Panel Pflicht: RCONEnabled immer True, RCONPort auf den
    Port aus runtime.json festnageln (auch nach einem Rohtext-Speichern)."""
    if key != "gus":
        return
    ini_set(GUS_PATH, "ServerSettings", "RCONEnabled", "True")
    ini_set(GUS_PATH, "ServerSettings", "RCONPort", str(load_runtime()["rcon_port"]))


@app.route("/config", methods=["GET"])
@login_required
def config():
    key = _current_file_key()
    raw, entries = read_ini(key)
    return render_template("config.html",
                           file_key=key, files=INI_LABELS,
                           groups=display_groups(entries), raw=raw,
                           exists=os.path.exists(INI_FILES[key]),
                           ini_path=INI_FILES[key])


@app.route("/config/save", methods=["POST"])
@login_required
def config_save():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("config"))
    key = _current_file_key()
    _raw, entries = read_ini(key)
    edits = {}
    for e in entries:
        if e["type"] == "kv":
            field = "field_" + e["id"]
            if field in request.form:
                # angezeigt wurde der Wert ohne umschließende ()/"" – hier wieder ergänzen
                edits[e["id"]] = rewrap(e["value"], request.form.get(field, ""))
    try:
        write_ini(key, apply_ini(entries, edits))
        enforce_rcon(key)
    except OSError as e:
        flash(t("config_write_error", err=str(e)))
        return redirect(url_for("config", file=key))
    flash(t("config_saved"))
    return redirect(url_for("config", file=key))


@app.route("/config/save-raw", methods=["POST"])
@login_required
def config_save_raw():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("config"))
    key = _current_file_key()
    try:
        write_ini(key, request.form.get("raw", ""))
        enforce_rcon(key)
    except OSError as e:
        flash(t("config_write_error", err=str(e)))
        return redirect(url_for("config", file=key))
    flash(t("raw_saved"))
    return redirect(url_for("config", file=key))


# ---------------------------------------------------------------------------
# Routen: Spieler / RCON
# ---------------------------------------------------------------------------
@app.route("/players")
@login_required
def players():
    enabled, _port, _pw = rcon_config()
    if not enabled:
        return jsonify(enabled=False, reachable=False, players=[],
                       note="Kein ServerAdminPassword gesetzt (unter „Übersicht“ RCON einrichten).")
    if service_active(SERVICE) != "active":
        return jsonify(enabled=True, reachable=False, players=[], note="Server läuft nicht.")
    try:
        with rcon_connect() as r:
            return jsonify(enabled=True, reachable=True, players=r.players())
    except (RCONError, OSError) as e:
        # Server-Prozess läuft, aber RCON nimmt noch keine Verbindung an – das ist
        # beim Hochfahren/Weltladen normal (Port noch zu). Freundlicher Hinweis statt
        # rohem "[Errno 111] Connection refused".
        refused = isinstance(e, ConnectionRefusedError) or "refused" in str(e).lower() \
            or "reset" in str(e).lower() or "timed out" in str(e).lower()
        note = t("rcon_starting") if refused else str(e)
        return jsonify(enabled=True, reachable=False, players=[], note=note)


@app.route("/rcon", methods=["POST"])
@login_required
def rcon_action():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("dashboard"))
    act = request.form.get("act")

    # "Speichern & Stoppen" gesondert behandeln: Welt speichern ist best-effort
    # (RCON kann bei einem hängenden/abstürzenden Server tot sein), aber der
    # Service muss in JEDEM Fall sauber gestoppt werden. systemctl disable --now
    # stoppt den Dienst manuell -> die Restart=on-failure-Policy greift dabei
    # nicht, sonst würde der Server sofort neu starten ("geht nicht aus").
    if act == "save_shutdown":
        saved = False
        try:
            with rcon_connect() as r:
                r.save()
                saved = True
        except (RCONError, OSError):
            saved = False
        if not stop_service():
            flash(t("srv_stop_failed"))
        elif saved:
            flash(t("save_shutdown_done"))
        else:
            flash(t("shutdown_nosave"))
        return redirect(url_for("dashboard"))

    try:
        with rcon_connect() as r:
            if act == "save":
                flash(t("world_saved", res=(r.save() or "OK")))
            elif act == "broadcast":
                msg = request.form.get("message", "").strip()
                if not msg:
                    flash(t("no_message"))
                else:
                    r.broadcast(msg)
                    flash(t("broadcast_sent"))
            else:
                flash(t("unknown_rcon"))
    except (RCONError, OSError) as e:
        flash(t("rcon_failed", err=str(e)))
    return redirect(url_for("dashboard"))


@app.route("/rcon/player", methods=["POST"])
@login_required
def rcon_player():
    if not check_csrf():
        return jsonify(ok=False, msg=t("csrf_invalid"))
    act = request.form.get("act")
    ident = (request.form.get("steamid") or "").strip()
    if not ident:
        return jsonify(ok=False, msg=t("no_steamid"))
    if act not in ("kick", "ban"):
        return jsonify(ok=False, msg=t("unknown_rcon"))
    try:
        with rcon_connect() as r:
            if act == "kick":
                r.kick(ident)
                return jsonify(ok=True, msg=t("player_kicked"))
            r.ban(ident)
            return jsonify(ok=True, msg=t("player_banned"))
    except (RCONError, OSError) as e:
        return jsonify(ok=False, msg=t("rcon_failed", err=str(e)))


@app.route("/rcon/setup", methods=["POST"])
@login_required
def rcon_setup():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("dashboard"))
    generated = ensure_rcon_configured()
    flash(t("rcon_enabled_gen", pw=generated) if generated else t("rcon_enabled_existing"))
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Geplante Neustarts (im Panel einstellbar)
#
# Ein Hintergrund-Thread im Panel-Prozess (waitress = ein Prozess) prüft alle
# 20 s den Zeitplan aus schedule.json. Zum Termin: Countdown-Warnungen per RCON-
# Broadcast, SaveWorld, dann `systemctl restart ark.service` über die vorhandene
# sudo-Regel. Optional vorher Spiel-Update (ark-update.service, SteamCMD) und
# Mod-Sync (ark-mods.service) – ARK: SE aktualisiert beides NICHT von selbst.
# ---------------------------------------------------------------------------
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    try:
        SCHED_TZ = ZoneInfo(CONF.get("tz") or "Europe/Berlin")
    except Exception:
        SCHED_TZ = None
except ImportError:      # Python < 3.9
    SCHED_TZ = None

SCHEDULE_PATH = CONF.get("schedule_path", os.path.join(PANEL_DIR, "schedule.json"))
SCHEDULE_DEFAULTS = {
    "enabled": False,
    "times": ["05:00"],
    "days": [0, 1, 2, 3, 4, 5, 6],          # 0 = Montag … 6 = Sonntag
    "warn_minutes": [15, 10, 5, 1],
    "message": "Server-Neustart in {min} Minute(n) – bitte in Sicherheit bringen!",
    "save_first": True,
    "skip_if_stopped": True,
    "skip_if_players": False,
    "update_first": False,      # vorher SteamCMD-Update (ark-update.service)
    "sync_mods": False,         # vorher Workshop-Mods synchronisieren (ark-mods.service)
    # Status (vom Scheduler gepflegt)
    "last_slot": "",
    "last_run": "",
    "last_result": "",
}
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
SCHED_GRACE = timedelta(minutes=5)   # verpasster Termin (z. B. Panel-Neustart) wird bis 5 min danach nachgeholt
_sched_lock = threading.Lock()
_job = {"thread": None, "cancel": threading.Event(), "target": None, "label": ""}


def sched_now():
    return datetime.now(SCHED_TZ) if SCHED_TZ else datetime.now().astimezone()


def load_schedule():
    data = _load_json(SCHEDULE_PATH, SCHEDULE_DEFAULTS)
    s = dict(SCHEDULE_DEFAULTS)
    s.update({k: data.get(k, v) for k, v in SCHEDULE_DEFAULTS.items()})
    s["times"] = sorted({x for x in s.get("times", []) if TIME_RE.match(str(x))},
                        key=lambda x: tuple(int(p) for p in x.split(":")))
    s["times"] = ["%02d:%02d" % tuple(int(p) for p in x.split(":")) for x in s["times"]]
    s["days"] = sorted({int(d) for d in s.get("days", []) if str(d).isdigit() and 0 <= int(d) <= 6})
    s["warn_minutes"] = sorted({int(w) for w in s.get("warn_minutes", [])
                                if str(w).isdigit() and 1 <= int(w) <= 60}, reverse=True)
    return s


def save_schedule(s):
    _save_json(SCHEDULE_PATH, s)


def _sched_update(**kw):
    with _sched_lock:
        s = load_schedule()
        s.update(kw)
        save_schedule(s)


def _occurrences(s, now):
    """Neustart-Termine von gestern bis übermorgen (für Fenster über Mitternacht)."""
    out = []
    for offset in (-1, 0, 1, 2):
        day = (now + timedelta(days=offset)).date()
        if day.weekday() not in s["days"]:
            continue
        for hm in s["times"]:
            h, m = (int(p) for p in hm.split(":"))
            dt = datetime(day.year, day.month, day.day, h, m, tzinfo=now.tzinfo)
            out.append(dt)
    return sorted(out)


def next_restart(s=None):
    s = s or load_schedule()
    if not s["enabled"] or not s["times"] or not s["days"]:
        return None
    now = sched_now()
    for dt in _occurrences(s, now):
        if dt > now:
            return dt
    return None


def _broadcast(msg):
    try:
        with rcon_connect() as r:
            r.broadcast(msg)
        return True
    except (RCONError, OSError):
        return False


def _players_online():
    try:
        with rcon_connect() as r:
            return len(r.players())
    except (RCONError, OSError):
        return 0


def _sync_mods_blocking(max_wait=3600):
    """Mod-Sync anstoßen und auf das Ende warten. Gibt eine Liste von Hinweisen zurück."""
    rc, out = svc("start", "--no-block", MODS_SERVICE)
    if rc != 0:
        return ["mods: " + (out or "rc=%d" % rc)]
    time.sleep(3)
    waited = 3
    while service_active(MODS_SERVICE) in ("active", "activating") and waited < max_wait:
        time.sleep(5)
        waited += 5
    if waited >= max_wait:
        return ["mods: timeout"]
    last = read_last_sync() or {}
    if last.get("failed"):
        return ["mods failed: " + ", ".join(str(x) for x in last["failed"])]
    return []


def _restart_job(target, slot, s):
    """Countdown + Neustart. Läuft in eigenem Thread; abbrechbar über _job['cancel']."""
    cancel = _job["cancel"]
    stamp = lambda: sched_now().strftime("%d.%m.%Y %H:%M")
    try:
        if s["skip_if_stopped"] and service_active(SERVICE) != "active":
            _sched_update(last_run=stamp(), last_result="skipped_stopped")
            return
        if s["skip_if_players"] and _players_online() > 0:
            _sched_update(last_run=stamp(), last_result="skipped_players")
            return
        # Warnungen (nur die, deren Zeitpunkt noch nicht vorbei ist)
        for w in s["warn_minutes"]:
            at = target - timedelta(minutes=w)
            if at < sched_now() - timedelta(seconds=30):
                continue
            while sched_now() < at:
                if cancel.wait(1):
                    break
            if cancel.is_set():
                break
            try:
                text = s["message"].format(min=w)
            except (KeyError, IndexError, ValueError):
                text = s["message"]
            _broadcast(text)
        while not cancel.is_set() and sched_now() < target:
            cancel.wait(1)
        if cancel.is_set():
            _broadcast("Server-Neustart abgebrochen.")
            _sched_update(last_run=stamp(), last_result="cancelled")
            return

        if s["save_first"]:
            try:
                with rcon_connect() as r:
                    r.save()
                time.sleep(5)          # SaveWorld schreibt asynchron
            except (RCONError, OSError):
                pass
        do_mods = s["sync_mods"] and bool(load_runtime()["mods"])
        if s["update_first"] or do_mods:
            # Server stoppen, Update/Mod-Sync laufen lassen, danach wieder starten.
            # (ark-update.service stoppt ark.service zusätzlich selbst per ExecStartPre.)
            warns = []
            svc("disable", "--now", SERVICE)
            svc("reset-failed", SERVICE)
            if s["update_first"]:
                rc, out = run(["sudo", "-n", "systemctl", "start", UPDATE_SERVICE], timeout=7500)
                if rc != 0:
                    warns.append("update: " + (out or "rc=%d" % rc))
            if do_mods:
                warns += _sync_mods_blocking()
            rc2, out2 = run(["sudo", "-n", "systemctl", "enable", "--now", SERVICE], timeout=300)
            ok = rc2 == 0
            err = out2 if not ok else "; ".join(warns)
        else:
            svc("enable", SERVICE)
            rc, out = run(["sudo", "-n", "systemctl", "restart", SERVICE], timeout=300)
            ok, err = rc == 0, out
        _sched_update(last_run=stamp(),
                      last_result="ok" if ok and not err else ("ok_warn:" + err[:200] if ok else "error:" + err[:200]))
    finally:
        with _sched_lock:
            _job.update(thread=None, target=None, label="")


def start_restart_job(target, slot, s, label):
    """Startet einen Neustart-Job, falls keiner läuft. Gibt True bei Erfolg zurück."""
    with _sched_lock:
        if _job["thread"] is not None:
            return False
        _job["cancel"] = threading.Event()
        th = threading.Thread(target=_restart_job, args=(target, slot, s),
                              name="ark-restart-job", daemon=True)
        _job.update(thread=th, target=target, label=label)
        th.start()
    return True


def _scheduler_loop():
    while True:
        try:
            s = load_schedule()
            if s["enabled"] and s["times"] and s["days"] and _job["thread"] is None:
                now = sched_now()
                lead = timedelta(minutes=max(s["warn_minutes"] or [0]))
                for dt in _occurrences(s, now):
                    slot = dt.strftime("%Y-%m-%d %H:%M")
                    if slot == s["last_slot"]:
                        continue
                    if dt - lead <= now <= dt + SCHED_GRACE:
                        _sched_update(last_slot=slot)
                        start_restart_job(dt, slot, s, "schedule")
                        break
        except Exception as e:      # Scheduler darf nie sterben
            print("scheduler error:", e, flush=True)
        time.sleep(20)


_scheduler_started = False


def start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    threading.Thread(target=_scheduler_loop, name="ark-scheduler", daemon=True).start()


WEEKDAYS = [("mon", 0), ("tue", 1), ("wed", 2), ("thu", 3), ("fri", 4), ("sat", 5), ("sun", 6)]


def _result_text(code):
    if not code:
        return ""
    if code.startswith("error:"):
        return t("sched_res_error", err=code[6:])
    if code.startswith("ok_warn:"):
        return t("sched_res_ok_warn", err=code[8:])
    return t("sched_res_" + code)


@app.route("/schedule")
@login_required
def schedule_page():
    s = load_schedule()
    nxt = next_restart(s)
    job_target = _job["target"]
    return render_template(
        "schedule.html", s=s, weekdays=WEEKDAYS,
        next_restart=(t("wd_" + WEEKDAYS[nxt.weekday()][0]) + nxt.strftime(" %d.%m.%Y %H:%M")) if nxt else "",
        job_active=job_target is not None,
        job_target=job_target.strftime("%H:%M:%S") if job_target else "",
        job_label=_job["label"],
        last_result=_result_text(s["last_result"]),
        tz_name=str(SCHED_TZ) if SCHED_TZ else time.strftime("%Z"),
        now=sched_now().strftime("%H:%M"),
    )


@app.route("/schedule/save", methods=["POST"])
@login_required
def schedule_save():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("schedule_page"))
    raw_times = [x.strip() for x in re.split(r"[,;\s]+", request.form.get("times", "")) if x.strip()]
    bad = [x for x in raw_times if not TIME_RE.match(x)]
    if bad:
        flash(t("sched_bad_time", val=", ".join(bad)))
        return redirect(url_for("schedule_page"))
    if len(raw_times) > 12:
        flash(t("sched_too_many"))
        return redirect(url_for("schedule_page"))
    raw_warn = [x.strip() for x in re.split(r"[,;\s]+", request.form.get("warn_minutes", "")) if x.strip()]
    if any(not x.isdigit() or not 1 <= int(x) <= 60 for x in raw_warn):
        flash(t("sched_bad_warn"))
        return redirect(url_for("schedule_page"))
    days = [int(d) for d in request.form.getlist("days") if d.isdigit() and 0 <= int(d) <= 6]
    message = request.form.get("message", "").replace("\r", " ").replace("\n", " ").strip()[:200]
    enabled = bool(request.form.get("enabled"))
    if enabled and (not raw_times or not days):
        flash(t("sched_need_time_day"))
        return redirect(url_for("schedule_page"))
    with _sched_lock:
        s = load_schedule()
        s.update({
            "enabled": enabled,
            "times": raw_times,
            "days": days,
            "warn_minutes": [int(x) for x in raw_warn],
            "message": message or SCHEDULE_DEFAULTS["message"],
            "save_first": bool(request.form.get("save_first")),
            "skip_if_stopped": bool(request.form.get("skip_if_stopped")),
            "skip_if_players": bool(request.form.get("skip_if_players")),
            "update_first": bool(request.form.get("update_first")),
            "sync_mods": bool(request.form.get("sync_mods")),
        })
        # Ein Termin, der gerade erst vorbei ist (Nachhol-Fenster), soll durch das
        # Speichern nicht sofort einen Neustart auslösen -> als erledigt markieren.
        now = sched_now()
        for dt in _occurrences(s, now):
            if dt <= now <= dt + SCHED_GRACE:
                s["last_slot"] = dt.strftime("%Y-%m-%d %H:%M")
        save_schedule(s)
    flash(t("sched_saved"))
    return redirect(url_for("schedule_page"))


@app.route("/schedule/now", methods=["POST"])
@login_required
def schedule_now():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("schedule_page"))
    try:
        minutes = max(0, min(60, int(request.form.get("minutes", "0"))))
    except ValueError:
        minutes = 0
    s = load_schedule()
    # Warnungen nur, soweit sie in den gewählten Countdown passen
    s["warn_minutes"] = [w for w in s["warn_minutes"] if w <= minutes]
    s["skip_if_players"] = False        # manuell ausgelöst = gewollt
    target = sched_now() + timedelta(minutes=minutes, seconds=2)
    if start_restart_job(target, "manual", s, "manual"):
        flash(t("sched_now_started", min=minutes))
    else:
        flash(t("sched_job_running"))
    return redirect(url_for("schedule_page"))


@app.route("/schedule/cancel", methods=["POST"])
@login_required
def schedule_cancel():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("schedule_page"))
    if _job["thread"] is not None:
        _job["cancel"].set()
        flash(t("sched_cancelled"))
    else:
        flash(t("sched_no_job"))
    return redirect(url_for("schedule_page"))


start_scheduler()


# ---------------------------------------------------------------------------
# Transfer: Settings + Mods von Server A nach Server B übernehmen
#
# Jedes Panel steuert genau einen Server. Übertragen wird ein JSON-Paket mit
# GameUserSettings.ini, Game.ini, Mods (Reihenfolge + Namen), eigenen Karten,
# aktiver Karte und Startoptionen. Zwei Wege:
#   1) Export als Datei auf A herunterladen -> auf B hochladen
#   2) B holt das Paket direkt von A (A gibt dafür ein Transfer-Token frei)
# Ports, RCONEnabled/RCONPort und SessionName bleiben IMMER lokal (B behält seine
# Werte). Passwörter (ServerAdminPassword + Beitrittspasswort) werden mit
# übertragen, wenn der Teil „Passwörter“ gewählt ist (Standard). Lokale Keys
# werden an Ort und Stelle ersetzt – die Reihenfolge der INI bleibt wie auf A.
# Vor jedem Import wird ein Backup angelegt, das sich mit einem Klick
# wiederherstellen lässt.
# ---------------------------------------------------------------------------
TRANSFER_FORMAT = "ark-panel-transfer"
TRANSFER_VERSION = 1
TRANSFER_PATH = CONF.get("transfer_path", os.path.join(PANEL_DIR, "transfer.json"))
TRANSFER_BACKUP_DIR = os.path.join(PANEL_DIR, "transfer-backups")
TRANSFER_MAX_BYTES = 8 * 1024 * 1024
TRANSFER_KEEP_BACKUPS = 10
# HIDDEN_KEYS (Ports/RCON/Name) gehören immer dem Zielserver. Die Passwort-Keys
# nur dann, wenn der Teil „secrets“ NICHT gewählt ist.
TRANSFER_SECRET_KEYS = {"ServerAdminPassword", "ServerPassword"}
TRANSFER_PARTS = ("gus", "game", "mods", "maps", "launch", "session", "secrets")
TRANSFER_DEFAULT_PARTS = {"gus", "game", "mods", "maps", "launch", "secrets"}

app.config["MAX_CONTENT_LENGTH"] = TRANSFER_MAX_BYTES


def load_transfer_token():
    return _load_json(TRANSFER_PATH, {"token": ""}).get("token", "") or ""


def save_transfer_token(tok):
    _save_json(TRANSFER_PATH, {"token": tok})


def _ini_local_values(text, keys):
    """[(section, key, value)] der lokalen Werte für die geschützten Keys."""
    vals, sec = [], ""
    for e in parse_ini(text):
        if e["type"] == "section":
            sec = e["name"]
        elif e["type"] == "kv" and e["key"] in keys:
            vals.append((sec, e["key"], e["value"]))
    return vals


def _ini_value(text, section, key):
    """Ersten Wert von key in section aus einem INI-Text lesen (oder None)."""
    for sec, k, v in _ini_local_values(text or "", {key}):
        if sec == section:
            return v.split("?", 1)[0].strip() if key == "ServerAdminPassword" else v
    return None


def build_transfer_bundle():
    rt = load_runtime()
    ini = {}
    for key in ("gus", "game"):
        raw, _entries = read_ini(key)
        ini[key] = raw or ""
    labels = load_mod_labels()
    return {
        "format": TRANSFER_FORMAT,
        "version": TRANSFER_VERSION,
        "panel_version": PANEL_VERSION,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": rt.get("session_name", ""),
        "ini": ini,
        "runtime": {
            "map": rt.get("map"),
            "session_name": rt.get("session_name", ""),
            "max_players": rt.get("max_players", 70),
            "battleye": bool(rt.get("battleye", True)),
            "extra_args": rt.get("extra_args", ""),
            "server_password": rt.get("server_password", ""),
            "mods": list(rt.get("mods", [])),
        },
        "mod_labels": {m: labels[m] for m in rt.get("mods", []) if m in labels},
        "custom_maps": load_custom_maps(),
    }


def validate_transfer_bundle(data):
    """Prüft/normalisiert ein Paket. Gibt (bundle, None) oder (None, fehler) zurück."""
    if not isinstance(data, dict) or data.get("format") != TRANSFER_FORMAT:
        return None, t("xfer_bad_format")
    if int(data.get("version", 0) or 0) > TRANSFER_VERSION:
        return None, t("xfer_bad_version")
    ini = data.get("ini") or {}
    rt = data.get("runtime") or {}
    if not isinstance(ini, dict) or not isinstance(rt, dict):
        return None, t("xfer_bad_format")
    out = {"source": str(data.get("source", ""))[:100],
           "created": str(data.get("created", ""))[:40],
           "ini": {}, "runtime": {}}
    for key in ("gus", "game"):
        v = ini.get(key, "")
        out["ini"][key] = v if isinstance(v, str) else ""
    mods = [str(m) for m in rt.get("mods", []) if MOD_ID_RE.match(str(m))]
    out["runtime"]["mods"] = list(dict.fromkeys(mods))          # Duplikate raus, Reihenfolge bleibt
    mp = str(rt.get("map", "") or "")
    out["runtime"]["map"] = mp if MAP_CODE_RE.match(mp) else ""
    try:
        out["runtime"]["max_players"] = max(1, min(500, int(rt.get("max_players", 70))))
    except (TypeError, ValueError):
        out["runtime"]["max_players"] = 70
    out["runtime"]["battleye"] = bool(rt.get("battleye", True))
    out["runtime"]["extra_args"] = str(rt.get("extra_args", "") or "").replace("\n", " ").replace("\r", " ").strip()
    sp = rt.get("server_password")             # fehlt bei Paketen älterer Panels
    out["runtime"]["server_password"] = None if sp is None else \
        str(sp).replace("?", "").replace(" ", "").replace("\n", "").replace("\r", "")[:100]
    sn = str(rt.get("session_name", "") or "")
    out["runtime"]["session_name"] = sn.replace("?", "").replace("\n", "").replace("\r", "").strip()[:100]
    labels = data.get("mod_labels") or {}
    out["mod_labels"] = {str(k): str(v)[:100] for k, v in labels.items()
                         if MOD_ID_RE.match(str(k))} if isinstance(labels, dict) else {}
    maps = []
    for m in data.get("custom_maps") or []:
        if not isinstance(m, dict):
            continue
        code = str(m.get("code", ""))
        mod_id = str(m.get("mod_id", "") or "")
        if not MAP_CODE_RE.match(code) or code in OFFICIAL_CODES:
            continue
        if mod_id and not MOD_ID_RE.match(mod_id):
            mod_id = ""
        maps.append({"code": code, "name": str(m.get("name", code))[:100] or code, "mod_id": mod_id})
    out["custom_maps"] = maps
    return out, None


def _transfer_backup(prune=True):
    """Aktuellen Stand (INIs + Panel-Stores) sichern. Gibt den Backup-Namen zurück."""
    import shutil
    name = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(TRANSFER_BACKUP_DIR, name)
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(TRANSFER_BACKUP_DIR, "%s-%d" % (name, n))
    os.makedirs(dest, mode=0o700)
    files = {"GameUserSettings.ini": INI_FILES["gus"], "Game.ini": INI_FILES["game"],
             "runtime.json": RUNTIME_PATH, "mods.json": MODS_PATH, "maps.json": MAPS_PATH}
    manifest = {}
    for label, src in files.items():
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dest, label))
            manifest[label] = True
        else:
            manifest[label] = False
    _save_json(os.path.join(dest, "manifest.json"), manifest)
    # alte Backups aufräumen
    if not prune:
        return os.path.basename(dest)
    try:
        dirs = sorted(d for d in os.listdir(TRANSFER_BACKUP_DIR)
                      if os.path.isdir(os.path.join(TRANSFER_BACKUP_DIR, d)))
        for d in dirs[:-TRANSFER_KEEP_BACKUPS]:
            shutil.rmtree(os.path.join(TRANSFER_BACKUP_DIR, d), ignore_errors=True)
    except OSError:
        pass
    return os.path.basename(dest)


def list_transfer_backups():
    try:
        return sorted((d for d in os.listdir(TRANSFER_BACKUP_DIR)
                       if os.path.isdir(os.path.join(TRANSFER_BACKUP_DIR, d))), reverse=True)
    except OSError:
        return []


def _import_ini(key, text, with_secrets=True):
    """Fremde INI 1:1 übernehmen. Lokal bleiben nur Ports/RCON/Sessionname
    (HIDDEN_KEYS) und – ohne with_secrets – die Passwörter. Diese Keys werden
    an ihrer Stelle in der fremden Datei ersetzt (Reihenfolge bleibt wie auf A),
    doppelte Vorkommen entfernt; fehlt ein lokaler Key dort, kommt er ans Ende
    seiner Section."""
    local_raw, _ = read_ini(key)
    incoming = [(sec, k) for sec, k, _v in _ini_local_values(text, TRANSFER_SECRET_KEYS)]
    keep = set(HIDDEN_KEYS)
    for k in TRANSFER_SECRET_KEYS:
        # Ohne Passwort-Teil, oder Paket enthält den Key nicht (älteres Panel): lokal behalten
        if not with_secrets or not any(ik == k for _s, ik in incoming):
            keep.add(k)
    local = {}
    for sec, k, v in _ini_local_values(local_raw, keep):
        local.setdefault((sec, k), v)            # erstes Vorkommen gilt

    out, sec, placed = [], "", set()
    sec_last = {}                                # Section -> Index der letzten Nicht-Leerzeile
    for e in parse_ini(text):
        if e["type"] == "section":
            sec = e["name"]
            out.append(e["raw"])
            sec_last[sec] = len(out) - 1
            continue
        if e["type"] == "kv" and e["key"] in keep:
            ident = (sec, e["key"])
            if ident in local and ident not in placed:
                out.append("%s=%s" % (e["key"], local[ident]))   # an Ort und Stelle
                placed.add(ident)
                sec_last[sec] = len(out) - 1
            continue                             # Duplikat bzw. lokal nicht vorhanden -> weg
        out.append(e["raw"])
        if e["raw"].strip():
            sec_last[sec] = len(out) - 1

    # Lokale Keys, die im Paket fehlen, ans Ende ihrer Section
    missing = {}
    for ident, v in local.items():
        if ident not in placed:
            missing.setdefault(ident[0], []).append("%s=%s" % (ident[1], v))
    for sname in sorted((n for n in missing if n in sec_last), key=lambda n: -sec_last[n]):
        i = sec_last[sname] + 1
        out[i:i] = missing.pop(sname)
    while out and out[-1].strip() == "":
        out.pop()
    for sname, kv in missing.items():            # Section fehlt im Paket -> anhängen
        if sname:
            out += ["", "[%s]" % sname]
        out += kv
    write_ini(key, "\n".join(out) + "\n")
    enforce_rcon(key)


def apply_transfer_bundle(b, parts, mods_merge=False):
    """Paket anwenden. Gibt (liste_der_übernommenen_teile, hinweise) zurück."""
    done, notes = [], []
    with _state_lock:
        with_secrets = "secrets" in parts
        for key in ("gus", "game"):
            if key in parts:
                if b["ini"].get(key, "").strip():
                    _import_ini(key, b["ini"][key], with_secrets)
                    done.append(INI_LABELS[key])
                else:
                    notes.append(t("xfer_note_empty_ini", file=INI_LABELS[key]))
        rt = load_runtime()
        if "maps" in parts:
            local = {m["code"]: m for m in load_custom_maps()}
            for m in b["custom_maps"]:
                local[m["code"]] = m
            save_custom_maps(list(local.values()))
            done.append(t("xfer_part_maps"))
        if "mods" in parts:
            if mods_merge:
                rt["mods"] = rt["mods"] + [m for m in b["runtime"]["mods"] if m not in rt["mods"]]
            else:
                rt["mods"] = list(b["runtime"]["mods"])
            labels = load_mod_labels()
            labels.update(b["mod_labels"])
            save_mod_labels(labels)
            done.append(t("xfer_part_mods_n", n=len(b["runtime"]["mods"])))
            if rt["mods"]:
                notes.append(t("xfer_note_sync_mods"))
        if "maps" in parts and b["runtime"]["map"]:
            known = {m["code"] for m in all_maps()}
            if b["runtime"]["map"] in known:
                rt["map"] = b["runtime"]["map"]
            else:
                notes.append(t("xfer_note_map_unknown", code=b["runtime"]["map"]))
        if "launch" in parts:
            rt["max_players"] = b["runtime"]["max_players"]
            rt["battleye"] = b["runtime"]["battleye"]
            rt["extra_args"] = b["runtime"]["extra_args"]
            done.append(t("xfer_part_launch"))
        if with_secrets:
            # Beitrittspasswort: Quelle ist runtime.json (ark-launch.sh übergibt es
            # bei jedem Start in die INI) – sonst wäre es nach dem Neustart wieder leer.
            sp = b["runtime"].get("server_password")
            if sp is None:                       # älteres Paket: aus der INI nehmen
                sp = _ini_value(b["ini"].get("gus", ""), "ServerSettings", "ServerPassword")
            if sp is not None:
                rt["server_password"] = sp
            if "gus" not in parts:               # Admin-Passwort auch ohne GUS-Import
                apw = _ini_value(b["ini"].get("gus", ""), "ServerSettings", "ServerAdminPassword")
                if apw:
                    ini_set(GUS_PATH, "ServerSettings", "ServerAdminPassword", apw)
            if sp is not None or _ini_value(b["ini"].get("gus", ""), "ServerSettings", "ServerAdminPassword"):
                done.append(t("xfer_part_secrets"))
            else:
                notes.append(t("xfer_note_no_secrets"))
        if "session" in parts and b["runtime"]["session_name"]:
            rt["session_name"] = b["runtime"]["session_name"]
            done.append(t("xfer_part_session"))
        save_runtime(rt)
    return done, notes


def _transfer_parts_from_form():
    return {p for p in TRANSFER_PARTS if request.form.get("part_" + p)}


def _run_import(data):
    """Gemeinsamer Ablauf für Datei-Upload und Direktabruf."""
    b, err = validate_transfer_bundle(data)
    if err:
        flash(err)
        return redirect(url_for("transfer_page"))
    parts = _transfer_parts_from_form()
    if not parts:
        flash(t("xfer_no_parts"))
        return redirect(url_for("transfer_page"))
    # ARK schreibt die GameUserSettings.ini beim Beenden zurück -> nur bei gestopptem Server
    if parts & {"gus", "game"} and service_active(SERVICE) == "active":
        flash(t("xfer_stop_first"))
        return redirect(url_for("transfer_page"))
    try:
        bk = _transfer_backup()
        done, notes = apply_transfer_bundle(b, parts, mods_merge=bool(request.form.get("mods_merge")))
    except OSError as e:
        flash(t("xfer_error", err=str(e)))
        return redirect(url_for("transfer_page"))
    flash(t("xfer_done", src=b["source"] or "?", parts=", ".join(done) or "–", backup=bk))
    for n in notes:
        flash(n)
    return redirect(url_for("transfer_page"))


@app.route("/transfer")
@login_required
def transfer_page():
    rt = load_runtime()
    return render_template("transfer.html",
                           token=load_transfer_token(),
                           backups=list_transfer_backups(),
                           running=(service_active(SERVICE) == "active"),
                           defaults=TRANSFER_DEFAULT_PARTS,
                           mods_count=len(rt["mods"]),
                           maps_count=len(load_custom_maps()),
                           self_url=request.host_url.rstrip("/"))


@app.route("/transfer/download")
@login_required
def transfer_download():
    bundle = build_transfer_bundle()
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", bundle["source"] or "ark").strip("_") or "ark"
    resp = app.response_class(json.dumps(bundle, indent=2, ensure_ascii=False),
                              mimetype="application/json")
    resp.headers["Content-Disposition"] = 'attachment; filename="ark-transfer-%s-%s.json"' % (
        name, time.strftime("%Y%m%d-%H%M"))
    return resp


@app.route("/transfer/export")
def transfer_export():
    """Maschinen-Endpunkt für den Direktabruf durch ein anderes Panel (Token nötig)."""
    tok = load_transfer_token()
    given = request.headers.get("X-Transfer-Token", "")
    if not tok or not given or not secrets.compare_digest(tok, given):
        return jsonify(error="forbidden"), 403
    return jsonify(build_transfer_bundle())


@app.route("/transfer/token", methods=["POST"])
@login_required
def transfer_token():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("transfer_page"))
    if request.form.get("act") == "revoke":
        save_transfer_token("")
        flash(t("xfer_token_revoked"))
    else:
        save_transfer_token(secrets.token_urlsafe(24))
        flash(t("xfer_token_created"))
    return redirect(url_for("transfer_page"))


@app.route("/transfer/upload", methods=["POST"])
@login_required
def transfer_upload():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("transfer_page"))
    f = request.files.get("bundle")
    if not f or not f.filename:
        flash(t("xfer_no_file"))
        return redirect(url_for("transfer_page"))
    try:
        data = json.loads(f.read(TRANSFER_MAX_BYTES).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        flash(t("xfer_bad_format"))
        return redirect(url_for("transfer_page"))
    return _run_import(data)


@app.route("/transfer/pull", methods=["POST"])
@login_required
def transfer_pull():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("transfer_page"))
    url = request.form.get("url", "").strip().rstrip("/")
    tok = request.form.get("token", "").strip()
    if url and "://" not in url:
        url = "http://" + url
    if not re.match(r"^https?://[A-Za-z0-9.\-\[\]:]+(/.*)?$", url) or not tok:
        flash(t("xfer_pull_bad_input"))
        return redirect(url_for("transfer_page"))
    if not url.endswith("/transfer/export"):
        url += "/transfer/export"
    try:
        req = urllib.request.Request(url, headers={"X-Transfer-Token": tok,
                                                   "User-Agent": "ark-panel/" + PANEL_VERSION})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(TRANSFER_MAX_BYTES + 1)
        if len(body) > TRANSFER_MAX_BYTES:
            raise ValueError("too large")
        data = json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as e:
        flash(t("xfer_pull_denied") if e.code == 403 else t("xfer_pull_failed", err="HTTP %d" % e.code))
        return redirect(url_for("transfer_page"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        flash(t("xfer_pull_failed", err=str(getattr(e, "reason", e))))
        return redirect(url_for("transfer_page"))
    return _run_import(data)


@app.route("/transfer/restore", methods=["POST"])
@login_required
def transfer_restore():
    """Ein Import-Backup zurückspielen (vorher wird der aktuelle Stand gesichert)."""
    import shutil
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("transfer_page"))
    name = request.form.get("backup", "")
    src = os.path.join(TRANSFER_BACKUP_DIR, name)
    if not re.match(r"^[0-9-]{8,24}$", name) or not os.path.isdir(src):
        flash(t("xfer_backup_missing"))
        return redirect(url_for("transfer_page"))
    if service_active(SERVICE) == "active":
        flash(t("xfer_stop_first"))
        return redirect(url_for("transfer_page"))
    try:
        with _state_lock:
            _transfer_backup(prune=False)   # src darf beim Aufräumen nicht verschwinden
            for label, key in (("GameUserSettings.ini", "gus"), ("Game.ini", "game")):
                p = os.path.join(src, label)
                if os.path.exists(p):
                    write_ini(key, _read_text(p))
            for label, dst in (("runtime.json", RUNTIME_PATH), ("mods.json", MODS_PATH),
                               ("maps.json", MAPS_PATH)):
                p = os.path.join(src, label)
                if os.path.exists(p):
                    tmp = dst + ".tmp"
                    shutil.copy2(p, tmp)
                    os.chmod(tmp, 0o600)
                    os.replace(tmp, dst)
    except OSError as e:
        flash(t("xfer_error", err=str(e)))
        return redirect(url_for("transfer_page"))
    flash(t("xfer_restored", name=name))
    return redirect(url_for("transfer_page"))


# ---------------------------------------------------------------------------
# Routen: Konto / Benutzer
# ---------------------------------------------------------------------------
@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        if not check_csrf():
            flash(t("csrf_invalid"))
            return redirect(url_for("account"))
        me = session["user"]
        cur = request.form.get("current", "")
        new = request.form.get("new", "")
        conf = request.form.get("confirm", "")
        users = load_users()
        if not check_password_hash(users[me]["password_hash"], cur):
            flash(t("pw_wrong_current"))
        elif len(new) < MIN_PW:
            flash(t("pw_too_short", n=MIN_PW))
        elif new != conf:
            flash(t("pw_mismatch"))
        else:
            with _users_lock:
                users = load_users()
                users[me]["password_hash"] = generate_password_hash(new)
                save_users(users)
            flash(t("pw_changed"))
        return redirect(url_for("account"))
    return render_template("account.html")


@app.route("/users")
@login_required
def users_page():
    return render_template("users.html", users=load_users(), me=session["user"])


@app.route("/users/add", methods=["POST"])
@login_required
def users_add():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("users_page"))
    name = request.form.get("username", "").strip()
    pw = request.form.get("password", "")
    users = load_users()
    if not USERNAME_RE.match(name):
        flash(t("user_invalid_name"))
    elif name in users:
        flash(t("user_exists"))
    elif len(pw) < MIN_PW:
        flash(t("user_pw_short", n=MIN_PW))
    else:
        with _users_lock:
            users = load_users()
            users[name] = {"password_hash": generate_password_hash(pw)}
            save_users(users)
        flash(t("user_created", name=name))
    return redirect(url_for("users_page"))


@app.route("/users/reset", methods=["POST"])
@login_required
def users_reset():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("users_page"))
    name = request.form.get("username", "")
    pw = request.form.get("password", "")
    users = load_users()
    if name not in users:
        flash(t("user_not_found"))
    elif len(pw) < MIN_PW:
        flash(t("user_pw_short", n=MIN_PW))
    else:
        with _users_lock:
            users = load_users()
            users[name]["password_hash"] = generate_password_hash(pw)
            save_users(users)
        flash(t("user_pw_reset", name=name))
    return redirect(url_for("users_page"))


@app.route("/users/delete", methods=["POST"])
@login_required
def users_delete():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("users_page"))
    name = request.form.get("username", "")
    me = session["user"]
    users = load_users()
    if name not in users:
        flash(t("user_not_found"))
    elif name == me:
        flash(t("user_delete_self"))
    elif len(users) <= 1:
        flash(t("user_delete_last"))
    else:
        with _users_lock:
            users = load_users()
            users.pop(name, None)
            save_users(users)
        flash(t("user_deleted", name=name))
    return redirect(url_for("users_page"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=True)
