"""
Auto Load: on the first boot of a session the title menu goes straight into
the most recent save, about a second after it appears.

While the title menu is up, the title level runs one step every frame. A
small override pak built from the player's own files puts a check in front of
that step: when IsRequestedTitleMovie() answers "requested", the level jumps
to its own "load the game map" step -- the step that normally runs after a
save has been loaded from the title. The executable hook on
IsRequestedTitleMovie answers "requested" only once per boot: when the title
menu has been up for AUTOLOAD_DELAY_MS (after the Skip Intro window refocus,
when that patch is installed) and the newest regular save has loaded. In
every other case it returns the game's own answer, so the title movie, the
title menu and returning to the title from in-game work as usual.
"""

from __future__ import annotations

import os
import struct

import gameplay_patches as gp
from gameplay_patches import Asm, _jmp_site, _place, off, va

# ---------------------------------------------------------------- executable
TITLE_MOVIE_IMPL  = 0x140B8A200   # IsRequestedTitleMovie(): movzx eax,[flag]; ret
TITLE_MOVIE_ORIG  = bytes.fromhex("0fb60519737703c3")
TITLE_MOVIE_FLAG  = 0x144301520   # the byte the original returns
LOAD_HEADERS      = 0x140B6E860   # LoadAllSaveDataHeader(bool)
GET_NEWEST_SLOT   = 0x140B6DDB0   # GetMaxDateTimeSlotIndex() -> int
LOAD_SLOT         = 0x140B6E6A0   # Load(slot) -> bool (synchronous)

SAVE_HEADERS      = 0x1443005B0   # header array: 0x70-byte entries
SAVE_HEADER_NUM   = 0x1443005B8
SAVE_HEADER_SIZE  = 0x70
HDR_USED, HDR_SLOT, HDR_INHERIT = 0x00, 0x04, 0x50

STATE             = 0x1549A9801   # 0 = pending, 2 = done for this boot
TITLE_SEEN_AT     = 0x1549A9810   # GetTickCount64 when the title was first seen
IAT_GET_TICK_COUNT64 = 0x1549AED78
AUTOLOAD_DELAY_MS = 1200          # the title refocus takes about 850 ms

CAVE2_OFF, CAVE2_END = 0x503310, 0x503400   # spare 0xCC padding in .rdata


def patch_autoload(data: bytearray, cave_off: int, cave_end: int) -> int | None:
    if bytes(data[off(TITLE_MOVIE_IMPL):off(TITLE_MOVIE_IMPL) + 8]) != TITLE_MOVIE_ORIG:
        return None
    if any(b != 0xCC for b in data[CAVE2_OFF:CAVE2_END]):
        return None
    # With Skip Intro, wait for its title refocus to have started.
    refocus = data[off(gp.TITLE_TICK_IMPL)] == 0xE9

    def u32(v): return struct.pack("<I", v).hex()

    a = Asm(va(CAVE2_OFF))
    a._rel("8A 05", STATE).raw("84 C0").jne("orig")
    if refocus:
        a._rel("8A 05", gp.REFOCUS_DONE).raw("84 C0").je("orig")
    a.raw("53 48 83 EC 20")                       # rsp now 16-byte aligned
    a._rel("FF15", IAT_GET_TICK_COUNT64)
    a._rel("48 8B 1D", TITLE_SEEN_AT).raw("48 85 DB").jne("seen")
    a._rel("48 89 05", TITLE_SEEN_AT).jmp("fail")
    a.label("seen")
    a.raw("48 29 D8 48 3D" + u32(AUTOLOAD_DELAY_MS))._rel("0F 82", "fail")
    a.raw("B0 02")._rel("88 05", STATE)
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
    a.raw("48 83 C4 20 5B B0 01 C3")              # "requested": load the map
    a.label("fail")
    a.raw("48 83 C4 20 5B")
    a.label("orig")
    a._rel("0F B6 05", TITLE_MOVIE_FLAG).raw("C3")

    dest = va(CAVE2_OFF)
    _place(data, CAVE2_OFF, CAVE2_END, a.build())
    _jmp_site(data, TITLE_MOVIE_IMPL, dest, 8)
    return cave_off


# ---------------------------------------------------------------- data pak
AUTOLOAD_PAK = "pakchunk95_FreeplayAutoLoad_P.pak"
LV_TITLE = "Project/Content/Level/Title/LV_Title"

UBERGRAPH = "ExecuteUbergraph_LV_Title"
# Bytecode (memory) offsets in the title level's event graph.
STEP3_ENTRY  = 4003   # title menu step, run every frame
LOAD_MAP     = 4399   # GetMapCommon -> BPI_LoadMap(true)
SCRIPT_END   = 4762   # Return(Nothing()); EndOfScript()
# LetBool(CmpSuccess, NotEqual_IntInt(m_Step, 3)); JumpIfNot(->4003, CmpSuccess)
STEP3_SWITCH = bytes.fromhex("07a30f00000001000000890000000000000001000000")
IRTM_IMPORT  = bytes.fromhex("bfffffff")      # CallMath(IsRequestedTitleMovie)


def _jump(op: int, target: int) -> bytes:
    return bytes([op]) + struct.pack("<I", target)


class _Summary:
    """Just enough of a UE4.27 package summary to move exports around."""

    def __init__(self, ua: bytes):
        p = 4
        legacy = struct.unpack_from("<i", ua, p)[0]; p += 4
        if legacy != -4:
            p += 4
        p += 8
        p += 4 + 20 * struct.unpack_from("<i", ua, p)[0]       # custom versions
        self.header = struct.unpack_from("<i", ua, p)[0]; p += 4
        n = struct.unpack_from("<i", ua, p)[0]; p += 4         # folder name
        p += n if n >= 0 else -2 * n
        flags = struct.unpack_from("<I", ua, p)[0]; p += 4
        p += 8                                                  # names
        if not flags & 0x80000000:
            n = struct.unpack_from("<i", ua, p)[0]; p += 4
            p += n if n >= 0 else -2 * n
        p += 8                                                  # gatherable text
        self.export_count, self.export_offset = struct.unpack_from("<ii", ua, p)

    EXPORT_SIZE = 104
    SERIAL_SIZE, SERIAL_OFFSET = 28, 36

    def export(self, i: int) -> int:
        return self.export_offset + i * self.EXPORT_SIZE


def edit_lv_title(umap: bytes, uexp: bytes) -> tuple[bytes, bytes]:
    ua, ue = bytearray(umap), bytearray(uexp)
    s = _Summary(ua)
    e0 = s.export(0)
    size0 = struct.unpack_from("<q", ua, e0 + s.SERIAL_SIZE)[0]
    off0 = struct.unpack_from("<q", ua, e0 + s.SERIAL_OFFSET)[0] - s.header
    # The event graph's bytecode: [mem size][stored size][code], ending in
    # Return(Nothing()) EndOfScript().
    tail = off0 + size0 - 12
    code = None
    for p in range(off0 + 8, tail):
        if struct.unpack_from("<i", ue, p - 4)[0] == tail - p and ue[p] == 0x4C \
                and struct.unpack_from("<I", ue, p + 1)[0] == SCRIPT_END:
            code = p
            break
    if code is None or bytes(ue[tail - 3:tail]) != b"\x04\x0b\x53":
        raise RuntimeError("title level script not recognised - game update?")
    sw = ue.find(STEP3_SWITCH, code, tail)
    if sw < 0 or ue.find(STEP3_SWITCH, sw + 1, tail) >= 0 or IRTM_IMPORT not in ue[code:tail]:
        raise RuntimeError("title level script not recognised - game update?")

    # JumpIfNot(->4003, IsRequestedTitleMovie()); Jump(->4399)
    new = (_jump(0x07, STEP3_ENTRY) + b"\x68" + IRTM_IMPORT + b"\x16"
           + _jump(0x06, LOAD_MAP))
    mem_grow, grow = 15 + 5, len(new)
    struct.pack_into("<I", ue, code + 1, SCRIPT_END + mem_grow)   # PushExecFlow(->Return)
    struct.pack_into("<I", ue, sw + 1, SCRIPT_END)                 # step 3 -> new check
    ue[tail - 3:tail - 3] = new
    struct.pack_into("<i", ue, code - 8, struct.unpack_from("<i", ue, code - 8)[0] + mem_grow)
    struct.pack_into("<i", ue, code - 4, struct.unpack_from("<i", ue, code - 4)[0] + grow)

    struct.pack_into("<q", ua, e0 + s.SERIAL_SIZE, size0 + grow)
    for i in range(1, s.export_count):
        o = s.export(i) + s.SERIAL_OFFSET
        struct.pack_into("<q", ua, o, struct.unpack_from("<q", ua, o)[0] + grow)
    bulk = struct.pack("<q", len(umap) + len(uexp) - 4)
    b = ua.find(bulk)
    if b < 0 or ua.find(bulk, b + 1) >= 0:
        raise RuntimeError("title level header not recognised - game update?")
    struct.pack_into("<q", ua, b, len(umap) + len(uexp) - 4 + grow)
    return bytes(ua), bytes(ue)


def build_autoload_pak(game_dir: str, paks_subpath: str, source_pak: str,
                       repak: str, run_repak) -> None:
    """Build AUTOLOAD_PAK in the game's Paks folder. Raises RuntimeError."""
    import shutil
    import tempfile

    paks_dir = os.path.join(game_dir, paks_subpath)
    src = os.path.join(paks_dir, source_pak)
    if not os.path.isfile(src):
        raise RuntimeError(f"{source_pak} not found in {paks_dir}")

    umap, uexp = edit_lv_title(run_repak(repak, "get", src, LV_TITLE + ".umap"),
                               run_repak(repak, "get", src, LV_TITLE + ".uexp"))
    files = {LV_TITLE + ".umap": umap, LV_TITLE + ".uexp": uexp}
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
