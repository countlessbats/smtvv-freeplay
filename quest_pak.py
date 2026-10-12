"""
Masakado Unlock: Masakado's powered-up fight is offered without the Kiou
Sword.

Masakado's sub-quest script (MM_M063_EM2170, in the player's own pakchunk3)
checks ItemIsHave(PowerUpItemId = Kiou Sword) in three places before playing
the "strong power from within the Kiou Sword" scene that leads to his
powered-up battle. Each check is a JumpIfNot; the edit points its target at
the very next instruction, so the script continues as if the sword were held.
The asset is edited in place (same size) and repacked as a small override pak.
"""

from __future__ import annotations

import os
import struct

QUEST_PAK = "pakchunk96_FreeplayQuest_P.pak"
QUEST_SOURCE_PAK = "pakchunk3-WindowsNoEditor.pak"
MASAKADO = "Project/Content/Blueprints/Event/Script/SubMission/M063/MM_M063_EM2170"

# LetBool(local, CallMath(ItemIsHave, InstVar(PowerUpItemId)))
# JumpIfNot(->target, local)
SWORD_CHECKS = [
    # (instruction bytes, next instruction offset)
    ("140001000000f000000002000000010000006830ffffff0101000000bb020000000000003c"
     "0000001607711300000001000000f00000000200000001000000", 20841),
    ("140001000000f000000000000000010000006830ffffff0101000000bb020000000000003c"
     "0000001607c05400000001000000f00000000000000001000000", 58157),
    ("140001000000f000000003000000010000006830ffffff0101000000bb020000000000003c"
     "000000160719f300000001000000f00000000300000001000000", 61646),
]
JUMP_TARGET_OFF = 0x2A


def edit_masakado(uexp: bytes) -> bytes:
    data = bytearray(uexp)
    for code, nxt in SWORD_CHECKS:
        pattern = bytes.fromhex(code)
        pos = data.find(pattern)
        if pos < 0 or data.find(pattern, pos + 1) >= 0:
            raise RuntimeError("Masakado quest script not recognised - game update?")
        struct.pack_into("<I", data, pos + JUMP_TARGET_OFF, nxt)
    return bytes(data)


def build_quest_pak(game_dir: str, paks_subpath: str, repak: str, run_repak) -> None:
    """Build QUEST_PAK in the game's Paks folder. Raises RuntimeError."""
    import shutil
    import tempfile

    paks_dir = os.path.join(game_dir, paks_subpath)
    src = os.path.join(paks_dir, QUEST_SOURCE_PAK)
    if not os.path.isfile(src):
        raise RuntimeError(f"{QUEST_SOURCE_PAK} not found in {paks_dir}")

    def get(entry: str) -> bytes:
        return run_repak(repak, "get", src, entry)

    files = {
        MASAKADO + ".uasset": get(MASAKADO + ".uasset"),
        MASAKADO + ".uexp": edit_masakado(get(MASAKADO + ".uexp")),
    }

    staging = tempfile.mkdtemp(prefix="smtvv_quest_")
    try:
        for entry, blob in files.items():
            path = os.path.join(staging, *entry.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(blob)
        out = os.path.join(paks_dir, QUEST_PAK)
        tmp = out + ".tmp"
        try:
            run_repak(repak, "pack", "--version", "V11", staging, tmp)
            os.replace(tmp, out)
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
