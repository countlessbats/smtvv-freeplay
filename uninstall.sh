#!/usr/bin/env bash
#
# SMTVV Freeplay - Linux / Steam Deck uninstaller.
# Restores the original executable and removes the Superjump DLL.
#
set -euo pipefail

EXE="SMT5V-Win64-Shipping.exe"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

find_game() {
    local c
    for c in \
        "$HOME/.local/share/Steam/steamapps/common/SMT5V" \
        "$HOME/.steam/steam/steamapps/common/SMT5V" \
        "$HOME/.steam/root/steamapps/common/SMT5V" \
        /run/media/*/steamapps/common/SMT5V \
        "$HERE/.." "$HERE/../.." ; do
        if [ -f "$c/Project/Binaries/Win64/$EXE" ]; then
            ( cd "$c" && pwd ); return 0
        fi
    done
    return 1
}

GAMEDIR="$(find_game || true)"
if [ -z "${GAMEDIR:-}" ]; then
    read -r -p "SMT5V folder: " GAMEDIR
    GAMEDIR="${GAMEDIR/#\~/$HOME}"
    GAMEDIR="${GAMEDIR%/}"
fi

BIN="$GAMEDIR/Project/Binaries/Win64"

if [ -f "$BIN/$EXE.original" ]; then
    echo "Restoring original executable..."
    cp -f "$BIN/$EXE.original" "$BIN/$EXE"
else
    echo "No backup found. Use Steam -> Properties -> Installed Files ->"
    echo "Verify integrity of game files to restore the executable."
fi

if [ -f "$BIN/xinput1_3.dll" ]; then
    echo "Removing Superjump module (xinput1_3.dll)..."
    rm -f "$BIN/xinput1_3.dll"
fi

echo "Done. (You can also remove the WINEDLLOVERRIDES launch option.)"
