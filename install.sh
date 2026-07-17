#!/usr/bin/env bash
#
# SMTVV Freeplay - Linux / Steam Deck installer.
#
# Steam Deck runs the same Steam Windows build through Proton, so the patches
# are identical to the Windows version - only the installer differs. Run this in
# Desktop Mode from a terminal (Konsole):
#
#     chmod +x install.sh
#     ./install.sh                 # all patches
#     ./install.sh --no-miracles   # skip a patch (see flags below)
#
# Patch flags are passed through to the patcher:
#   --no-essences  --no-heal  --no-mimans  --no-miracles
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
        /run/media/*/SteamLibrary/steamapps/common/SMT5V \
        /run/media/*/*/steamapps/common/SMT5V \
        /run/media/*/*/SteamLibrary/steamapps/common/SMT5V \
        "$HERE/.." "$HERE/../.." ; do
        if [ -f "$c/Project/Binaries/Win64/$EXE" ]; then
            ( cd "$c" && pwd ); return 0
        fi
    done
    return 1
}

GAMEDIR="$(find_game || true)"
if [ -z "${GAMEDIR:-}" ]; then
    echo "Could not find SMT5V automatically."
    echo "In Steam: right-click SMT5V -> Properties -> Installed Files -> Browse,"
    echo "then paste that folder's path here (or the path to your SMT5V folder)."
    read -r -p "SMT5V folder: " GAMEDIR
    GAMEDIR="${GAMEDIR/#\~/$HOME}"
    GAMEDIR="${GAMEDIR%/}"
fi

BIN="$GAMEDIR/Project/Binaries/Win64"
if [ ! -f "$BIN/$EXE" ]; then
    echo "ERROR: $EXE not found under:"
    echo "  $BIN"
    exit 1
fi

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
    echo "ERROR: python3 not found. In Desktop Mode it is normally available;"
    echo "       open Konsole and run this script there."
    exit 1
fi

PATCH_FLAGS=()
for a in "$@"; do
    case "$a" in
        --no-superjump)
            echo "Note: Superjump has been removed; ignoring deprecated --no-superjump."
            ;;
        *) PATCH_FLAGS+=("$a") ;;
    esac
done

echo "Game: $GAMEDIR"
echo

"$PY" "$HERE/patch_smtvv_freeplay.py" --game-dir "$GAMEDIR" "${PATCH_FLAGS[@]}"

if [ -f "$BIN/$EXE.patched" ]; then
    if [ ! -f "$BIN/$EXE.original" ]; then
        echo "Backing up original executable..."
        cp -p "$BIN/$EXE" "$BIN/$EXE.original"
    fi
    echo "Installing patched executable..."
    cp -f "$BIN/$EXE.patched" "$BIN/$EXE"
fi

if [ -f "$BIN/xinput1_3.dll" ]; then
    if command -v sha256sum >/dev/null 2>&1; then
        existing_hash="$(sha256sum "$BIN/xinput1_3.dll" | awk '{print tolower($1)}')"
        if [ "$existing_hash" = "$LEGACY_SUPERJUMP_SHA256" ]; then
            echo "Removing legacy Superjump module (xinput1_3.dll)..."
            rm -f "$BIN/xinput1_3.dll"
        else
            echo "NOTE: Found xinput1_3.dll, but it does not match the old Superjump module."
            echo "      Leaving it in place."
        fi
    else
        echo "NOTE: Found xinput1_3.dll, but sha256sum is unavailable."
        echo "      Leaving it in place."
    fi
fi

echo
echo "Done. Launch the game through Steam as usual."
