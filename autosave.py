"""
Autosave after battle: once a battle has closed and the player is back on
the field, the game is saved to a chosen slot.

The battle stores the player's position for saving itself, so a plain save
(BPL_SaveLoad:Save, the same routine the save menu ends in) restores the
spot the battle started from.
"""

from __future__ import annotations

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


def patch_autosave(data: bytearray, caves: list[list[int]], slot: int) -> bool:
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

    # Save object build: while the autosave runs, fill the header the way a
    # menu save does.
    def build_hook(a):
        a._rel("8A 05", AUTOSAVE_BUSY)                   # mov al, [busy]
        a.raw("84 C0").jne("auto")
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
        a.raw("48 85 D2").je("store")
        a.label("scan")
        a.raw("45 85 C0").jle("store")
        a.raw("38 4A %02X" % HEADER_LANGUAGE).jne("next")  # cmp [rdx+68h], cl
        a.raw("0F B7 42 %02X" % (HEADER_LANGUAGE + 1))   # movzx eax, word [rdx+69h]
        a.jmp("store")
        a.label("next")
        a.raw("48 83 C2 70 41 FF C8")                    # add rdx, 70h; dec r8d
        a.jmp("scan")
        a.label("store")
        a.raw("66 89 43 %02X" % (HDR_LANGUAGE + 1))      # mov [rbx+76h], ax
        a.raw("48 83 C4 20 5B C3")                       # add rsp, 20h; pop rbx; ret
        return a

    _jmp_site(data, SAVE_BUILD_SITE, put_code(data, caves, build_hook), 5, opcode=0xE8)
    return True
