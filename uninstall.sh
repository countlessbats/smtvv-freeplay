#!/usr/bin/env bash
#
# SMTVV Freeplay - Linux / Steam Deck uninstaller.
# Restores the original executable and removes the legacy Superjump DLL.
#
set -euo pipefail

EXE="SMT5V-Win64-Shipping.exe"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEGACY_SUPERJUMP_SHA256="4d51dc377c15006ee4903de265ccda3514900a059d2019498b66ee9dcc56b819"

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

MIRACLE_PAK="$GAMEDIR/Project/Content/Paks/pakchunk99_NGPlusMiracles_P.pak"
if [ -f "$MIRACLE_PAK" ]; then
    echo "Removing NG+ miracle data pak..."
    rm -f "$MIRACLE_PAK"
fi

SHOP_PAK="$GAMEDIR/Project/Content/Paks/pakchunk98_FreeplayShop_P.pak"
if [ -f "$SHOP_PAK" ]; then
    echo "Removing shop data pak..."
    rm -f "$SHOP_PAK"
fi

BOOT_PAK="$GAMEDIR/Project/Content/Paks/pakchunk97_FreeplayBoot_P.pak"
if [ -f "$BOOT_PAK" ]; then
    echo "Removing intro data pak..."
    rm -f "$BOOT_PAK"
fi

QUEST_PAK="$GAMEDIR/Project/Content/Paks/pakchunk96_FreeplayQuest_P.pak"
if [ -f "$QUEST_PAK" ]; then
    echo "Removing quest data pak..."
    rm -f "$QUEST_PAK"
fi

if [ -f "$BIN/xinput1_3.dll" ]; then
    if command -v sha256sum >/dev/null 2>&1; then
        existing_hash="$(sha256sum "$BIN/xinput1_3.dll" | awk '{print tolower($1)}')"
        if [ "$existing_hash" = "$LEGACY_SUPERJUMP_SHA256" ]; then
            echo "Removing legacy Superjump module (xinput1_3.dll)..."
            rm -f "$BIN/xinput1_3.dll"
        else
            echo "Found xinput1_3.dll, but it does not match the old Superjump module."
            echo "Leaving it in place."
        fi
    else
        echo "Found xinput1_3.dll, but sha256sum is unavailable. Leaving it in place."
    fi
fi

echo "Done. If you previously added WINEDLLOVERRIDES for Superjump, remove that launch option."
