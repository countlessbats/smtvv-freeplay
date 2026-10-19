"""
Deep Stock: battle items can be stockpiled up to 99 outside battle, while
each battle still allows only the game's normal carry limit of each item
(e.g. 5 Somas).

Data: in ItemTable (section 0, 100-byte rows, row N-1 = item N) every
battle-usable item (+61 nonzero) with a carry limit below 99 (+58) gets a
limit of 99.

Exe: when a battle enters E_BTL_STEP_PRE, the stock above each item's
original limit is recorded as a hidden amount; until the battle reaches
E_BTL_STEP_END_EVENT, ItemGetNum reports the real count minus that hidden
amount (never below 0). Items used in battle come out of the real stock.
In and out of battle, the menus' ItemGetMaxNum (the Blueprint call only,
so the game's own carry checks still see 99) reports the original limit,
so stock above it shows as e.g. 11/10.
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
# body). The other registered copy (0x140CCA910) must stay untouched:
# redirecting it makes the game exit during startup.
MAX_THUNKS = [0x140CCBA60]


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
                     orig: dict[int, int], side_off: int, side_end: int) -> int | None:
    """Main code goes in the shared cave; the ItemGetMaxNum hooks go in a
    second, smaller cave (side_off..side_end)."""
    for t in SETNEXTSTEP_THUNKS + MAX_THUNKS + [ITEM_GET_NUM, ITEM_GET_MAX]:
        if data[off(t)] != 0xE9:
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

    # ItemGetMaxNum body: remember which item was asked for.
    max_orig = ITEM_GET_MAX + 5 + struct.unpack_from("<i", data, off(ITEM_GET_MAX) + 1)[0]
    a = Asm(va(side_off))
    a._rel("89 0D", STOCK_LAST_ID)                # mov [last], ecx
    a.jmp(max_orig)
    dest = va(side_off)
    side_off = _place(data, side_off, side_end, a.build())
    _jmp_site(data, ITEM_GET_MAX, dest, 5)

    # Blueprint ItemGetMaxNum: report the item's original limit.
    for t in MAX_THUNKS:
        prev = t + 5 + struct.unpack_from("<i", data, off(t) + 1)[0]
        a = Asm(va(side_off))
        a.raw("53 48 83 EC 20 4C 89 C3")          # push rbx; sub rsp,20h; mov rbx,r8 (result)
        a.raw("B8 FF FF FF FF")._rel("89 05", STOCK_LAST_ID)
        a.call(prev)
        a._rel("8B 05", STOCK_LAST_ID)            # mov eax, [last]
        a.raw("3D" + u32(ID_MAX)).ja("done")
        a._rel("48 8D 0D", limits_va)
        a.raw("0F B6 0C 01 85 C9").je("done")    # movzx ecx,[rcx+rax]; test ecx,ecx
        a.raw("89 0B")                            # mov [rbx], ecx
        a.label("done")
        a.raw("48 83 C4 20 5B C3")
        dest = va(side_off)
        side_off = _place(data, side_off, side_end, a.build())
        _jmp_site(data, t, dest, 5)
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
