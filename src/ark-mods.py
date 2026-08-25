#!/usr/bin/env python3
"""
ARK Mod-Sync für Linux-Dedicated-Server.

Warum das nötig ist: ARK-Workshop-Mods werden von SteamCMD als komprimierte
.z-Archive geliefert. Der Windows-Server entpackt sie beim Start selbst und legt
sie unter ShooterGame/Content/Mods/<id>/ ab – auf Linux fehlt genau dieser
Schritt (auch mit -automanagedmods). Dieses Skript übernimmt ihn:

  1. Mod per SteamCMD laden  (+workshop_download_item 346110 <id>)
  2. alle .z-Archive nach dem ARK-Format entpacken
  3. mod.info / modmeta.info auslesen und die <id>.mod-Datei erzeugen
  4. alles nach ShooterGame/Content/Mods/<id>/ (+ <id>.mod) kopieren

Aufruf (immer als der Server-Benutzer, sonst stimmen die Dateirechte nicht):

  sudo -u ark ARK_DIR=/home/ark/arkserver python3 ark-mods.py 793605978 [weitere-ids]
  sudo -u ark python3 ark-mods.py --from-runtime /opt/ark-panel/runtime.json

Die Dateiformate (.z, .mod, mod.info, modmeta.info) sind ARK-/UE4-spezifisch;
diese Implementierung folgt der öffentlich dokumentierten Struktur.
"""

import glob
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib

GAME_APPID = "346110"           # Workshop-Content läuft unter der Client-AppID
Z_SIGNATURE = 2653586369        # gültige ARK-.z-Signatur (0x9E2A83C1)
STEAMCMD = os.environ.get("STEAMCMD", "/usr/games/steamcmd")


def log(msg):
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
#  .z-Entpackung  (UE4/ARK-Kompressionsformat)
# --------------------------------------------------------------------------- #
def unpack_z(src, dst):
    """Entpackt ein ARK-.z-Archiv nach dst."""
    with open(src, "rb") as f:
        signature = struct.unpack("<q", f.read(8))[0]
        if signature != Z_SIGNATURE:
            raise ValueError(f"Ungültige .z-Signatur ({signature}) in {src}")
        struct.unpack("<q", f.read(8))[0]          # max. unpacked chunk size
        struct.unpack("<q", f.read(8))[0]          # gesamt packed
        total_unpacked = struct.unpack("<q", f.read(8))[0]

        # Chunk-Index: (packed, unpacked)-Paare, bis die Summe der unpacked-
        # Größen der Gesamtgröße entspricht.
        index = []
        counted = 0
        while counted < total_unpacked:
            packed = struct.unpack("<q", f.read(8))[0]
            unpacked = struct.unpack("<q", f.read(8))[0]
            index.append((packed, unpacked))
            counted += unpacked
        if counted != total_unpacked:
            raise ValueError(f"Header/Index-Mismatch in {src}")

        out = bytearray()
        for packed, unpacked in index:
            chunk = zlib.decompress(f.read(packed))
            if len(chunk) != unpacked:
                raise ValueError(f"Chunk-Größe weicht ab in {src}")
            out += chunk

    if len(out) != total_unpacked:
        raise ValueError(f"Gesamtgröße weicht ab in {src}")
    with open(dst, "wb") as f:
        f.write(out)


# --------------------------------------------------------------------------- #
#  UE4-Strings + .mod-Metadaten
# --------------------------------------------------------------------------- #
def read_ue4_string(f):
    """Liest einen UE4-String: int32-Länge, dann die Bytes inkl. Null-Terminator.
    Negative Länge = UTF-16LE (kommt bei ARK-Mods praktisch nicht vor)."""
    count = struct.unpack("<i", f.read(4))[0]
    if count == 0:
        return ""
    if count < 0:
        raw = f.read(2 * (-count))
        return raw[:-2].decode("utf-16-le", "ignore")
    raw = f.read(count)
    return raw[:-1].decode("utf-8", "ignore")


def write_ue4_string(f, text):
    """Schreibt einen UE4-String: int32-Länge (inkl. Terminator), Bytes, \\x00."""
    data = text.encode("utf-8")
    f.write(struct.pack("<i", len(data) + 1))
    f.write(data)
    f.write(b"\x00")


def parse_mod_info(path):
    """mod.info -> Liste der Map-/Mod-Namen."""
    maps = []
    with open(path, "rb") as f:
        read_ue4_string(f)                              # interner Name, verworfen
        count = struct.unpack("<i", f.read(4))[0]
        for _ in range(count):
            name = read_ue4_string(f)
            if name:
                maps.append(name)
    return maps


def parse_modmeta(path):
    """modmeta.info -> Liste von (Key, Value)-Paaren."""
    meta = []
    with open(path, "rb") as f:
        pairs = struct.unpack("<i", f.read(4))[0]
        for _ in range(pairs):
            key = read_ue4_string(f)
            value = read_ue4_string(f)
            if key:
                meta.append((key, value))
    return meta


def write_mod_file(dst, modid, maps, meta):
    """Erzeugt die <id>.mod-Datei, die ARK zum Registrieren der Mod braucht."""
    with open(dst, "wb") as f:
        f.write(struct.pack("<i", int(modid)))          # ModID (int32) ...
        f.write(b"\x00\x00\x00\x00")                    # ... + 4 Pad-Bytes
        write_ue4_string(f, "ModName")
        write_ue4_string(f, "")
        f.write(struct.pack("<i", len(maps)))
        for name in maps:
            write_ue4_string(f, name)
        f.write(struct.pack("<I", 4280483635))          # feste Marker aus dem Format
        f.write(struct.pack("<i", 2))
        has_modtype = any(k == "ModType" for k, _ in meta)
        f.write(struct.pack("<b", 1 if has_modtype else 0))
        f.write(struct.pack("<i", len(meta)))
        for key, value in meta:
            write_ue4_string(f, key)
            write_ue4_string(f, value)


# --------------------------------------------------------------------------- #
#  Download + Installation
# --------------------------------------------------------------------------- #
def find_download_dir(modid):
    """Findet das von SteamCMD heruntergeladene Workshop-Verzeichnis der Mod."""
    home = os.path.expanduser("~")
    bases = [
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam"),
        os.path.join(home, "Steam"),
        os.path.join(home, ".local", "share", "Steam"),
    ]
    rel = os.path.join("steamapps", "workshop", "content", GAME_APPID, str(modid))
    for base in bases:
        cand = os.path.join(base, rel)
        if os.path.isdir(cand):
            return cand
    # Fallback: gezielt unter den Steam-Verzeichnissen suchen
    for base in bases:
        for hit in glob.glob(os.path.join(base, "**", rel), recursive=True):
            if os.path.isdir(hit):
                return hit
    return None


def content_subdir(download_dir):
    """ARK-Workshop-Content liegt im Unterordner WindowsNoEditor (auch auf Linux)."""
    win = os.path.join(download_dir, "WindowsNoEditor")
    return win if os.path.isdir(win) else download_dir


def extract_all_z(root):
    """Entpackt rekursiv alle .z-Archive und räumt .z/.uncompressed_size weg."""
    count = 0
    for curdir, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".z"):
                continue
            src = os.path.join(curdir, name)
            unpack_z(src, src[:-2])                      # ohne ".z"
            os.remove(src)
            size_hint = src + ".uncompressed_size"
            if os.path.isfile(size_hint):
                os.remove(size_hint)
            count += 1
    return count


def install_mod(modid, ark_dir):
    """Lädt eine Mod, entpackt sie und installiert sie in den Server."""
    log(f"[+] Lade Mod {modid} via SteamCMD ...")
    proc = subprocess.run(
        [STEAMCMD, "+login", "anonymous",
         "+workshop_download_item", GAME_APPID, str(modid), "+quit"],
        check=False, capture_output=True, text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    # SteamCMD-Zeilen durchreichen, damit sie im Journal sichtbar bleiben
    for line in out.splitlines():
        if line.strip():
            log("    " + line.rstrip())

    # SteamCMD gibt bei nicht (mehr) verfügbaren Mods "Download item ... failed"
    # zurück – das direkt abfangen, statt später über ein fehlendes Verzeichnis
    # zu stolpern (irreführende Meldung).
    lo = out.lower()
    if "success. downloaded item" not in lo:
        if "failed" in lo and "download item" in lo:
            raise RuntimeError(
                "Von SteamCMD abgelehnt (failed) – Mod entfernt, privat oder "
                "keine ARK-SE-Workshop-Mod?")
        raise RuntimeError(
            "SteamCMD hat die Mod nicht geladen (kein 'Success' in der Ausgabe).")

    download = find_download_dir(modid)
    if not download:
        raise RuntimeError(
            "Heruntergeladene Dateien nicht gefunden – Download unvollständig?")
    content = content_subdir(download)

    log(f"[+] Entpacke .z-Dateien in {content} ...")
    n = extract_all_z(content)
    log(f"[+] {n} Datei(en) entpackt.")

    mod_info = os.path.join(content, "mod.info")
    if not os.path.isfile(mod_info):
        raise RuntimeError(f"mod.info fehlt für Mod {modid} – Download unvollständig?")
    maps = parse_mod_info(mod_info)
    meta_path = os.path.join(content, "modmeta.info")
    meta = parse_modmeta(meta_path) if os.path.isfile(meta_path) else []

    mods_root = os.path.join(ark_dir, "ShooterGame", "Content", "Mods")
    os.makedirs(mods_root, exist_ok=True)
    target = os.path.join(mods_root, str(modid))
    if os.path.isdir(target):
        shutil.rmtree(target)
    shutil.copytree(content, target)
    write_mod_file(os.path.join(mods_root, f"{modid}.mod"), modid, maps, meta)
    log(f"[+] Mod {modid} installiert -> {target}")


def load_ids_from_runtime(path):
    with open(path) as f:
        data = json.load(f)
    return [str(m) for m in data.get("mods", [])]


def main(argv):
    ark_dir = os.environ.get("ARK_DIR", "/home/ark/arkserver")
    args = list(argv)

    if args and args[0] == "--from-runtime":
        if len(args) < 2:
            log("[x] --from-runtime braucht einen Pfad zur runtime.json")
            return 2
        modids = load_ids_from_runtime(args[1])
    else:
        modids = args

    if not modids:
        log("[x] Keine Mod-IDs angegeben.")
        log("    Aufruf: ark-mods.py <id> [id ...]  oder  --from-runtime <runtime.json>")
        return 2

    if not (os.path.isfile(STEAMCMD) or shutil.which(STEAMCMD)):
        log(f"[x] SteamCMD nicht gefunden ({STEAMCMD}). STEAMCMD-Umgebungsvariable setzen.")
        return 1

    log(f"[+] ARK-Verzeichnis: {ark_dir}")
    log(f"[+] Zu synchronisierende Mods: {', '.join(modids)}")
    ok, failed = [], []
    for modid in modids:
        try:
            install_mod(modid, ark_dir)
            ok.append(modid)
        except Exception as exc:      # eine kaputte Mod nicht die anderen abbrechen lassen
            log(f"[x] Mod {modid} fehlgeschlagen: {exc}")
            failed.append(modid)

    log(f"[+] Bilanz: {len(ok)}/{len(modids)} installiert"
        + (f", fehlgeschlagen: {', '.join(failed)}" if failed else ""))

    if not ok:
        # gar nichts installiert -> echter Fehler
        log("[x] Keine Mod konnte installiert werden.")
        return 1
    if failed:
        # teils erfolgreich: als Erfolg werten, damit der gute Teil zählt;
        # die fehlgeschlagenen IDs stehen oben im Log.
        log("[!] Fertig – mit übersprungenen Mods (siehe oben). Server neu starten.")
        return 0
    log("[+] Fertig. Server neu starten, damit die Mods geladen werden.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
