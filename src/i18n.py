#!/usr/bin/env python3
"""Leichtgewichtige DE/EN-Übersetzungen für das ARK Control Panel."""

LANGS = ("de", "en")
DEFAULT_LANG = "de"

TRANSLATIONS = {
    # -- Navigation / allgemein --
    "nav_overview": {"de": "Übersicht", "en": "Overview"},
    "nav_maps": {"de": "Karten", "en": "Maps"},
    "nav_mods": {"de": "Mods", "en": "Mods"},
    "nav_config": {"de": "Konfiguration", "en": "Configuration"},
    "nav_users": {"de": "Benutzer", "en": "Users"},
    "nav_account": {"de": "Konto", "en": "Account"},
    "nav_logout": {"de": "Abmelden", "en": "Log out"},
    "save": {"de": "Speichern", "en": "Save"},

    # -- Login --
    "login_title": {"de": "Anmelden", "en": "Sign in"},
    "login_subtitle": {"de": "Melde dich an, um den Server zu verwalten.",
                       "en": "Sign in to manage the server."},
    "username": {"de": "Benutzername", "en": "Username"},
    "password": {"de": "Passwort", "en": "Password"},
    "login_btn": {"de": "Anmelden", "en": "Sign in"},
    "login_bad": {"de": "Benutzername oder Passwort ist falsch.",
                  "en": "Wrong username or password."},

    # -- Dashboard --
    "server_status": {"de": "Serverstatus", "en": "Server status"},
    "boot_on": {"de": "↻ startet nach einem Reboot automatisch",
                "en": "↻ starts automatically after a reboot"},
    "boot_off": {"de": "○ bleibt nach einem Reboot aus",
                 "en": "○ stays off after a reboot"},
    "btn_start": {"de": "Starten", "en": "Start"},
    "btn_restart": {"de": "Neu starten", "en": "Restart"},
    "btn_stop": {"de": "Stoppen", "en": "Stop"},
    "btn_update": {"de": "Aktualisieren", "en": "Update"},
    "confirm_update": {"de": "Update starten? Der Server wird dafür gestoppt.",
                       "en": "Start update? The server will be stopped for it."},
    "active_map_label": {"de": "Aktive Karte", "en": "Active map"},
    "connect_title": {"de": "Verbinden", "en": "Connect"},
    "connect_steam": {"de": "Steam-Serverbrowser", "en": "Steam server browser"},
    "connect_steam_hint": {
        "de": "Ansicht → Server → Favoriten → Server hinzufügen (Query-Port!)",
        "en": "View → Servers → Favorites → Add a server (query port!)",
    },
    "connect_console": {"de": "In-Game-Konsole", "en": "In-game console"},
    "connect_console_hint": {
        "de": "Tab-Taste drücken, Befehl eingeben (Spiel-Port!)",
        "en": "Press Tab, then enter the command (game port!)",
    },
    "connect_copy": {"de": "Kopieren", "en": "Copy"},
    "connect_kind_auto": {"de": "öffentliche IP · automatisch", "en": "public IP · auto-detected"},
    "connect_kind_manual": {"de": "öffentliche Adresse", "en": "public address"},
    "connect_kind_local": {"de": "lokale Adresse", "en": "local address"},
    "connect_local_note": {
        "de": "Öffentliche IP nicht ermittelbar (kein Internet-Egress?) – lokale Adresse angezeigt. Bei Bedarf öffentliche IP/DDNS bei den Startparametern eintragen und die Ports in OPNsense weiterleiten.",
        "en": "Public IP could not be detected (no internet egress?) – showing the local address. If needed, set the public IP/DDNS in the launch parameters and forward the ports in your firewall.",
    },
    "mods_active_label": {"de": "Aktive Mods", "en": "Active mods"},
    "res_title": {"de": "Ressourcen", "en": "Resources"},
    "res_cpu": {"de": "CPU", "en": "CPU"},
    "res_mem": {"de": "RAM", "en": "RAM"},
    "res_disk": {"de": "Disk", "en": "Disk"},
    "res_version": {"de": "Version", "en": "Version"},
    "res_server": {"de": "ARK-Server", "en": "ARK server"},
    "res_server_off": {"de": "aus", "en": "off"},
    "players_online": {"de": "Spieler online", "en": "Players online"},
    "server_log": {"de": "Server-Log", "en": "Server log"},
    "auto_refresh": {"de": "aktualisiert automatisch", "en": "auto-refreshing"},
    "update_running": {"de": "Update läuft", "en": "Update running"},
    "loading": {"de": "Lade …", "en": "Loading …"},
    "world_save": {"de": "Welt speichern", "en": "Save world"},
    "save_and_stop": {"de": "Speichern & Stoppen", "en": "Save & stop"},
    "confirm_save_stop": {"de": "Welt speichern und Server sauber herunterfahren?",
                          "en": "Save world and shut the server down cleanly?"},
    "msg_placeholder": {"de": "Nachricht an Spieler …", "en": "Message to players …"},
    "send": {"de": "Senden", "en": "Send"},
    "rcon_help": {
        "de": "RCON läuft server-intern über 127.0.0.1. „Speichern & Stoppen“ ist der "
              "saubere Weg zum Beenden – ARK speichert bei einem harten Stopp nicht.",
        "en": "RCON runs internally via 127.0.0.1. “Save & stop” is the clean way to shut "
              "down — ARK does not save on a hard stop."},
    "rcon_setup_btn": {"de": "RCON einrichten", "en": "Set up RCON"},
    "rcon_setup_help": {
        "de": "Vergibt bei Bedarf ein ServerAdminPassword (= RCON- und In-Game-Admin-"
              "Passwort). RCON wird beim Start ohnehin aktiviert.",
        "en": "Sets a ServerAdminPassword if needed (= RCON and in-game admin password). "
              "RCON is enabled on launch anyway."},
    "nobody_online": {"de": "Niemand online.", "en": "Nobody online."},
    "rcon_unreachable": {"de": "RCON nicht erreichbar", "en": "RCON not reachable"},
    "kick": {"de": "Kicken", "en": "Kick"},
    "ban": {"de": "Bannen", "en": "Ban"},
    "confirm_kick": {"de": "Spieler {name} kicken?", "en": "Kick player {name}?"},
    "confirm_ban": {"de": "Spieler {name} bannen?", "en": "Ban player {name}?"},
    "player_kicked": {"de": "Spieler gekickt.", "en": "Player kicked."},
    "player_banned": {"de": "Spieler gebannt.", "en": "Player banned."},
    "no_steamid": {"de": "Keine Spieler-ID angegeben.", "en": "No player ID provided."},

    # -- Karten --
    "maps_title": {"de": "Kartenverwaltung", "en": "Map management"},
    "maps_active": {"de": "Aktive Karte", "en": "Active map"},
    "maps_active_hint": {
        "de": "Die Karte wird beim Serverstart als Startparameter gesetzt. "
              "Nach dem Umstellen den Server neu starten.",
        "en": "The map is passed as a launch parameter. Restart the server after changing it."},
    "maps_official": {"de": "Offizielle Karten", "en": "Official maps"},
    "maps_custom": {"de": "Eigene / Mod-Karten", "en": "Custom / mod maps"},
    "maps_select_btn": {"de": "Als aktive Karte setzen", "en": "Set as active map"},
    "maps_current": {"de": "aktiv", "en": "active"},
    "maps_paid": {"de": "DLC", "en": "DLC"},
    "maps_paid_hint": {
        "de": "Kostenpflichtiges Expansion-Pack – der Server lädt es gratis, aber Spieler müssen das DLC in Steam besitzen, um beizutreten.",
        "en": "Paid expansion pack – the server downloads it for free, but players must own the DLC on Steam to join.",
    },
    "maps_modmap_note": {
        "de": "Mod-Karte – die zugehörige Mod-ID muss unter „Mods“ eingetragen sein "
              "(oder „Mods automatisch verwalten“ aktiv).",
        "en": "Mod map – its mod ID must be listed under “Mods” (or “auto-managed mods” enabled)."},
    "maps_add_title": {"de": "Eigene Karte hinzufügen", "en": "Add custom map"},
    "maps_add_code_ph": {"de": "Karten-Code (z. B. Ragnarok)", "en": "Map code (e.g. Ragnarok)"},
    "maps_add_name_ph": {"de": "Anzeigename", "en": "Display name"},
    "maps_add_mod_ph": {"de": "Mod-ID (optional, für Mod-Karten)", "en": "Mod ID (optional, for mod maps)"},
    "maps_add_btn": {"de": "Karte hinzufügen", "en": "Add map"},
    "maps_delete_btn": {"de": "Entfernen", "en": "Remove"},
    "maps_modid_label": {"de": "Mod-ID", "en": "Mod ID"},
    "map_code_invalid": {"de": "Ungültiger Karten-Code (nur Buchstaben, Zahlen, _ ).",
                         "en": "Invalid map code (letters, digits, _ only)."},
    "map_exists": {"de": "Diese Karte ist bereits eingetragen.", "en": "This map is already listed."},
    "map_added": {"de": "Karte '{name}' hinzugefügt.", "en": "Map '{name}' added."},
    "map_deleted": {"de": "Karte entfernt.", "en": "Map removed."},
    "map_not_found": {"de": "Karte nicht gefunden.", "en": "Map not found."},
    "map_selected": {"de": "Aktive Karte auf '{name}' gesetzt. Server neu starten.",
                     "en": "Active map set to '{name}'. Restart the server."},

    # -- Startparameter --
    "launch_title": {"de": "Startparameter", "en": "Launch parameters"},
    "launch_session": {"de": "Servername (SessionName)", "en": "Server name (SessionName)"},
    "launch_maxplayers": {"de": "Max. Spieler", "en": "Max players"},
    "launch_port": {"de": "Spielport (Port)", "en": "Game port (Port)"},
    "launch_query": {"de": "Query-Port", "en": "Query port"},
    "launch_rconport": {"de": "RCON-Port", "en": "RCON port"},
    "launch_battleye": {"de": "BattlEye aktiv", "en": "BattlEye enabled"},
    "launch_public": {"de": "Öffentliche Adresse (optional)", "en": "Public address (optional)"},
    "launch_public_ph": {
        "de": "z. B. ark.meinedomain.de oder öffentliche IP – für die Anzeige im Dashboard",
        "en": "e.g. ark.mydomain.com or public IP – shown on the dashboard",
    },
    "launch_serverpw": {"de": "Server-Passwort (optional)", "en": "Server password (optional)"},
    "launch_serverpw_ph": {
        "de": "Beitrittspasswort – leer lassen für offenen Server",
        "en": "Join password – leave empty for an open server",
    },
    "launch_extra": {"de": "Zusätzliche Startargumente", "en": "Extra launch arguments"},
    "launch_extra_ph": {"de": "z. B. -NoTransferFromFiltering -ForceAllowCaveFlyers",
                        "en": "e.g. -NoTransferFromFiltering -ForceAllowCaveFlyers"},
    "launch_saved": {"de": "Startparameter gespeichert. Server neu starten.",
                     "en": "Launch parameters saved. Restart the server."},
    "launch_save_btn": {"de": "Startparameter speichern", "en": "Save launch parameters"},
    "launch_bad_number": {"de": "Ungültiger Zahlenwert.", "en": "Invalid numeric value."},

    # -- Mods --
    "mods_title": {"de": "Mod-Verwaltung", "en": "Mod management"},
    "mods_intro": {
        "de": "Trage die Steam-Workshop-IDs der Mods in Ladereihenfolge ein. Reihenfolge kann "
              "für abhängige Mods wichtig sein. Nach dem Eintragen unten „Mods synchronisieren“ "
              "klicken und danach den Server neu starten.",
        "en": "List the Steam Workshop IDs of your mods in load order. Order can matter for "
              "dependent mods. After adding them, click “Sync mods” below and restart the server."},
    "mods_add_title": {"de": "Mod hinzufügen", "en": "Add mod"},
    "mods_add_id_ph": {"de": "Workshop-ID (z. B. 731604991)", "en": "Workshop ID (e.g. 731604991)"},
    "mods_add_name_ph": {"de": "Name (optional)", "en": "Name (optional)"},
    "mods_add_btn": {"de": "Hinzufügen", "en": "Add"},
    "mods_list_title": {"de": "Aktive Mods (Ladereihenfolge)", "en": "Active mods (load order)"},
    "mods_sync_title": {"de": "Mods herunterladen / installieren", "en": "Download / install mods"},
    "mods_sync_hint": {
        "de": "Lädt die eingetragenen Mods per SteamCMD, entpackt sie und installiert sie in den Server. Danach den Server neu starten.",
        "en": "Downloads the listed mods via SteamCMD, extracts and installs them into the server. Restart the server afterwards.",
    },
    "mods_sync_btn": {"de": "Mods synchronisieren", "en": "Sync mods"},
    "mods_sync_running": {"de": "Synchronisierung läuft …", "en": "Sync running …"},
    "mods_phase_download": {"de": "lädt", "en": "downloading"},
    "mods_phase_extract": {"de": "entpackt", "en": "extracting"},
    "mods_phase_installed": {"de": "installiert", "en": "installed"},
    "mods_progress_running": {
        "de": "Mod {pos}/{total} ({mod}) – {phase} …",
        "en": "Mod {pos}/{total} ({mod}) – {phase} …"},
    "mods_progress_done": {
        "de": "Fertig: {ok}/{total} installiert.",
        "en": "Done: {ok}/{total} installed."},
    "mods_last_ok": {
        "de": "Zuletzt synchronisiert: {ok}/{total} installiert ({when} Uhr).",
        "en": "Last sync: {ok}/{total} installed ({when})."},
    "mods_last_failed": {
        "de": "Fehlgeschlagen: {failed}",
        "en": "Failed: {failed}"},
    "mods_sync_started": {"de": "Mod-Synchronisierung gestartet. Das kann einige Minuten dauern.",
                          "en": "Mod sync started. This may take a few minutes."},
    "mods_sync_failed": {"de": "Synchronisierung konnte nicht gestartet werden: {out}",
                         "en": "Could not start sync: {out}"},
    "mods_sync_empty": {"de": "Keine Mods eingetragen – nichts zu synchronisieren.",
                        "en": "No mods listed – nothing to sync."},
    "mods_empty": {"de": "Noch keine Mods eingetragen.", "en": "No mods listed yet."},
    "mods_up": {"de": "▲", "en": "▲"},
    "mods_down": {"de": "▼", "en": "▼"},
    "mods_remove_btn": {"de": "Entfernen", "en": "Remove"},
    "mods_workshop_link": {"de": "Workshop", "en": "Workshop"},
    "mod_id_invalid": {"de": "Ungültige Workshop-ID (nur Ziffern).", "en": "Invalid Workshop ID (digits only)."},
    "mod_exists": {"de": "Diese Mod-ID ist bereits eingetragen.", "en": "This mod ID is already listed."},
    "mod_added": {"de": "Mod {id} hinzugefügt.", "en": "Mod {id} added."},
    "mod_removed": {"de": "Mod entfernt.", "en": "Mod removed."},
    "mod_not_found": {"de": "Mod nicht gefunden.", "en": "Mod not found."},
    "mods_saved": {"de": "Mods gespeichert. Server neu starten.", "en": "Mods saved. Restart the server."},

    # -- Konfiguration --
    "cfg_file": {"de": "Datei", "en": "File"},
    "cfg_notice": {
        "de": "Die Datei {path} existiert noch nicht. Sie wird beim ersten Speichern angelegt "
              "(oder sobald der Server einmal gelaufen ist).",
        "en": "The file {path} does not exist yet. It will be created on first save "
              "(or once the server has run once)."},
    "tab_settings": {"de": "Einstellungen", "en": "Settings"},
    "tab_raw": {"de": "Rohdatei", "en": "Raw file"},
    "cfg_save_hint": {"de": "Änderungen greifen nach einem Neustart des Servers.",
                      "en": "Changes take effect after a server restart."},
    "cfg_save_raw_btn": {"de": "Rohdatei speichern", "en": "Save raw file"},
    "cfg_raw_warn": {"de": "Vorsicht: hier wird die Datei 1:1 überschrieben.",
                     "en": "Caution: this overwrites the file verbatim."},
    "cfg_empty": {"de": "Diese Datei enthält noch keine Schlüssel. Nutze den Reiter „Rohdatei“.",
                  "en": "This file has no keys yet. Use the “Raw file” tab."},

    # -- Konto --
    "change_password": {"de": "Passwort ändern", "en": "Change password"},
    "logged_in_as": {"de": "angemeldet als", "en": "signed in as"},
    "current_password": {"de": "Aktuelles Passwort", "en": "Current password"},
    "new_password": {"de": "Neues Passwort", "en": "New password"},
    "repeat_new_password": {"de": "Neues Passwort wiederholen", "en": "Repeat new password"},

    # -- Benutzerverwaltung --
    "users_add_title": {"de": "Neuen Benutzer anlegen", "en": "Add new user"},
    "users_add_pw_ph": {"de": "Passwort (min. 6 Zeichen)", "en": "Password (min. 6 chars)"},
    "users_add_btn": {"de": "Anlegen", "en": "Add"},
    "users_equal_note": {
        "de": "Alle Konten sind gleichberechtigt und dürfen den Server steuern sowie "
              "Benutzer verwalten.",
        "en": "All accounts are equal and may control the server and manage users."},
    "users_you": {"de": "du", "en": "you"},
    "users_new_pw_ph": {"de": "neues Passwort", "en": "new password"},
    "users_reset_btn": {"de": "Zurücksetzen", "en": "Reset"},
    "users_delete_btn": {"de": "Löschen", "en": "Delete"},
    "users_delete_confirm": {"de": "Benutzer {name} wirklich löschen?",
                             "en": "Really delete user {name}?"},

    # -- Flash-Meldungen --
    "csrf_invalid": {"de": "Sicherheits-Token ungültig, bitte erneut versuchen.",
                     "en": "Security token invalid, please try again."},
    "srv_started": {"de": "Server gestartet.", "en": "Server started."},
    "srv_stopped": {"de": "Server gestoppt.", "en": "Server stopped."},
    "srv_stop_failed": {"de": "Server konnte nicht gestoppt werden (läuft noch).",
                        "en": "Server could not be stopped (still running)."},
    "srv_restarted": {"de": "Server neu gestartet.", "en": "Server restarted."},
    "update_started": {
        "de": "Update gestartet – der Server wird dafür gestoppt. Fortschritt siehst du "
              "in den Update-Logs.",
        "en": "Update started — the server will be stopped. Progress shows in the update logs."},
    "update_failed": {"de": "Update-Start fehlgeschlagen: {out}",
                      "en": "Failed to start update: {out}"},
    "unknown_action": {"de": "Unbekannte Aktion.", "en": "Unknown action."},
    "world_saved": {"de": "Welt gespeichert: {res}", "en": "World saved: {res}"},
    "no_message": {"de": "Keine Nachricht eingegeben.", "en": "No message entered."},
    "broadcast_sent": {"de": "Nachricht gesendet.", "en": "Message sent."},
    "save_shutdown_done": {
        "de": "Welt gespeichert, Server wird beendet.",
        "en": "World saved, server is shutting down."},
    "shutdown_nosave": {
        "de": "Server gestoppt. Welt konnte vorher nicht per RCON gespeichert werden (Server nicht erreichbar) – der letzte Auto-Save der Karte gilt.",
        "en": "Server stopped. World could not be saved via RCON beforehand (server unreachable) – the map's last auto-save applies."},
    "unknown_rcon": {"de": "Unbekannte RCON-Aktion.", "en": "Unknown RCON action."},
    "rcon_failed": {"de": "RCON nicht möglich: {err}", "en": "RCON not possible: {err}"},
    "rcon_enabled_gen": {
        "de": "ServerAdminPassword erzeugt (= RCON- und In-Game-Admin-Passwort): {pw} "
              "— bitte notieren. Server neu starten, damit es greift.",
        "en": "ServerAdminPassword generated (= RCON and in-game admin password): {pw} "
              "— please note it. Restart the server for it to take effect."},
    "rcon_enabled_existing": {
        "de": "RCON ist eingerichtet (vorhandenes ServerAdminPassword genutzt).",
        "en": "RCON is set up (using existing ServerAdminPassword)."},
    "pw_wrong_current": {"de": "Aktuelles Passwort ist falsch.",
                         "en": "Current password is wrong."},
    "pw_too_short": {"de": "Neues Passwort muss mindestens {n} Zeichen haben.",
                     "en": "New password must be at least {n} characters."},
    "pw_mismatch": {"de": "Die neuen Passwörter stimmen nicht überein.",
                    "en": "The new passwords do not match."},
    "pw_changed": {"de": "Passwort geändert.", "en": "Password changed."},
    "user_invalid_name": {
        "de": "Ungültiger Benutzername (2–32 Zeichen: Buchstaben, Zahlen, . _ -).",
        "en": "Invalid username (2–32 chars: letters, digits, . _ -)."},
    "user_exists": {"de": "Diesen Benutzer gibt es schon.", "en": "This user already exists."},
    "user_pw_short": {"de": "Passwort muss mindestens {n} Zeichen haben.",
                      "en": "Password must be at least {n} characters."},
    "user_created": {"de": "Benutzer '{name}' angelegt.", "en": "User '{name}' created."},
    "user_not_found": {"de": "Benutzer nicht gefunden.", "en": "User not found."},
    "user_pw_reset": {"de": "Passwort für '{name}' neu gesetzt.",
                      "en": "Password for '{name}' reset."},
    "user_delete_self": {"de": "Du kannst dein eigenes Konto nicht löschen.",
                         "en": "You cannot delete your own account."},
    "user_delete_last": {"de": "Der letzte Benutzer kann nicht gelöscht werden.",
                         "en": "The last user cannot be deleted."},
    "user_deleted": {"de": "Benutzer '{name}' gelöscht.", "en": "User '{name}' deleted."},
    "config_saved": {"de": "Konfiguration gespeichert. Für die Übernahme den Server neu starten.",
                     "en": "Configuration saved. Restart the server to apply."},
    "raw_saved": {"de": "Rohdatei gespeichert. Für die Übernahme den Server neu starten.",
                  "en": "Raw file saved. Restart the server to apply."},
}


def translate(lang, key, **kw):
    if lang not in LANGS:
        lang = DEFAULT_LANG
    entry = TRANSLATIONS.get(key, {})
    text = entry.get(lang) or entry.get(DEFAULT_LANG) or key
    return text.format(**kw) if kw else text
