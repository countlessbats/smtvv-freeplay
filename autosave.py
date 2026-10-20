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
# also fills the header the load menu reads (player name, location,
# language); Save passes it only for the autosave slots, so it is set here
# while the autosave runs.
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

# Inspection: copies of the finished save object as it is written: one from
# the direct save (autosave), one from every call of the writer, with the
# caller's return address and a call count.
SAVE_WRITE_FN    = 0x140B708A0
SAVE_WRITE_ORIG  = bytes.fromhex("4055535657")   # push rbp; push rbx; push rsi; push rdi
CAPTURE_SITES    = ((0x140B70352, bytes.fromhex("e849050000"), 0x1549A9100, 0x1549A9A20),)
WRITE_BUF        = 0x1549A9500
WRITE_PTR        = 0x1549A9A28
WRITE_RET        = 0x1549A9A30
WRITE_COUNT      = 0x1549A9A38
CAPTURE_QWORDS   = 0x80


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

    # Save object build: fill the header too while the autosave runs.
    def build_hook(a):
        a._rel("8A 05", AUTOSAVE_BUSY)                   # mov al, [busy]
        a.raw("84 C0").je("go")
        a.raw("41 B9 01 00 00 00")                       # mov r9d, 1
        a.label("go")
        a.jmp(SAVE_BUILD_FN)
        return a

    _jmp_site(data, SAVE_BUILD_SITE, put_code(data, caves, build_hook), 5, opcode=0xE8)

    for site, orig, buf, ptr in CAPTURE_SITES:
        if bytes(data[off(site):off(site) + 5]) != orig:
            continue

        def capture_hook(a, buf=buf, ptr=ptr):
            a.raw("56 57 51")                            # push rsi, rdi, rcx
            a._rel("48 89 0D", ptr)                      # mov [ptr], rcx (save object)
            a.raw("48 89 CE")                            # mov rsi, rcx
            a._rel("48 8D 3D", buf)                      # lea rdi, [buf]
            a.raw("B9" + struct.pack("<I", CAPTURE_QWORDS).hex())
            a.raw("FC F3 48 A5")                         # cld; rep movsq
            a.raw("59 5F 5E")
            a.jmp(SAVE_WRITE_FN)
            return a

        _jmp_site(data, site, put_code(data, caves, capture_hook), 5, opcode=0xE8)

    if bytes(data[off(SAVE_WRITE_FN):off(SAVE_WRITE_FN) + 5]) == SAVE_WRITE_ORIG:
        def write_hook(a):
            a.raw("56 57 51")                            # push rsi, rdi, rcx
            a.raw("48 8B 44 24 18")                      # mov rax, [rsp+18h] (return address)
            a._rel("48 89 05", WRITE_RET)
            a._rel("48 89 0D", WRITE_PTR)
            a.raw("48 89 CE")                            # mov rsi, rcx
            a._rel("48 8D 3D", WRITE_BUF)
            a.raw("B9" + struct.pack("<I", CAPTURE_QWORDS).hex())
            a.raw("FC F3 48 A5")                         # cld; rep movsq
            a.raw("59 5F 5E")
            a._rel("FF 05", WRITE_COUNT)                 # inc dword [count]
            a.raw(SAVE_WRITE_ORIG.hex())
            a.jmp(SAVE_WRITE_FN + 5)
            return a

        _jmp_site(data, SAVE_WRITE_FN, put_code(data, caves, write_hook), 5)
    return True
