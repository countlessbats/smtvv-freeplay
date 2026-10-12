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

# Booting straight into a save happens before the controller is visible to
# XInput, so the game starts with it marked disconnected. After the load a
# thread waits (up to 30 s) for a controller to answer XInputGetState and then
# runs the window refocus, which makes the game look for controllers again.
# Timestamps of each step are kept in spare bytes for diagnosis.
IAT_GET_TICK_COUNT64 = 0x1549AED78
PAD_POLL_MS, PAD_POLL_COUNT = 100, 300
LOG_LOAD, LOG_PAD, LOG_DONE, LOG_LEFT = 0x1549A9810, 0x1549A9818, 0x1549A9820, 0x1549A9828
CAVE2_OFF, CAVE2_END = 0x503310, 0x503400   # spare 0xCC padding in .rdata


def emit_pad_wait(data: bytearray) -> tuple[int, int]:
    """Emit the pad-wait thread and a starter for it in CAVE2.
    Returns (thread VA, starter VA); the starter is called with rsp = 8 mod 16."""
    def u32(v): return struct.pack("<I", v).hex()

    t = Asm(va(CAVE2_OFF))
    t.raw("53 56 48 83 EC 38")
    t._rel("FF15", IAT_GET_TICK_COUNT64)._rel("48 89 05", LOG_LOAD)
    t.raw("BE" + u32(PAD_POLL_COUNT))
    t.label("poll").raw("31 DB")
    t.label("slot").raw("89 D9 48 8D 54 24 20")._rel("FF15", gp.IAT_XINPUT_GET_STATE)
    t.raw("85 C0").je("found")
    t.raw("FF C3 83 FB 04")._rel("0F82", "slot")
    t.raw("B9" + u32(PAD_POLL_MS))._rel("FF15", gp.IAT_SLEEP)
    t.raw("FF CE").jne("poll")
    t.jmp("done")
    t.label("found")
    t._rel("FF15", IAT_GET_TICK_COUNT64)._rel("48 89 05", LOG_PAD)
    t._rel("89 35", LOG_LEFT)
    t.raw("31 C9").call(gp.REFOCUS_THREAD)
    t._rel("FF15", IAT_GET_TICK_COUNT64)._rel("48 89 05", LOG_DONE)
    t.label("done")
    t.raw("31 C0 48 83 C4 38 5E 5B C3")
    thread = va(CAVE2_OFF)
    code = t.build()

    starter = thread + len(code)
    s = Asm(starter)
    s.raw("48 83 EC 38 31 C9 31 D2")
    s._rel("4C 8D 05", thread)
    s.raw("45 31 C9 48 C7 44 24 20 00 00 00 00 48 C7 44 24 28 00 00 00 00")
    s._rel("FF15", gp.IAT_CREATE_THREAD)
    s.raw("48 83 C4 38 C3")
    _place(data, CAVE2_OFF, CAVE2_END, code + s.build())
    return thread, starter


def patch_autoload(data: bytearray, cave_off: int, cave_end: int) -> int | None:
    if bytes(data[off(TITLE_MOVIE_IMPL):off(TITLE_MOVIE_IMPL) + 8]) != TITLE_MOVIE_ORIG:
        return None
    if any(b != 0xCC for b in data[CAVE2_OFF:CAVE2_END]):
        return None
    cave_off = gp.emit_refocus_thread(data, cave_off, cave_end)
    _, start_pad_wait = emit_pad_wait(data)

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
    a.call(start_pad_wait)
    a.raw("48 83 C4 20 5B B0 01 C3")              # "requested": load the map
    a.label("fail")
    a.raw("48 83 C4 20 5B")
    a.label("no")
    a.raw("31 C0 C3")

    dest = va(cave_off)
    cave_off = _place(data, cave_off, cave_end, a.build())
    _jmp_site(data, TITLE_MOVIE_IMPL, dest, 8)
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
