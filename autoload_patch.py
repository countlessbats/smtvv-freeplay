"""
Auto Load: on the first boot of a session the game goes straight into the most
recent save, without showing the title menu.

The title level asks IsRequestedTitleMovie() once, before any title UI exists.
Its "requested" branch is redirected (data pak) to the level's own
"load the game map" step -- the step that normally runs after a save has been
loaded from the title. The executable hook on IsRequestedTitleMovie loads the
newest regular save (reloading the save headers first) and answers "requested"
when that succeeds; otherwise, and on every later visit to the title, it
answers "not requested", so the title menu opens as usual. The title movie
screen is therefore never shown while Auto Load is installed.
"""

from __future__ import annotations

import os
import struct

import gameplay_patches as gp
from gameplay_patches import Asm, _jmp_site, _place, off, va

# ---------------------------------------------------------------- executable
TITLE_MOVIE_IMPL  = 0x140B8A200   # IsRequestedTitleMovie(): movzx eax,[flag]; ret
TITLE_MOVIE_ORIG  = bytes.fromhex("0fb60519737703c3")
LOAD_HEADERS      = 0x140B6E860   # LoadAllSaveDataHeader(bool)
GET_NEWEST_SLOT   = 0x140B6DDB0   # GetMaxDateTimeSlotIndex() -> int
LOAD_SLOT         = 0x140B6E6A0   # Load(slot) -> bool (synchronous)

SAVE_HEADERS      = 0x1443005B0   # header array: 0x70-byte entries
SAVE_HEADER_NUM   = 0x1443005B8
SAVE_HEADER_SIZE  = 0x70
HDR_USED, HDR_SLOT, HDR_INHERIT = 0x00, 0x04, 0x50

STATE             = 0x1549A9801   # 0 = first title visit pending, 2 = done
REFOCUS_ARMED     = 0x1549A9802   # 1 = refocus once the game next reads input

# The field comes up with the controller reported as disconnected; the window
# refocus is therefore deferred to the first Blueprint input check after the
# load, when the game is running and reading the pad.
PAD_CHECK_CALL    = 0x140CFDC1E   # IsActionPadCheckCore thunk: call impl
PAD_CHECK_IMPL    = 0x140A849C0
CAVE2_OFF, CAVE2_END = 0x503310, 0x503400   # spare 0xCC padding in .rdata


def patch_autoload(data: bytearray, cave_off: int, cave_end: int) -> int | None:
    if bytes(data[off(TITLE_MOVIE_IMPL):off(TITLE_MOVIE_IMPL) + 8]) != TITLE_MOVIE_ORIG:
        return None
    o = off(PAD_CHECK_CALL)
    if data[o] != 0xE8 or PAD_CHECK_CALL + 5 + int.from_bytes(data[o + 1:o + 5], "little", signed=True) != PAD_CHECK_IMPL:
        return None
    if any(b != 0xCC for b in data[CAVE2_OFF:CAVE2_END]):
        return None
    cave_off = gp.emit_refocus_thread(data, cave_off, cave_end)

    def u32(v): return struct.pack("<I", v).hex()

    a = Asm(va(cave_off))
    a._rel("8A 05", STATE).raw("84 C0").jne("no")
    a.raw("B0 02")._rel("88 05", STATE)
    a.raw("53 48 83 EC 20")                       # rsp now 16-byte aligned
    a.raw("B1 01").call(LOAD_HEADERS)
    a.call(GET_NEWEST_SLOT).raw("89 C3")          # ebx = newest slot
    a._rel("48 8B 05", SAVE_HEADERS)
    a._rel("48 63 0D", SAVE_HEADER_NUM)
    a.raw("48 85 C9").jle("fail")
    a.label("scan")
    a.raw("83 78" + "%02x" % HDR_USED + "01").jne("next")
    a.raw("39 58" + "%02x" % HDR_SLOT).jne("next")
    a.raw("80 78" + "%02x" % HDR_INHERIT + "00").jne("fail")    # NG+ clear data
    a.jmp("found")
    a.label("next")
    a.raw("48 05" + u32(SAVE_HEADER_SIZE) + "48 FF C9").jne("scan")
    a.jmp("fail")
    a.label("found")
    a.raw("89 D9").call(LOAD_SLOT).raw("84 C0").je("fail")
    a.raw("B0 01")._rel("88 05", gp.REFOCUS_DONE)   # title refocus not needed
    a._rel("88 05", REFOCUS_ARMED)
    a.raw("48 83 C4 20 5B B0 01 C3")              # "requested": load the map
    a.label("fail")
    a.raw("48 83 C4 20 5B")
    a.label("no")
    a.raw("31 C0 C3")

    dest = va(cave_off)
    cave_off = _place(data, cave_off, cave_end, a.build())
    _jmp_site(data, TITLE_MOVIE_IMPL, dest, 8)

    # First input check after an automatic load: refocus the window.
    b = Asm(va(CAVE2_OFF))
    b._rel("8A 05", REFOCUS_ARMED).raw("84 C0").je("tail")
    b.raw("30 C0")._rel("88 05", REFOCUS_ARMED)
    b.raw("51 52 41 50 41 51 48 83 EC 08")
    gp.start_refocus_thread(b)
    b.raw("48 83 C4 08 41 59 41 58 5A 59")
    b.label("tail")
    b.jmp(PAD_CHECK_IMPL)
    dest2 = va(CAVE2_OFF)
    _place(data, CAVE2_OFF, CAVE2_END, b.build())
    data[o + 1:o + 5] = (dest2 - (PAD_CHECK_CALL + 5)).to_bytes(4, "little", signed=True)
    return cave_off


# ---------------------------------------------------------------- data pak
AUTOLOAD_PAK = "pakchunk95_FreeplayAutoLoad_P.pak"
LV_TITLE = "Project/Content/Level/Title/LV_Title"

# LetBool(local, CallMath(IsRequestedTitleMovie)); JumpIfNot(->1842, local);
# Jump(->15)  (15 = play the title movie)
TITLE_BRANCH = bytes.fromhex(
    "1400010000003c000000000000000100000068bfffffff16073207000000010000003c00"
    "00000000000001000000060f000000")
TITLE_BRANCH_JUMP_OFF = len(TITLE_BRANCH) - 4
LOAD_MAP_ENTRY = 4399            # GetMapCommon -> BPI_LoadMap(true)


def edit_lv_title(uexp: bytes) -> bytes:
    data = bytearray(uexp)
    pos = data.find(TITLE_BRANCH)
    if pos < 0 or data.find(TITLE_BRANCH, pos + 1) >= 0:
        raise RuntimeError("title level script not recognised - game update?")
    struct.pack_into("<I", data, pos + TITLE_BRANCH_JUMP_OFF, LOAD_MAP_ENTRY)
    return bytes(data)


def build_autoload_pak(game_dir: str, paks_subpath: str, source_pak: str,
                       repak: str, run_repak) -> None:
    """Build AUTOLOAD_PAK in the game's Paks folder. Raises RuntimeError."""
    import shutil
    import tempfile

    paks_dir = os.path.join(game_dir, paks_subpath)
    src = os.path.join(paks_dir, source_pak)
    if not os.path.isfile(src):
        raise RuntimeError(f"{source_pak} not found in {paks_dir}")

    files = {
        LV_TITLE + ".umap": run_repak(repak, "get", src, LV_TITLE + ".umap"),
        LV_TITLE + ".uexp": edit_lv_title(run_repak(repak, "get", src, LV_TITLE + ".uexp")),
    }
    staging = tempfile.mkdtemp(prefix="smtvv_autoload_")
    try:
        for entry, blob in files.items():
            path = os.path.join(staging, *entry.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(blob)
        out = os.path.join(paks_dir, AUTOLOAD_PAK)
        tmp = out + ".tmp"
        try:
            run_repak(repak, "pack", "--version", "V11", staging, tmp)
            os.replace(tmp, out)
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
