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
    "automanaged_mods": False,
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
    rc, out = run(["journalctl", "-u", name, "-n", str(lines),
                   "--no-pager", "-o", "short-iso"])
    return out if rc == 0 else "Keine Logs verfügbar (Rechte prüfen)."


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
    path = INI_FILES[key]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


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
        logs=recent_logs(SERVICE),
        active_map=map_name_for(rt["map"]),
        mods_count=len(rt["mods"]),
        service=SERVICE,
        connect_ip=ip,
        connect_query=rt.get("query_port", 27015),
        connect_game=rt.get("port", 7777),
        connect_kind=kind,
    )


@app.route("/status")
@login_required
def status():
    return jsonify(
        server=service_active(SERVICE),
        update=service_active(UPDATE_SERVICE),
        enabled=service_enabled(SERVICE),
        logs=recent_logs(SERVICE, 60),
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
            "extra_args": request.form.get("extra_args", "").strip(),
        })
        save_runtime(rt)
    flash(t("launch_saved"))
    return redirect(url_for("maps_page"))


# ---------------------------------------------------------------------------
# Routen: Mods
# ---------------------------------------------------------------------------
@app.route("/mods")
@login_required
def mods_page():
    rt = load_runtime()
    return render_template("mods.html", rt=rt, mods=active_mods_view(),
                           sync_state=service_active(MODS_SERVICE))


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
    rc, out = svc("start", MODS_SERVICE)
    flash(t("mods_sync_started") if rc == 0 else t("mods_sync_failed", out=out))
    return redirect(url_for("mods_page"))


@app.route("/mods/sync-status")
@login_required
def mods_sync_status():
    return jsonify(state=service_active(MODS_SERVICE),
                   logs=recent_logs(MODS_SERVICE, 80))


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


@app.route("/mods/automanaged", methods=["POST"])
@login_required
def mods_automanaged():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("mods_page"))
    with _state_lock:
        rt = load_runtime()
        rt["automanaged_mods"] = bool(request.form.get("automanaged_mods"))
        save_runtime(rt)
    flash(t("mods_automanaged_saved"))
    return redirect(url_for("mods_page"))


# ---------------------------------------------------------------------------
# Routen: Konfiguration (GameUserSettings.ini / Game.ini)
# ---------------------------------------------------------------------------
def _current_file_key():
    key = request.args.get("file") or request.form.get("file") or "gus"
    return key if key in INI_FILES else "gus"


@app.route("/config", methods=["GET"])
@login_required
def config():
    key = _current_file_key()
    raw, entries = read_ini(key)
    return render_template("config.html",
                           file_key=key, files=INI_LABELS,
                           groups=group_ini(entries), raw=raw,
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
                edits[e["id"]] = request.form.get(field, "")
    write_ini(key, apply_ini(entries, edits))
    flash(t("config_saved"))
    return redirect(url_for("config", file=key))


@app.route("/config/save-raw", methods=["POST"])
@login_required
def config_save_raw():
    if not check_csrf():
        flash(t("csrf_invalid"))
        return redirect(url_for("config"))
    key = _current_file_key()
    write_ini(key, request.form.get("raw", ""))
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
        return jsonify(enabled=True, reachable=False, players=[], note=str(e))


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
