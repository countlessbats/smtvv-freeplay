"""
Newborn Clears Compendium: starting a New Game+ with the Newborn method also
empties the Demon Compendium.

Exe: InitRenewalNewGame (the Newborn carry-over) is reached through a 5-byte
jump at the end of its exec thunk. The jump is pointed at a cave that runs
the original and then the game's own compendium reset, which refills the
save data's compendium (SaveData+0x5A8, 1201 records indexed by demon ID)
with default, unregistered records.

Text: the English carry-over lists are updated. Newborn no longer lists the
compendium and says it starts empty; Reborn, which still keeps it and whose
list is "in addition to Newborn", now lists it.
"""

from __future__ import annotations

import os
import struct

import ue_asset
from gameplay_patches import Asm, _jmp_site, _place, off, va

NEWBORN_PAK = "pakchunk94_FreeplayNewborn_P.pak"
NEWBORN_SOURCE_PAK = "pakchunk0-WindowsNoEditor.pak"
INHERIT_TEXT = "Project/Content/L10N/en/Blueprints/Gamedata/BinTable/Inherit/InheritMessage"

RENEWAL_JMP = 0x140CB73E3        # exec thunk: jmp InitRenewalNewGame impl
RENEWAL_IMPL = 0x140B22F20
RENEWAL_IMPL_ORIG = bytes.fromhex("48895c24084889742410")
BOOK_RESET = 0x140B1C260         # resets SaveData+0x5A8 to 1201 default records
BOOK_RESET_ORIG = bytes.fromhex("40534881ecd0000000e842910000488d4c2420")

NEWBORN_OLD = ("The following elements will be carried over:\n　\n- Enemy info\n"
               "- Demon Compendium\n- Unlocked fusions\n- Certain Miracles\n　\n")
NEWBORN_NEW = ("The following elements will be carried over:\n　\n- Enemy info\n"
               "- Unlocked fusions\n- Certain Miracles\n　\n"
               "The Demon Compendium is not carried over.\n　\n")
REBORN_OLD = "- Glory\n　\n"
REBORN_NEW = "- Glory\n- Demon Compendium\n　\n"
REBORN_HEAD = "In addition to the elements from Newborn,"


def patch_newborn(data: bytearray, cave_off: int, cave_end: int) -> int | None:
    o = off(RENEWAL_JMP)
    if data[o] != 0xE9 or RENEWAL_JMP + 5 + struct.unpack_from("<i", data, o + 1)[0] != RENEWAL_IMPL:
        return None
    if data[off(RENEWAL_IMPL):off(RENEWAL_IMPL) + len(RENEWAL_IMPL_ORIG)] != RENEWAL_IMPL_ORIG:
        return None
    if data[off(BOOK_RESET):off(BOOK_RESET) + len(BOOK_RESET_ORIG)] != BOOK_RESET_ORIG:
        return None
    a = Asm(va(cave_off))
    a.raw("48 83 EC 28")                          # sub rsp, 28h
    a.call(RENEWAL_IMPL)
    a.call(BOOK_RESET)
    a.raw("48 83 C4 28 C3")                       # add rsp, 28h; ret
    code = a.build()
    dest = va(cave_off)
    cave_off = _place(data, cave_off, cave_end, code)
    _jmp_site(data, RENEWAL_JMP, dest, 5)
    return cave_off


def _replace_text(pk: ue_asset.Package, old_full: str, old: str, new: str) -> None:
    """Replace `old` with `new` inside the one string that contains old_full."""
    blob = ue_asset.fstring(old_full)
    at = pk.e.find(blob)
    if at < 0 or pk.e.find(blob, at + 1) >= 0:
        raise RuntimeError("carry-over text not found - game update?")
    n = -struct.unpack_from("<i", pk.e, at)[0]
    full = pk.e[at + 4:at + 4 + 2 * n].decode("utf-16-le")[:-1]
    pk.replace(at, ue_asset.fstring(full), ue_asset.fstring(full.replace(old, new, 1)))


def _string_with(pk: ue_asset.Package, needle: str) -> str:
    raw = needle.encode("utf-16-le")
    at = pk.e.find(raw)
    if at < 0:
        raise RuntimeError("carry-over text not found - game update?")
    # walk back to the FString length prefix
    for start in range(at - 4, max(0, at - 4096), -2):
        n = struct.unpack_from("<i", pk.e, start)[0]
        if n < 0 and start + 4 + 2 * -n > at and pk.e[start + 4 + 2 * -n - 2:start + 4 + 2 * -n] == b"\0\0":
            s = pk.e[start + 4:start + 4 + 2 * -n].decode("utf-16-le")[:-1]
            if needle in s:
                return s
    raise RuntimeError("carry-over text not found - game update?")


def edit_inherit_text(uasset: bytes, uexp: bytes) -> tuple[bytes, bytes]:
    pk = ue_asset.Package(uasset, uexp)
    newborn = _string_with(pk, NEWBORN_OLD)
    _replace_text(pk, newborn, NEWBORN_OLD, NEWBORN_NEW)
    reborn = _string_with(pk, REBORN_HEAD)
    if REBORN_OLD not in reborn:
        raise RuntimeError("Reborn carry-over text not as expected - game update?")
    _replace_text(pk, reborn, REBORN_OLD, REBORN_NEW)
    return pk.build()


def build_newborn_pak(game_dir: str, paks_subpath: str, repak: str, run_repak) -> None:
    """Build NEWBORN_PAK in the game's Paks folder. Raises RuntimeError."""
    import shutil
    import tempfile

    paks_dir = os.path.join(game_dir, paks_subpath)
    src = os.path.join(paks_dir, NEWBORN_SOURCE_PAK)
    if not os.path.isfile(src):
        raise RuntimeError(f"{NEWBORN_SOURCE_PAK} not found in {paks_dir}")
    a, e = edit_inherit_text(run_repak(repak, "get", src, INHERIT_TEXT + ".uasset"),
                             run_repak(repak, "get", src, INHERIT_TEXT + ".uexp"))
    staging = tempfile.mkdtemp(prefix="smtvv_newborn_")
    try:
        for entry, blob in ((INHERIT_TEXT + ".uasset", a), (INHERIT_TEXT + ".uexp", e)):
            path = os.path.join(staging, *entry.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(blob)
        out = os.path.join(paks_dir, NEWBORN_PAK)
        tmp = out + ".tmp"
        try:
            run_repak(repak, "pack", "--version", "V11", staging, tmp)
            os.replace(tmp, out)
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
