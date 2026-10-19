#!/usr/bin/env bash
#
# SMTVV Freeplay - Linux / Steam Deck installer.
#
# Steam Deck runs the same Steam Windows build through Proton, so the patches
# are identical to the Windows version - only the installer differs. Run this in
# Desktop Mode from a terminal (Konsole):
#
#     chmod +x install.sh
#     ./install.sh
#
# It asks about each mod in turn. Run it again later to add or remove mods.
# Optional: ./install.sh /path/to/SMT5V   (skips the automatic search)
#
# Scripted use: patch flags skip the questions and are passed to the patcher
# (every mod is installed unless switched off):
#   --no-essences  --no-heal  --no-mimans  --no-miracles  --no-compendium
#   --no-refill  --no-jump  --no-shop  --no-magatsuhi  --no-intro  --no-masakado
#   --no-newborn
#   --stockpile    (Stockpile instead of Battle Refill)
#   --autosave-slot N   (save to slot N, 1-20, after every battle; off by default)
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

# Accepts the SMT5V folder or its Project/Binaries/Win64 folder.
normalize_dir() {
    local d="$1"
    d="${d#\"}"; d="${d%\"}"; d="${d#\'}"; d="${d%\'}"
    d="${d/#\~/$HOME}"
    d="${d%/}"
    case "$d" in */Project/Binaries/Win64) d="${d%/Project/Binaries/Win64}" ;; esac
    printf '%s' "$d"
}

PATCH_FLAGS=()
GAMEDIR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --no-superjump) PATCH_FLAGS+=("--no-jump") ;;
        --autosave-slot) PATCH_FLAGS+=("$1" "${2:-}"); shift ;;
        -*) PATCH_FLAGS+=("$1") ;;
        *) GAMEDIR="$(normalize_dir "$1")" ;;
    esac
    shift
done

if [ -z "$GAMEDIR" ]; then
    GAMEDIR="$(find_game || true)"
fi
while [ -z "$GAMEDIR" ] || [ ! -f "$GAMEDIR/Project/Binaries/Win64/$EXE" ]; do
    if [ -n "$GAMEDIR" ]; then
        echo "That folder doesn't contain Project/Binaries/Win64/$EXE."
    else
        echo "Could not find SMT5V automatically."
    fi
    echo "In Steam: right-click SMT5V -> Properties -> Installed Files -> Browse,"
    echo "then paste that folder's path here (or press Enter to cancel)."
    read -r -p "SMT5V folder: " GAMEDIR
    [ -z "$GAMEDIR" ] && { echo "Cancelled."; exit 1; }
    GAMEDIR="$(normalize_dir "$GAMEDIR")"
done
GAMEDIR="$(cd "$GAMEDIR" && pwd)"
BIN="$GAMEDIR/Project/Binaries/Win64"
PAKS="$GAMEDIR/Project/Content/Paks"
STATE="$BIN/Freeplay.features"

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
    echo "ERROR: python3 not found. In Desktop Mode it is normally available;"
    echo "       open Konsole and run this script there."
    exit 1
fi

echo "============================================================"
echo " SMT5V: Vengeance - Freeplay Mod Installer"
echo "============================================================"
echo "Game: $GAMEDIR"
echo

uninstall_all() {
    bash "$HERE/uninstall.sh" "$GAMEDIR"
    exit 0
}

# --- Questions (skipped when patch flags are given) ---
if [ ${#PATCH_FLAGS[@]} -eq 0 ]; then
    BOOL_KEYS=(essences heal mimans miracles compendium jump shop magatsuhi intro masakado newborn)
    declare -A DESC=(
        [essences]="Reusable Essences (essences not consumed)"
        [heal]="Leyline Auto-Heal (full HP/MP on leyline use)"
        [mimans]="Miman Reveal (all miman positions shown on map)"
        [miracles]="NG+ Miracles (unlock NG+ miracles early)"
        [compendium]="Free Compendium (compendium summons cost nothing)"
        [jump]="Superjump (hold jump to rise, faster air control)"
        [shop]="Free Growth Items (Gospels, Grimoires, Sutras, Balms, Incenses free in shop)"
        [magatsuhi]="Full Magatsuhi (gauge full at the start of every battle)"
        [intro]="Skip Intro (no logos or opening movie; boot to title menu)"
        [masakado]="Masakado Unlock (powered-up Masakado fight without the Kiou Sword)"
        [newborn]="Newborn Clears Compendium (NG+ Newborn starts with an empty compendium)"
    )
    declare -A INST=()
    INST_ITEMS=""
    INST_AUTOSAVE=""
    if [ -f "$STATE" ]; then
        while IFS='=' read -r k v; do
            k="${k%$'\r'}"; v="${v%$'\r'}"
            case "$k" in
                itemhacks) case "$v" in refill|stockpile) INST_ITEMS="$v" ;; esac ;;
                autosave) [[ "$v" =~ ^([1-9]|1[0-9]|20)$ ]] && INST_AUTOSAVE="$v" ;;
                *) for b in "${BOOL_KEYS[@]}"; do [ "$k" = "$b" ] && [ "$v" = "1" ] && INST[$k]=1; done ;;
            esac
        done < "$STATE"
    fi
    NINST=${#INST[@]}
    [ -n "$INST_ITEMS" ] && NINST=$((NINST + 1))
    [ -n "$INST_AUTOSAVE" ] && NINST=$((NINST + 1))
    NALL=13

    # An install that predates the feature record.
    LEGACY=""
    if [ ! -f "$STATE" ]; then
        if [ -f "$BIN/$EXE.original" ] && ! cmp -s "$BIN/$EXE" "$BIN/$EXE.original"; then
            LEGACY=1
        fi
        for p in 93_FreeplayStockpile 94_FreeplayNewborn 95_FreeplayMap 96_FreeplayQuest \
                 97_FreeplayBoot 98_FreeplayShop 99_NGPlusMiracles; do
            [ -f "$PAKS/pakchunk${p}_P.pak" ] && LEGACY=1
        done
    fi

    if [ "$NINST" -ge "$NALL" ]; then
        echo "All mods in this pack are currently installed."
        while true; do
            read -r -p "Uninstall all? Choose N to list each for individual uninstall. [y/n]: " A
            case "$A" in [yY]) uninstall_all ;; [nN]) break ;; esac
        done
    elif [ "$NINST" -gt 0 ]; then
        echo "Some mods from this pack are installed (marked [installed] below)."
        while true; do
            read -r -p "Uninstall all of them first? [y/N]: " A
            case "$A" in [yY]) uninstall_all ;; ""|[nN]) break ;; esac
        done
    elif [ -n "$LEGACY" ]; then
        echo "An earlier version of this pack is installed. It did not record which"
        echo "mods it installed."
        while true; do
            read -r -p "Uninstall it? Choose N to choose mods now. [y/N]: " A
            case "$A" in [yY]) uninstall_all ;; ""|[nN]) break ;; esac
        done
    else
        echo "No mods from this pack are installed. Choose the ones you want:"
    fi
    echo

    declare -A SEL=()
    ask() {
        local k="$1" q def A
        if [ -n "${INST[$k]:-}" ]; then
            q="${DESC[$k]} [installed] - keep? [Y/n]: "; def=y
        else
            q="${DESC[$k]} - install? [y/N]: "; def=n
        fi
        while true; do
            read -r -p "  $q" A
            A="${A:-$def}"
            case "$A" in [yY]) SEL[$k]=1; return ;; [nN]) return ;; esac
        done
    }
    ask_items() {
        local q def A
        echo "  Item Hacks: [R] Battle Refill (battle items topped up at every battle start)"
        echo "              [S] Stockpile (stack battle items to 99; normal limit per battle)"
        echo "              [N] Neither"
        case "$INST_ITEMS" in
            refill) q="Item Hacks [installed: Battle Refill] - keep? [R/s/n]: "; def=r ;;
            stockpile) q="Item Hacks [installed: Stockpile] - keep? [r/S/n]: "; def=s ;;
            *) q="Item Hacks? [r/s/N]: "; def=n ;;
        esac
        while true; do
            read -r -p "  $q" A
            A="${A:-$def}"
            case "$A" in
                [rR]) SEL_ITEMS=refill; return ;;
                [sS]) SEL_ITEMS=stockpile; return ;;
                [nN]) SEL_ITEMS=none; return ;;
            esac
        done
    }
    ask_autosave() {
        local q A
        echo "  Autosave After Battle: saves to one slot after every battle,"
        echo "                         overwriting that slot each time."
        if [ -n "$INST_AUTOSAVE" ]; then
            q="Autosave After Battle [installed: slot $INST_AUTOSAVE] - keep? Enter for slot $INST_AUTOSAVE, another slot (1-20), or N to remove: "
        else
            q="Autosave After Battle - install? Enter a save slot (1-20), or blank to skip: "
        fi
        while true; do
            read -r -p "  $q" A
            if [ -z "$A" ]; then SEL_AUTOSAVE="$INST_AUTOSAVE"; return; fi
            case "$A" in [nN]) SEL_AUTOSAVE=""; return ;; esac
            if [[ "$A" =~ ^([1-9]|1[0-9]|20)$ ]]; then SEL_AUTOSAVE="$A"; return; fi
            echo "  Please enter a slot number from 1 to 20."
        done
    }

    SEL_ITEMS=none
    SEL_AUTOSAVE=""
    for k in essences heal mimans miracles compendium; do ask "$k"; done
    ask_items
    for k in jump shop magatsuhi intro masakado newborn; do ask "$k"; done
    ask_autosave

    NSEL=0
    for k in "${BOOL_KEYS[@]}"; do
        if [ -n "${SEL[$k]:-}" ]; then NSEL=$((NSEL + 1)); else PATCH_FLAGS+=("--no-$k"); fi
    done
    case "$SEL_ITEMS" in
        refill) NSEL=$((NSEL + 1)) ;;
        stockpile) NSEL=$((NSEL + 1)); PATCH_FLAGS+=("--stockpile") ;;
        none) PATCH_FLAGS+=("--no-refill") ;;
    esac
    if [ -n "$SEL_AUTOSAVE" ]; then
        NSEL=$((NSEL + 1)); PATCH_FLAGS+=("--autosave-slot" "$SEL_AUTOSAVE")
    fi
    if [ "$NSEL" -eq 0 ]; then
        echo
        echo "No mods chosen."
        if [ "$NINST" -gt 0 ] || [ -n "$LEGACY" ]; then uninstall_all; fi
        exit 0
    fi
fi

# Zip extraction can drop the exec bit on the bundled repak tool.
if [ -f "$HERE/repak/linux64/repak" ]; then
    chmod +x "$HERE/repak/linux64/repak" 2>/dev/null || true
fi

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
if [ -f "$BIN/Freeplay.features.new" ]; then
    mv -f "$BIN/Freeplay.features.new" "$BIN/Freeplay.features"
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
echo "To change or remove mods, run ./install.sh again."
