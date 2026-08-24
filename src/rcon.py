#!/usr/bin/env python3
"""
Minimaler Source-RCON-Client für ARK: Survival Evolved – ohne externe Abhängigkeiten.
ARK nutzt das Standard-Source-RCON-Protokoll; das RCON-Passwort ist das
ServerAdminPassword aus der GameUserSettings.ini, der Port kommt aus RCONPort
(Standard 27020).
"""
import re
import socket
import struct

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0


class RCONError(Exception):
    pass


class ArkRCON:
    def __init__(self, host, port, password, timeout=4):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout
        self.sock = None
        self._id = 0

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _recvn(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RCONError("Verbindung vom Server geschlossen.")
            buf += chunk
        return buf

    def _send(self, ptype, body):
        self._id += 1
        payload = struct.pack("<ii", self._id, ptype) + body.encode("utf-8") + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(payload)) + payload)
        return self._id

    def _recv(self):
        (length,) = struct.unpack("<i", self._recvn(4))
        data = self._recvn(length)
        pid, ptype = struct.unpack("<ii", data[:8])
        body = data[8:-2] if len(data) >= 10 else b""
        return pid, ptype, body.decode("utf-8", errors="replace")

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock.settimeout(self.timeout)
        auth_id = self._send(SERVERDATA_AUTH, self.password)
        pid, ptype, _ = self._recv()
        # Manche Server senden zuerst einen leeren RESPONSE_VALUE
        if ptype == SERVERDATA_RESPONSE_VALUE:
            pid, ptype, _ = self._recv()
        if pid == -1 or pid != auth_id:
            raise RCONError("RCON-Authentifizierung fehlgeschlagen (ServerAdminPassword prüfen).")

    def command(self, cmd):
        self._send(SERVERDATA_EXECCOMMAND, cmd)
        _, _, body = self._recv()
        return body.strip()

    # -- bequeme Wrapper --------------------------------------------------
    def players(self):
        """Liste aus dicts: {name, steamid, playeruid}. 'ListPlayers' liefert
        Zeilen wie '0. Spielername, 76561198…' (oder eine EOS-ID)."""
        raw = self.command("ListPlayers")
        rows = []
        if not raw or "no players" in raw.lower():
            return rows
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^\d+\.\s*(.*?),\s*([0-9A-Za-z._-]+)\s*$", line)
            if m:
                rows.append({"name": m.group(1).strip(),
                             "steamid": m.group(2).strip(),
                             "playeruid": ""})
            elif not line.lower().startswith(("no ", "server")):
                rows.append({"name": line, "steamid": "", "playeruid": ""})
        return rows

    def save(self):
        return self.command("SaveWorld")

    def broadcast(self, message):
        return self.command("Broadcast " + message)

    def server_chat(self, message):
        return self.command("ServerChat " + message)

    def kick(self, ident):
        return self.command("KickPlayer " + str(ident))

    def ban(self, ident):
        return self.command("BanPlayer " + str(ident))

    def shutdown(self):
        # ARK kennt keinen eingebauten Countdown – vorher SaveWorld aufrufen.
        return self.command("DoExit")
