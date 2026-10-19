"""
Deep Stock: battle items can be stockpiled up to 99 outside battle, while
each battle still allows only the game's normal carry limit of each item
(e.g. 5 Somas).

The ItemTable keeps its limits (section 0, 100-byte rows, row N-1 = item N;
+58 carry limit, +61 nonzero when usable in battle), so menus show the
normal limit and stock above it shows as e.g. 11/10. For every battle item
with a limit below 99, the exe's ItemGetMaxNum reports 99 to the game's
carry checks.

When a battle enters E_BTL_STEP_PRE, the stock above each item's normal
limit is recorded as a hidden amount; until the battle reaches
E_BTL_STEP_END_EVENT, ItemGetNum reports the real count minus that hidden
amount (never below 0), and the battle menus' ItemGetMaxNum (the Blueprint
call) reports the normal limit. Items used in battle come out of the real
stock.
"""

from __future__ import annotations

import os
import struct

from gameplay_patches import (Asm, BTL_NEXTSTEP_OFF, BTL_STEP_PRE, ITEM_GET_MAX, ITEM_GET_NUM,
                              SETNEXTSTEP_THUNKS, _jmp_site, _place, va, off)
from shop_pak import ITEM_ID_OFF, ITEM_ROW, ITEM_TABLE, _section

STOCK_PAK = "pakchunk93_FreeplayStock_P.pak"

ITEM_MAX_OFF = 58          # u8 carry limit
ITEM_BATTLE_OFF = 61       # nonzero: usable in battle
STOCK_MAX = 99
ID_MAX = 135               # use items are 1..135

BTL_STEP_END_EVENT = 24
STOCK_ACTIVE = 0x1549A9900   # spare zeroed bytes in a writable section page
STOCK_LAST_ID = 0x1549A9908  # item ID of the latest ItemGetMaxNum call
STOCK_HIDDEN = 0x1549A9910   # u8 per item ID, 0..ID_MAX
# Blueprint exec thunk of ItemGetMaxNum (a 5-byte jump into the protected
# body), hooked in place.
MAX_THUNKS = [0x140CCBA60]
# The other registered copy (0x140CCA910) must keep its code bytes (patching
# them makes the game exit during startup), so its entry in the native
# function table is pointed at the hook instead: (table slot, thunk).
MAX_SLOTS = [(0x143279EB0, 0x140CCA910)]


def _file_off(data: bytes, v: int) -> int:
    """File offset of VA v, from the section table."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, pe + 6)[0]
    sec = pe + 24 + struct.unpack_from("<H", data, pe + 20)[0]
    rva = v - 0x140000000
    for i in range(count):
        vsize, vaddr, rsize, raw = struct.unpack_from("<4I", data, sec + i * 40 + 8)
        if vaddr <= rva < vaddr + max(vsize, rsize):
            return raw + rva - vaddr
    raise RuntimeError(f"address {v:#x} not in any section")


def edit_item_max(uexp: bytes) -> tuple[bytes, dict[int, int]]:
    """Raise the limits; returns the edited table and {item: original limit}."""
    data = bytearray(uexp)
    _, base, size = _section(data, 0)
    orig = {}
    for item in range(1, ID_MAX + 1):
        row = base + (item - 1) * ITEM_ROW
        if row + ITEM_ROW > base + size or struct.unpack_from("<i", data, row + ITEM_ID_OFF)[0] != item:
            raise RuntimeError(f"ItemTable row for item {item} not found - game update?")
        limit = data[row + ITEM_MAX_OFF]
        if data[row + ITEM_BATTLE_OFF] and 0 < limit < STOCK_MAX:
            orig[item] = limit
            data[row + ITEM_MAX_OFF] = STOCK_MAX
    if not orig:
        raise RuntimeError("no battle items found in ItemTable - game update?")
    return bytes(data), orig


def patch_deep_stock(data: bytearray, cave_off: int, cave_end: int,
                     orig: dict[int, int], side: list[list[int]]) -> int | None:
    """Main code goes in the shared cave; the ItemGetMaxNum hooks go in the
    smaller caves listed in side ([start, end] pairs, used up in place)."""
    for t in SETNEXTSTEP_THUNKS + MAX_THUNKS + [ITEM_GET_NUM, ITEM_GET_MAX]:
        if data[off(t)] != 0xE9:
            return None
    for slot, thunk in MAX_SLOTS:
        if struct.unpack_from("<Q", data, _file_off(data, slot))[0] != thunk:
            return None
    num_orig = ITEM_GET_NUM + 5 + struct.unpack_from("<i", data, off(ITEM_GET_NUM) + 1)[0]
    limits = bytes(orig.get(i, 0) for i in range(ID_MAX + 1))

    def u32(v): return struct.pack("<I", v).hex()

    # ItemGetNum: subtract the hidden stock while a battle is running.
    a = Asm(va(cave_off))
    a.raw("53 48 83 EC 20 89 CB")                 # push rbx; sub rsp,20h; mov ebx,ecx
    a.call(num_orig)
    a._rel("8A 0D", STOCK_ACTIVE).raw("84 C9").je("done")
    a.raw("81 FB" + u32(ID_MAX)).ja("done")
    a._rel("48 8D 0D", STOCK_HIDDEN)
    a.raw("0F B6 0C 19")                          # movzx ecx, byte [rcx+rbx]
    a.raw("29 C8")                                # sub eax, ecx
    a._rel("0F 8D", "done")                       # jge done
    a.raw("31 C0")
    a.label("done")
    a.raw("48 83 C4 20 5B C3")
    dest = va(cave_off)
    cave_off = _place(data, cave_off, cave_end, a.build())
    _jmp_site(data, ITEM_GET_NUM, dest, 5)

    # SetNextStep: record the hidden stock at PRE, stop hiding at END_EVENT.
    for t in SETNEXTSTEP_THUNKS:
        prev = t + 5 + struct.unpack_from("<i", data, off(t) + 1)[0]
        a = Asm(va(cave_off))
        a.raw("53 56 57 48 83 EC 20 48 89 CB")    # push rbx/rsi/rdi; sub rsp,20h; mov rbx,rcx
        a.call(prev)
        a.raw("0F B6 83" + u32(BTL_NEXTSTEP_OFF))  # movzx eax, m_NextStep
        a.raw("83 F8 %02x" % BTL_STEP_PRE).jne("end")
        a.raw("BE 01 00 00 00")                   # mov esi, 1
        a.label("loop")
        a.rip("48 8D 05", "limits")
        a.raw("0F B6 3C 30")                      # movzx edi, byte [rax+rsi]
        a.raw("31 C0 85 FF").je("store")          # no limit: hide nothing
        a.raw("89 F1").call(num_orig)
        a.raw("29 F8")                            # sub eax, edi
        a._rel("0F 8F", "store")                  # jg store
        a.raw("31 C0")
        a.label("store")
        a._rel("48 8D 0D", STOCK_HIDDEN)
        a.raw("88 04 31")                         # mov [rcx+rsi], al
        a.raw("FF C6 81 FE" + u32(ID_MAX)).jle("loop")
        a.raw("B0 01")._rel("88 05", STOCK_ACTIVE)
        a.jmp("done")
        a.label("end")
        a.raw("83 F8 %02x" % BTL_STEP_END_EVENT)
        a._rel("0F 82", "done")                   # jb done
        a.raw("31 C0")._rel("88 05", STOCK_ACTIVE)
        a.label("done")
        a.raw("48 83 C4 20 5F 5E 5B C3")
        a.label("limits")
        limits_va = va(cave_off) + len(a.b)
        a.b += limits
        dest = va(cave_off)
        cave_off = _place(data, cave_off, cave_end, a.build())
        _jmp_site(data, t, dest, 5)

    # ItemGetMaxNum body: remember which item was asked for, and let the
    # game's carry checks see the stock limit for items with a normal limit.
    max_orig = ITEM_GET_MAX + 5 + struct.unpack_from("<i", data, off(ITEM_GET_MAX) + 1)[0]
    def side_put(build) -> int:
        for c in side:
            code = build(Asm(va(c[0]))).build()
            if c[0] + len(code) <= c[1]:
                dest = va(c[0])
                c[0] = _place(data, c[0], c[1], code)
                return dest
        raise RuntimeError("code cave too small")

    def max_hook(a):
        a._rel("89 0D", STOCK_LAST_ID)            # mov [last], ecx
        a.raw("53 48 83 EC 20 89 CB")             # push rbx; sub rsp,20h; mov ebx,ecx
        a.call(max_orig)
        a.raw("81 FB" + u32(ID_MAX)).ja("keep")
        a._rel("48 8D 15", limits_va)
        a.raw("80 3C 1A 00").je("keep")           # cmp byte [rdx+rbx], 0
        a.raw("B8" + u32(STOCK_MAX))
        a.label("keep")
        a.raw("48 83 C4 20 5B C3")
        return a

    _jmp_site(data, ITEM_GET_MAX, side_put(max_hook), 5)

    # Blueprint ItemGetMaxNum: in battle, report the item's normal limit.
    def thunk_hook(prev):
        def build(a):
            # rax is passed through untouched: the game also calls this
            # entry outside Blueprint and uses what it returns.
            a.raw("53 48 83 EC 20 4C 89 C3")      # push rbx; sub rsp,20h; mov rbx,r8 (result)
            a.raw("B9 FF FF FF FF")._rel("89 0D", STOCK_LAST_ID)
            a.call(prev)
            a._rel("8A 0D", STOCK_ACTIVE).raw("84 C9").je("done")   # battles only
            a._rel("8B 0D", STOCK_LAST_ID)        # mov ecx, [last]
            a.raw("81 F9" + u32(ID_MAX)).ja("done")
            a._rel("48 8D 15", limits_va)
            a.raw("0F B6 14 0A 85 D2").je("done")    # movzx edx,[rdx+rcx]; test edx,edx
            a.raw("48 85 DB").je("done")          # no result slot
            a.raw("88 13")                        # mov [rbx], dl (the low byte of any int width)
            a.label("done")
            a.raw("48 83 C4 20 5B C3")
            return a
        return build

    for t in MAX_THUNKS:
        prev = t + 5 + struct.unpack_from("<i", data, off(t) + 1)[0]
        _jmp_site(data, t, side_put(thunk_hook(prev)), 5)
    for slot, _ in MAX_SLOTS:
        prev = struct.unpack_from("<Q", data, _file_off(data, slot))[0]
        struct.pack_into("<Q", data, _file_off(data, slot), side_put(thunk_hook(prev)))
    return cave_off


def read_item_table(game_dir: str, paks_subpath: str, source_pak: str,
                    repak: str, run_repak) -> tuple[bytes, bytes]:
    src = os.path.join(game_dir, paks_subpath, source_pak)
    if not os.path.isfile(src):
        raise RuntimeError(f"{source_pak} not found")
    return (run_repak(repak, "get", src, ITEM_TABLE + ".uasset"),
            run_repak(repak, "get", src, ITEM_TABLE + ".uexp"))


def build_stock_pak(game_dir: str, paks_subpath: str, item_asset: bytes,
                    item_exp: bytes, repak: str, run_repak) -> None:
    """Build STOCK_PAK (ItemTable only) in the game's Paks folder."""
    import shutil
    import tempfile

    staging = tempfile.mkdtemp(prefix="smtvv_stock_")
    try:
        for entry, blob in ((ITEM_TABLE + ".uasset", item_asset), (ITEM_TABLE + ".uexp", item_exp)):
            path = os.path.join(staging, *entry.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(blob)
        out = os.path.join(game_dir, paks_subpath, STOCK_PAK)
        tmp = out + ".tmp"
        try:
            run_repak(repak, "pack", "--version", "V11", staging, tmp)
            os.replace(tmp, out)
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
