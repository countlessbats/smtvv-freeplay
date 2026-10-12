"""
Skip Intro: no logo or warning screens, no opening movie, and no "press any
button" screen -- the game boots straight to the title menu.

Two Blueprint assets are extracted from the player's own pakchunk0, edited in
place (same size) and repacked as a small override pak:

  WBP_LogoScreen   the logo sequence starts at its last, invisible hold step
                   and finishes when that hold ends, skipping every logo and
                   warning fade. The hold keeps the logo level up for a few
                   seconds so Steam Input has attached the controller before
                   the title menu reads it.
  BP_LogoGameMode  SetRequestTitleMovie(true) -> (false), so the title level
                   opens its menu directly, as it does when returning to the
                   title from in-game
"""

from __future__ import annotations

import os
import struct

BOOT_PAK = "pakchunk97_FreeplayBoot_P.pak"
LOGO_ROOT = "Project/Content/Blueprints/Logo/"
LOGO_SCREEN = LOGO_ROOT + "WBP_LogoScreen"
LOGO_GAMEMODE = LOGO_ROOT + "BP_LogoGameMode"

# Construct: culture check, then Let(Progress, IntConst(4)).
#   Jump(->5739) | Let(Progress, IntConst(4))
LOGO_START = bytes.fromhex(
    "066b1600000f0100000069000000000000000500000001010000006900000000000000"
    "050000001d04000000")
LOGO_START_JUMP_OFF = 1         # Japanese-culture branch: also set Progress
LOGO_START_JUMP_TO = 1354
LOGO_START_STEP_OFF = 40        # first step of the sequence
LOGO_HOLD_STEP = 13             # "ProgressTime >= 2 or skip" hold, no fades

# Step 13: if ProgressTime >= FloatConst(2) or bSkipRequest -> Jump(->833)
LOGO_HOLD = bytes.fromhex(
    "14000100000021000000080000000100000068e8ffffff01010000006a00000000000000"
    "050000001e00000040161400010000001d000000040000000100000068eaffffff000100"
    "0000210000000800000001000000010100000019000000000000000500000016076b1600"
    "0000010000001d00000004000000010000000641030000")
LOGO_HOLD_TIME_OFF = 0x29
LOGO_HOLD_TIME = 4.0            # seconds before the title menu opens
LOGO_HOLD_JUMP_OFF = 0x7F
LOGO_DONE_ENTRY = 5712          # LetBool(bComplete, true)

# CallMath(SetRequestTitleMovie, True)
TITLE_MOVIE_REQ = bytes.fromhex("68e3ffffff2716")
TITLE_MOVIE_ARG_OFF = 5
EX_FALSE = 0x28


def _patch_once(data: bytearray, pattern: bytes, what: str) -> int:
    pos = data.find(pattern)
    if pos < 0 or data.find(pattern, pos + 1) >= 0:
        raise RuntimeError(f"{what} not recognised - game update?")
    return pos


def edit_logo_screen(uexp: bytes) -> bytes:
    data = bytearray(uexp)
    pos = _patch_once(data, LOGO_START, "logo screen script")
    struct.pack_into("<i", data, pos + LOGO_START_JUMP_OFF, LOGO_START_JUMP_TO)
    struct.pack_into("<i", data, pos + LOGO_START_STEP_OFF, LOGO_HOLD_STEP)
    pos = _patch_once(data, LOGO_HOLD, "logo screen script")
    struct.pack_into("<f", data, pos + LOGO_HOLD_TIME_OFF, LOGO_HOLD_TIME)
    struct.pack_into("<i", data, pos + LOGO_HOLD_JUMP_OFF, LOGO_DONE_ENTRY)
    return bytes(data)


def edit_logo_gamemode(uexp: bytes) -> bytes:
    data = bytearray(uexp)
    pos = _patch_once(data, TITLE_MOVIE_REQ, "logo game mode script")
    data[pos + TITLE_MOVIE_ARG_OFF] = EX_FALSE
    return bytes(data)


def build_boot_pak(game_dir: str, paks_subpath: str, source_pak: str,
                   repak: str, run_repak) -> None:
    """Build BOOT_PAK in the game's Paks folder. Raises RuntimeError."""
    import shutil
    import tempfile

    paks_dir = os.path.join(game_dir, paks_subpath)
    src = os.path.join(paks_dir, source_pak)
    if not os.path.isfile(src):
        raise RuntimeError(f"{source_pak} not found in {paks_dir}")

    def get(entry: str) -> bytes:
        return run_repak(repak, "get", src, entry)

    files = {
        LOGO_SCREEN + ".uasset": get(LOGO_SCREEN + ".uasset"),
        LOGO_SCREEN + ".uexp": edit_logo_screen(get(LOGO_SCREEN + ".uexp")),
        LOGO_GAMEMODE + ".uasset": get(LOGO_GAMEMODE + ".uasset"),
        LOGO_GAMEMODE + ".uexp": edit_logo_gamemode(get(LOGO_GAMEMODE + ".uexp")),
    }

    staging = tempfile.mkdtemp(prefix="smtvv_boot_")
    try:
        for entry, blob in files.items():
            path = os.path.join(staging, *entry.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(blob)
        out = os.path.join(paks_dir, BOOT_PAK)
        tmp = out + ".tmp"
        try:
            run_repak(repak, "pack", "--version", "V11", staging, tmp)
            os.replace(tmp, out)
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
