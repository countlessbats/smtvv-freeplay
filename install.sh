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
#     ./install.sh --no-superjump  # skip the Superjump DLL
#
# Patch flags are passed through to the patcher:
#   --no-essences  --no-heal  --no-mimans  --no-miracles  --no-superjump
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

# Separate our own --no-superjump from the patcher's flags.
PATCH_FLAGS=()
DO_SUPERJUMP=1
for a in "$@"; do
    case "$a" in
        --no-superjump) DO_SUPERJUMP=0 ;;
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

if [ "$DO_SUPERJUMP" = "1" ] && [ -f "$HERE/superjump/xinput1_3.dll" ]; then
    echo "Installing Superjump module (xinput1_3.dll)..."
    cp -f "$HERE/superjump/xinput1_3.dll" "$BIN/xinput1_3.dll"
    echo
    echo "  ----------------------------------------------------------------"
    echo "  Steam Deck / Proton note for SUPERJUMP only:"
    echo "  A Proton DLL override is required for the proxy DLL to load."
    echo "  In Steam: SMT5V -> Properties -> General -> Launch Options, set:"
    echo
    echo '      WINEDLLOVERRIDES="xinput1_3=n,b" %command%'
    echo
    echo "  (The executable patches above work WITHOUT this; it's Superjump-only.)"
    echo "  ----------------------------------------------------------------"
elif [ "$DO_SUPERJUMP" = "0" ]; then
    echo "Skipping Superjump module (--no-superjump)."
fi

echo
echo "Done. Launch the game through Steam as usual."
