#!/usr/bin/env bash
# Aktualisiert den ARK-Dedicated-Server via SteamCMD (AppID 376030).
# Wird vom Panel über ark-update.service (oneshot) aufgerufen.
# Der Server wird durch die Service-Definition vorher gestoppt.
set -euo pipefail

APPID=376030
INSTALL_DIR="${INSTALL_DIR:-$HOME/arkserver}"
STEAMCMD="${STEAMCMD:-/usr/games/steamcmd}"
BACKUP_DIR="$HOME/backups"
KEEP=7

echo "[$(date '+%F %T')] Update gestartet."

# --- Spielstände sichern -----------------------------------------------------
SAVED="$INSTALL_DIR/ShooterGame/Saved"
if [ -d "$SAVED" ]; then
    mkdir -p "$BACKUP_DIR"
    TS="$(date +%Y%m%d-%H%M%S)"
    echo "Sichere Spielstände nach saved-$TS.tar.gz ..."
    tar czf "$BACKUP_DIR/saved-$TS.tar.gz" -C "$INSTALL_DIR/ShooterGame" Saved || \
        echo "WARN: Backup nicht vollständig."
    ls -1t "$BACKUP_DIR"/saved-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | \
        xargs -r rm -f
fi

# --- Update ------------------------------------------------------------------
echo "Führe SteamCMD-Update aus (AppID $APPID) ..."
"$STEAMCMD" +force_install_dir "$INSTALL_DIR" \
    +login anonymous +app_update "$APPID" validate +quit

# --- steamclient.so für das SDK verlinken (häufige Fehlerquelle) --------------
SC="$(find "$HOME/.steam" "$HOME/Steam" "$INSTALL_DIR" -name steamclient.so 2>/dev/null | head -n1 || true)"
if [ -n "$SC" ]; then
    mkdir -p "$HOME/.steam/sdk64"
    ln -sf "$SC" "$HOME/.steam/sdk64/steamclient.so"
    echo "steamclient.so verlinkt: $SC"
fi

echo "[$(date '+%F %T')] Update abgeschlossen."
