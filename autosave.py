"""
Autosave after battle: once a battle has closed and the player is back on
the field, the game is saved to a chosen slot.

The battle stores the player's position for saving itself, so a plain save
(BPL_SaveLoad:Save, the same routine the save menu ends in) restores the
spot the battle started from.
"""

from __future__ import annotations

import os
import struct

from gameplay_patches import BTL_NEXTSTEP_OFF, SETNEXTSTEP_THUNKS, _jmp_site, off, put_code

SAVE_SLOT_NATIVE = 0x140B70210   # Save(list index) -> bool; 0..19 = save slots 1..20
SAVE_SLOT_ORIG   = bytes.fromhex("4056 4881ec00020000 4863f1".replace(" ", ""))
BTL_STEP_FINISH_WAIT = 31        # the battle's last step

# Inside Save: builds the save object from the save data. Its last argument
# also fills the player name in the header the load menu reads; Save passes it
# only for the autosave slots, so it is set here while the autosave runs.
SAVE_BUILD_SITE  = 0x140B702DA
SAVE_BUILD_ORIG  = bytes.fromhex("e8e1d7f9ff")
SAVE_BUILD_FN    = 0x140B0DAC0

# Player movement update, called every frame the player can move on the field.
FIELD_TICK_SITE  = 0x140A6AA7D
FIELD_TICK_ORIG  = bytes.fromhex("e85e110000")
FIELD_TICK_FN    = 0x140A6BBE0

AUTOSAVE_PENDING = 0x1549A9A08   # field updates left before saving (0 = none due)
AUTOSAVE_COUNT   = 0x1549A9A0C   # saves written this session
AUTOSAVE_RESULT  = 0x1549A9A10   # result of the last save
AUTOSAVE_BUSY    = 0x1549A9A14   # nonzero while the autosave runs
# Field updates to wait after the battle's last step, so the battle has
# written its results back before the save.
AUTOSAVE_DELAY   = 120

SLOT_MIN, SLOT_MAX = 1, 20

# Header fields of the save object (offsets from the object the build fills,
# which starts 0x30 into the save object). Menu saves clear the autosave flag
# and record the text language, which loading checks against the current
# one; the two bytes after it are taken from an existing save in that language.
HDR_AUTOSAVE_FLAG = 0x0C
HDR_LANGUAGE      = 0x75
CURRENT_LANGUAGE  = 0x140B44420     # returns the current text language in al
SAVE_HEADERS      = 0x1443005B0     # load-menu header entries, 0x70 bytes each
SAVE_HEADER_COUNT = 0x1443005B8
HEADER_LANGUAGE   = 0x68

# Location: the load menu shows the row of the MapAreaName table named by the
# field's current area label (BP_MapUICtrl.NowAreaNameData), reached through
# the game instance (ProjectGameInstance_C.m_MapUICommon).
HDR_LOCATION      = 0x60
GAME_INSTANCE     = 0x140B29520     # returns the game instance
GI_MAP_UI         = 0x1EF0
MAP_UI_AREA_LABEL = 0x290           # FName {index, number}
FNAME_BLOCKS      = 0x1443BE310     # FNamePool blocks; entry = block + 2 * offset
AREA_TABLE        = "Project/Content/Blueprints/Gamedata/BinTable/Map/MapAreaName"
HASH_SECTION      = b".text1"       # readable data section with unused zero padding
FNV_BASIS, FNV_PRIME = 0x811C9DC5, 0x01000193


def label_hash(name: str, num: int, salt: int) -> int:
    """16-bit hash of an FName (lower-cased text, then its number), as the
    location code computes it."""
    h = FNV_BASIS ^ salt
    for c in name.encode("latin-1").lower():
        h = ((h ^ c) * FNV_PRIME) & 0xFFFFFFFF
    h ^= num
    return (h ^ (h >> 16)) & 0xFFFF


def area_hashes(labels: list[tuple[str, int]]) -> tuple[int, list[int]]:
    """A salt under which every row label hashes differently, and the hashes."""
    for salt in range(1, 1 << 16):
        hs = [label_hash(n, k, salt) for n, k in labels]
        if len(set(hs)) == len(hs):
            return salt, hs
    raise RuntimeError("no collision-free hash for the area labels")


def _slack_data(data: bytearray, size: int) -> int:
    """Place size zero bytes' worth of room in HASH_SECTION's padding; returns
    its file offset (the caller writes the data)."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    sec = pe + 24 + struct.unpack_from("<H", data, pe + 20)[0]
    for i in range(nsec):
        h = sec + 40 * i
        if bytes(data[h:h + 8]).rstrip(b"\0") != HASH_SECTION:
            continue
        vsize, rva, rsize, raw = struct.unpack_from("<IIII", data, h + 8)
        start = raw + ((vsize + 15) & ~15) + 16
        end = start
        while end < raw + rsize and data[end] == 0:
            end += 1
        if start + size <= end - 16:
            return start
    raise RuntimeError("no room for the location table")


def _va(data: bytearray, file_off: int) -> int:
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    sec = pe + 24 + struct.unpack_from("<H", data, pe + 20)[0]
    for i in range(nsec):
        vsize, rva, rsize, raw = struct.unpack_from("<IIII", data, sec + 40 * i + 8)
        if raw <= file_off < raw + rsize:
            return 0x140000000 + rva + file_off - raw
    raise RuntimeError("offset outside the image")


def read_area_labels(game_dir: str, paks_subpath: str, source_pak: str,
                     repak: str, run_repak) -> list[tuple[str, int]]:
    """MapAreaName row labels, in row order, as (name, FName number)."""
    from ue_asset import Package
    src = os.path.join(game_dir, paks_subpath, source_pak)
    if not os.path.isfile(src):
        raise RuntimeError(f"{source_pak} not found")
    pkg = Package(run_repak(repak, "get", src, AREA_TABLE + ".uasset"),
                  run_repak(repak, "get", src, AREA_TABLE + ".uexp"))
    e, names = bytes(pkg.e), pkg.names
    tag = struct.pack("<iiii", names.index("MessageLabel"), 0, names.index("NameProperty"), 0)
    labels, i = [], e.find(tag)
    while i >= 0:
        v, num = struct.unpack_from("<ii", e, i + 25)
        labels.append((names[v], num))
        i = e.find(tag, i + 1)
    if not labels or labels[0][0] != "MapAreaName_Dummy":
        raise RuntimeError("unexpected MapAreaName layout")
    return labels


def patch_autosave(data: bytearray, caves: list[list[int]], slot: int,
                   area_labels: list[tuple[str, int]] | None = None) -> bool:
    if not SLOT_MIN <= slot <= SLOT_MAX:
        raise ValueError(f"save slot must be {SLOT_MIN}-{SLOT_MAX}")
    for t in SETNEXTSTEP_THUNKS:
        if data[off(t)] != 0xE9:
            return False
    if bytes(data[off(SAVE_SLOT_NATIVE):off(SAVE_SLOT_NATIVE) + len(SAVE_SLOT_ORIG)]) != SAVE_SLOT_ORIG:
        return False
    if bytes(data[off(FIELD_TICK_SITE):off(FIELD_TICK_SITE) + 5]) != FIELD_TICK_ORIG:
        return False
    if bytes(data[off(SAVE_BUILD_SITE):off(SAVE_BUILD_SITE) + 5]) != SAVE_BUILD_ORIG:
        return False

    # Battle end: arm the save.
    for t in SETNEXTSTEP_THUNKS:
        prev = t + 5 + struct.unpack_from("<i", data, off(t) + 1)[0]

        def step_hook(a, prev=prev):
            a.raw("53 48 83 EC 20 48 89 CB")              # push rbx; sub rsp,20h; mov rbx,rcx
            a.call(prev)
            a.raw("80 BB" + struct.pack("<I", BTL_NEXTSTEP_OFF).hex() + "%02x" % BTL_STEP_FINISH_WAIT)
            a.jne("done")
            a.raw("B8" + struct.pack("<I", AUTOSAVE_DELAY).hex())
            a._rel("89 05", AUTOSAVE_PENDING)            # mov [pending], eax
            a.label("done")
            a.raw("48 83 C4 20 5B C3")
            return a

        _jmp_site(data, t, put_code(data, caves, step_hook), 5)

    # Field update: count down, then save.
    def tick_hook(a):
        a._rel("8B 05", AUTOSAVE_PENDING)                # mov eax, [pending]
        a.raw("85 C0").je("go")
        a._rel("FF 0D", AUTOSAVE_PENDING)                # dec dword [pending]
        a.jne("go")
        a.raw("51 52 41 50 41 51 48 83 EC 68")           # keep the argument registers
        for i in range(4):                               # movdqu [rsp+20h+i*16], xmm0..3
            a.raw("F3 0F 7F %02X 24 %02X" % (0x44 | (i << 3), 0x20 + 16 * i))
        a.raw("B0 01")._rel("88 05", AUTOSAVE_BUSY)    # mov al,1; mov [busy],al
        a.raw("B9" + struct.pack("<I", slot - 1).hex())  # mov ecx, list index
        a.call(SAVE_SLOT_NATIVE)
        a._rel("88 05", AUTOSAVE_RESULT)
        a.raw("31 C0")._rel("88 05", AUTOSAVE_BUSY)
        a._rel("FF 05", AUTOSAVE_COUNT)
        for i in range(4):
            a.raw("F3 0F 6F %02X 24 %02X" % (0x44 | (i << 3), 0x20 + 16 * i))
        a.raw("48 83 C4 68 41 59 41 58 5A 59")
        a.label("go")
        a.jmp(FIELD_TICK_FN)
        return a

    _jmp_site(data, FIELD_TICK_SITE, put_code(data, caves, tick_hook), 5, opcode=0xE8)

    # Location: hash the field's current area label and find it among the
    # MapAreaName row hashes; no match leaves the location at 0 ("Unused").
    loc_fn = None
    if area_labels:
        salt, hashes = area_hashes(area_labels)
        tbl = _slack_data(data, 2 * len(hashes))
        tbl_va = _va(data, tbl)

        def location(a):
            a.raw("56 48 83 EC 20")                      # push rsi; sub rsp, 20h
            a.call(GAME_INSTANCE)
            a.raw("48 85 C0").je("done")
            a.raw("48 8B 80" + struct.pack("<I", GI_MAP_UI).hex())
            a.raw("48 85 C0").je("done")
            a.raw("8B 88" + struct.pack("<I", MAP_UI_AREA_LABEL).hex())         # ecx = index
            a.raw("44 8B 80" + struct.pack("<I", MAP_UI_AREA_LABEL + 4).hex())  # r8d = number
            a.raw("89 CA C1 EA 10")                      # edx = block
            a._rel("4C 8D 0D", FNAME_BLOCKS)
            a.raw("4D 8B 0C D1 4D 85 C9").je("done")
            a.raw("0F B7 C9 4D 8D 0C 49")                # r9 = entry
            a.raw("41 0F B7 09 F6 C1 01").jne("done")  # wide names never match
            a.raw("C1 E9 06 49 83 C1 02")                # ecx = length; r9 = text
            a.raw("B8" + struct.pack("<I", FNV_BASIS ^ salt).hex())
            a.label("chr")
            a.raw("85 C9").j8("74", "hashed")
            a.raw("41 0F B6 11 8D 72 BF 83 FE 19").j8("77", "lower")
            a.raw("83 CA 20")
            a.label("lower")
            a.raw("31 D0 69 C0" + struct.pack("<I", FNV_PRIME).hex())
            a.raw("49 FF C1 FF C9").j8("EB", "chr")
            a.label("hashed")
            a.raw("44 31 C0 89 C2 C1 EA 10 31 D0")       # ax = hash
            a._rel("4C 8D 0D", tbl_va)
            a.raw("B9" + struct.pack("<I", len(hashes)).hex())
            a.label("row")
            a.raw("FF C9").j8("78", "done")
            a.raw("66 41 3B 04 49").j8("75", "row")
            a.raw("89 4B %02X" % HDR_LOCATION)
            a.label("done")
            a.raw("48 83 C4 20 5E C3")                   # add rsp, 20h; pop rsi; ret
            return a

        loc_fn = put_code(data, caves, location)
        data[tbl:tbl + 2 * len(hashes)] = struct.pack("<%dH" % len(hashes), *hashes)

    # Save object build: while the autosave runs, fill the header the way a
    # menu save does.
    def build_hook(a):
        a._rel("8A 05", AUTOSAVE_BUSY)                   # mov al, [busy]
        a.raw("84 C0").j8("75", "auto")
        a.jmp(SAVE_BUILD_FN)
        a.label("auto")
        a.raw("53 48 83 EC 20")                          # push rbx; sub rsp, 20h
        a.raw("48 89 D3")                                # mov rbx, rdx (header)
        a.raw("41 B9 01 00 00 00")                       # mov r9d, 1 (player name)
        a.call(SAVE_BUILD_FN)
        a.raw("C7 43 %02X 00 00 00 00" % HDR_AUTOSAVE_FLAG)
        a.call(CURRENT_LANGUAGE)
        a.raw("0F B6 C8")                                # movzx ecx, al
        a.raw("88 43 %02X" % HDR_LANGUAGE)
        a.raw("31 C0")                                   # xor eax, eax
        a._rel("48 8B 15", SAVE_HEADERS)                 # mov rdx, [headers]
        a._rel("44 8B 05", SAVE_HEADER_COUNT)            # mov r8d, [count]
        a.raw("48 85 D2").j8("74", "store")
        a.label("scan")
        a.raw("45 85 C0").j8("7E", "store")
        a.raw("38 4A %02X" % HEADER_LANGUAGE).j8("75", "next")  # cmp [rdx+68h], cl
        a.raw("0F B7 42 %02X" % (HEADER_LANGUAGE + 1))   # movzx eax, word [rdx+69h]
        a.j8("EB", "store")
        a.label("next")
        a.raw("48 83 C2 70 41 FF C8")                    # add rdx, 70h; dec r8d
        a.j8("EB", "scan")
        a.label("store")
        a.raw("66 89 43 %02X" % (HDR_LANGUAGE + 1))      # mov [rbx+76h], ax
        if loc_fn:
            a.call(loc_fn)
        a.raw("48 83 C4 20 5B C3")                       # add rsp, 20h; pop rbx; ret
        return a

    _jmp_site(data, SAVE_BUILD_SITE, put_code(data, caves, build_hook), 5, opcode=0xE8)
    return True
