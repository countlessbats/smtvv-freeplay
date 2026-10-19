"""
Gameplay patches for the Freeplay patcher: battle consumable refill and
multi-jump with air control. Each builder writes its code into the shared
CC cave and returns the next free cave offset, or None if the expected bytes
were not found (the patch is then skipped).
"""

from __future__ import annotations

import struct

RDATA_RAW = 0x600
RDATA_VA  = 0x140001000


def va(foff: int) -> int:
    return RDATA_VA + (foff - RDATA_RAW)


def off(v: int) -> int:
    return v - RDATA_VA + RDATA_RAW


class Asm:
    """Tiny x64 emitter: raw bytes plus rel32 fixups to labels or VAs."""

    def __init__(self, base_va: int):
        self.base = base_va
        self.b = bytearray()
        self.labels: dict[str, int] = {}
        self.fix: list[tuple[int, str | int]] = []

    def raw(self, hexstr: str) -> "Asm":
        self.b += bytes.fromhex(hexstr.replace(" ", ""))
        return self

    def label(self, name: str) -> "Asm":
        self.labels[name] = len(self.b)
        return self

    def _rel(self, opcode: str, target: str | int) -> "Asm":
        self.raw(opcode)
        self.fix.append((len(self.b), target))
        self.b += b"\0\0\0\0"
        return self

    def call(self, t): return self._rel("E8", t)
    def jmp(self, t):  return self._rel("E9", t)
    def je(self, t):   return self._rel("0F84", t)
    def jne(self, t):  return self._rel("0F85", t)
    def jle(self, t):  return self._rel("0F8E", t)
    def ja(self, t):   return self._rel("0F87", t)

    def rip(self, opcode: str, label: str) -> "Asm":
        """Instruction ending in a RIP-relative disp32 to a data label."""
        return self._rel(opcode, label)

    def f32(self, name: str, value: float) -> "Asm":
        while len(self.b) % 4:
            self.b += b"\xCC"
        self.label(name)
        self.b += struct.pack("<f", value)
        return self

    def build(self) -> bytes:
        for pos, t in self.fix:
            tgt = self.base + self.labels[t] if isinstance(t, str) else t
            struct.pack_into("<i", self.b, pos, tgt - (self.base + pos + 4))
        return bytes(self.b)


def _place(data: bytearray, cave_off: int, cave_end: int, code: bytes) -> int:
    if cave_off + len(code) > cave_end:
        raise RuntimeError("code cave too small")
    for i in range(len(code)):
        assert data[cave_off + i] == 0xCC
    data[cave_off : cave_off + len(code)] = code
    return cave_off + ((len(code) + 15) & ~15)


def _jmp_site(data: bytearray, site_va: int, dest_va: int, length: int,
              opcode: int = 0xE9) -> None:
    o = off(site_va)
    data[o] = opcode
    struct.pack_into("<i", data, o + 1, dest_va - (site_va + 5))
    for i in range(5, length):
        data[o + i] = 0x90


# Small executable sections whose raw data is mostly unused zero padding;
# the loader maps their whole raw size, so the padding can hold code.
SLACK_SECTIONS = (b".rodata", b".xtext")
IMAGE_BASE = 0x140000000


def slack_caves(data: bytearray) -> list[list[int]]:
    """Zero padding in SLACK_SECTIONS as [file start, file end, va - file]
    cave entries, filled with CC so _place accepts them."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    sec = pe + 24 + struct.unpack_from("<H", data, pe + 20)[0]
    caves = []
    for i in range(nsec):
        h = sec + 40 * i
        name = bytes(data[h:h + 8]).rstrip(b"\0")
        vsize, rva, rsize, raw = struct.unpack_from("<IIII", data, h + 8)
        flags = struct.unpack_from("<I", data, h + 36)[0]
        if name not in SLACK_SECTIONS or not flags & 0x20000000:
            continue
        start = raw + ((vsize + 15) & ~15) + 16
        end = start
        while end < raw + rsize and data[end] in (0, 0xCC):
            end += 1
        end = (end - 16) & ~15
        if end - start >= 64:
            data[start:end] = b"\xCC" * (end - start)
            caves.append([start, end, IMAGE_BASE + rva - raw])
    return caves


def put_code(data: bytearray, caves: list[list[int]], build) -> int:
    """Place the code from build(Asm) in the first cave it fits; returns its VA."""
    for c in caves:
        code = build(Asm(c[0] + c[2])).build()
        if c[0] + len(code) <= c[1]:
            dest = c[0] + c[2]
            c[0] = _place(data, c[0], c[1], code)
            return dest
    raise RuntimeError("code cave too small")


# ---------------------------------------------------------------------------
# Battle consumable refill
# ---------------------------------------------------------------------------
# BattleMainWorkBase::SetNextStep exec thunk (a 5-byte jump into the
# protected body). After the original runs, if the battle is entering
# E_BTL_STEP_PRE (3) -- the first step of every battle -- every
# battle-usable item the player has ever obtained is topped up to its carry
# limit. The other registered copy of
# this thunk (0x140C27BC0) must stay untouched: redirecting it makes the
# game exit during startup.
SETNEXTSTEP_THUNKS = [0x140C2C2D0]
BTL_NEXTSTEP_OFF  = 0x262   # m_NextStep
BTL_STEP_PRE      = 3
BTL_STEP_READY       = 2   # E_BTL_STEP_READY .. E_BTL_STEP_START_EVENT run once per
BTL_STEP_START_EVENT = 5   # battle, before the first turn
BTL_STEP_END_EVENT   = 24  # E_BTL_STEP_END_EVENT .. FINISH_WAIT close a battle

ITEM_GET          = 0x140ACE9A0   # ItemGet(id, count)  (adds)
ITEM_GET_MAX      = 0x140ACF220   # ItemGetMaxNum(id) -> int
ITEM_GET_NUM      = 0x140ACF4F0   # ItemGetNum(id) -> int
ITEM_IS_GOTTEN    = 0x140ACF6F0   # ItemIsGotten(id) -> bool
ITEM_IS_USEBATTLE = 0x140ACF7C0   # ItemIsUseBattle(id) -> bool
REFILL_ID_MAX     = 135           # use items are 1..135


def patch_refill(data: bytearray, cave_off: int, cave_end: int) -> int | None:
    for t in SETNEXTSTEP_THUNKS:
        if data[off(t)] != 0xE9:
            return None
    if data[off(ITEM_IS_USEBATTLE):off(ITEM_IS_USEBATTLE) + 5] != bytes.fromhex("48895c2408"):
        return None
    for fn in (ITEM_GET, ITEM_GET_MAX, ITEM_GET_NUM, ITEM_IS_GOTTEN):
        if data[off(fn)] != 0xE9:
            return None

    for t in SETNEXTSTEP_THUNKS:
        orig = t + 5 + struct.unpack_from("<i", data, off(t) + 1)[0]
        a = Asm(va(cave_off))
        a.raw("53 56 57")                     # push rbx/rsi/rdi
        a.raw("48 83 EC 20")                  # sub rsp, 20h
        a.raw("48 89 CB")                     # mov rbx, rcx
        a.call(orig)                          # original SetNextStep
        a.raw("80 BB").raw(struct.pack("<I", BTL_NEXTSTEP_OFF).hex()).raw("%02x" % BTL_STEP_PRE)
        a.jne("done")
        a.raw("BE 01 00 00 00")               # mov esi, 1
        a.label("loop")
        a.raw("89 F1").call(ITEM_IS_USEBATTLE).raw("84 C0").je("next")
        a.raw("89 F1").call(ITEM_IS_GOTTEN).raw("84 C0").je("next")
        a.raw("89 F1").call(ITEM_GET_MAX).raw("89 C7")          # edi = max
        a.raw("89 F1").call(ITEM_GET_NUM).raw("29 C7")          # edi -= num
        a.jle("next")
        a.raw("89 F1 89 FA").call(ITEM_GET)                     # ItemGet(id, edi)
        a.label("next")
        a.raw("FF C6")                                           # inc esi
        a.raw("81 FE").raw(struct.pack("<I", REFILL_ID_MAX).hex())
        a.jle("loop")
        a.label("done")
        a.raw("48 83 C4 20 5F 5E 5B C3")
        code = a.build()
        dest = va(cave_off)
        cave_off = _place(data, cave_off, cave_end, code)
        _jmp_site(data, t, dest, 5)
    return cave_off


# ---------------------------------------------------------------------------
# Full Magatsuhi: fill the player's Magatsuhi gauge as each battle starts
# ---------------------------------------------------------------------------
# A battle keeps its own Magatsuhi gauges in BattleMainWorkBase: an int
# array, one per side, the player's first (the party Uplifting gauge from the
# save data is copied in before the first step, and the array is written
# back when the battle ends). The maximum is BPL_BattleCommon:
# GetUpliftingGaugeMax, a constant 100. The player's gauge is filled on the
# opening steps (READY .. START_EVENT), which run once per battle.
BTL_GAUGES_OFF   = 0x540         # TArray<int32> {data, num, max}
BTL_GAUGE_CACHE  = 0x550         # player's gauge, refreshed from the array
UPLIFT_MAX       = 100


def patch_magatsuhi(data: bytearray, caves: list[list[int]]) -> bool:
    for t in SETNEXTSTEP_THUNKS:
        if data[off(t)] != 0xE9:
            return False

    def u32(v): return struct.pack("<I", v).hex()

    # Chains onto whatever the thunk currently jumps to (the Battle Refill
    # or Stockpile cave when that patch is installed).
    for t in SETNEXTSTEP_THUNKS:
        prev = t + 5 + struct.unpack_from("<i", data, off(t) + 1)[0]

        def hook(a, prev=prev):
            a.raw("53 48 83 EC 20 48 89 CB")                     # push rbx; sub rsp,20h; mov rbx,rcx
            a.call(prev)
            a.raw("0F B6 83" + u32(BTL_NEXTSTEP_OFF))             # movzx eax, byte [rbx+262h]
            a.raw("83 E8 %02x 83 F8 %02x" % (BTL_STEP_READY, BTL_STEP_START_EVENT - BTL_STEP_READY))
            a.ja("done")                                          # opening steps only
            a.raw("48 8B 83" + u32(BTL_GAUGES_OFF))               # mov rax, [rbx+540h]
            a.raw("48 85 C0").je("done")
            a.raw("83 BB" + u32(BTL_GAUGES_OFF + 8) + "00")       # cmp dword [rbx+548h], 0
            a.jle("done")
            a.raw("C7 00" + u32(UPLIFT_MAX))                      # mov dword [rax], 100
            a.raw("C7 83" + u32(BTL_GAUGE_CACHE) + u32(UPLIFT_MAX))
            a.label("done")
            a.raw("48 83 C4 20 5B C3")
            return a

        _jmp_site(data, t, put_code(data, caves, hook), 5)
    return True


# ---------------------------------------------------------------------------
# Hold-to-ascend and air control (PlayerMovementComponent)
# ---------------------------------------------------------------------------
PM_ON_GROUND    = 0x1C8   # nonzero while grounded
PM_JUMPING      = 0x250   # jump in progress
PM_TAKEOFF      = 0x251   # take-off done (rising phase active)
PM_JUMP_TIME    = 0x254   # seconds since take-off
PM_AIR_TIME     = 0x24C

JUMP_VCALL_SITE = 0x140A6869C   # Jump(): call [rax+570h] (grounded check)
JUMP_VCALL_ORIG = bytes.fromhex("ff907005000084c074")
AIRSPEED_SITE   = 0x140A6BC00   # airborne max speed: movss xmm0,[rcx+160h]
AIRSPEED_ORIG   = bytes.fromhex("f30f108160010000")
INTERP_SITE     = 0x140A6A985   # movss xmm0,[rdi+1BCh] (InputInterpSpeed)
INTERP_ORIG     = bytes.fromhex("f30f1087bc010000")
TURN_SITE       = 0x140A6ADEA   # mulss xmm0,[rdi+16Ch] (rotation rate)
TURN_ORIG       = bytes.fromhex("f30f59876c010000")

ARC_SITE        = 0x140A6C8C6   # rising arc: movss xmm3,[rdi+254h]
ARC_ORIG        = bytes.fromhex("f30f109f54020000")

# Rising speed is velocityJump + 2*0.5*gravityJump*t (1550 - 4000*t by
# default). While jump is held the arc time is clamped here, giving a steady
# climb of about 1070 units/s.
HOLD_ARC_TIME   = 0.12

IAT_GET_FOREGROUND_WINDOW = 0x1549AF7A8
IAT_GET_WINDOW_THREAD_PID = 0x1549AF878
IAT_GET_CURRENT_PID       = 0x1549AEBD0
IAT_GET_ASYNC_KEY_STATE   = 0x1549AF748
IAT_XINPUT_GET_STATE      = 0x1549AFDF0   # xinput1_3 ordinal 2
VK_SPACE        = 0x20
XINPUT_A_OR_B   = 0x3000

AIR_SPEED_MUL   = 1.5
AIR_INTERP_MUL  = 8.0
AIR_TURN_MUL    = 8.0


def patch_jump(data: bytearray, cave_off: int, cave_end: int) -> int | None:
    for site, orig in ((JUMP_VCALL_SITE, JUMP_VCALL_ORIG), (AIRSPEED_SITE, AIRSPEED_ORIG),
                       (INTERP_SITE, INTERP_ORIG), (TURN_SITE, TURN_ORIG), (ARC_SITE, ARC_ORIG)):
        if bytes(data[off(site):off(site) + len(orig)]) != orig:
            return None

    def u32(v): return struct.pack("<I", v).hex()

    # Mid-air Jump(): start rising from the current height.
    a = Asm(va(cave_off))
    a.raw("48 83 EC 28 FF 90 70 05 00 00 48 83 C4 28")   # original grounded check
    a.raw("84 C0").jne("ret")
    a.raw("80 BB" + u32(PM_ON_GROUND) + "00").jne("fail")
    for flag in (0x241, 0x242, 0x243):                     # bEnableJump*
        a.raw("80 BB" + u32(flag) + "00").je("fail")
    a.raw("C6 83" + u32(PM_JUMPING) + "01")
    a.raw("C6 83" + u32(PM_TAKEOFF) + "01")
    a.raw("C7 83" + u32(PM_JUMP_TIME) + struct.pack("<f", HOLD_ARC_TIME).hex())
    a.raw("C7 83" + u32(PM_AIR_TIME) + "00000000")
    a.raw("48 8B 83 B0000000")                             # mov rax,[rbx+B0h]
    a.raw("F3 0F 10 80 D8010000")                          # movss xmm0,[rax+1D8h]
    for o in (0x258, 0x25C, 0x260):                        # jump base height
        a.raw("F3 0F 11 83" + u32(o))
    a.label("fail")
    a.raw("31 C0")
    a.label("ret")
    a.raw("C3")
    dest = va(cave_off)
    cave_off = _place(data, cave_off, cave_end, a.build())
    _jmp_site(data, JUMP_VCALL_SITE, dest, 6, opcode=0xE8)

    # Rising arc tick: while jump (Space, or pad A/B) is held in the focused
    # game window, keep the arc time at HOLD_ARC_TIME so the climb continues.
    a = Asm(va(cave_off))
    a.raw("50 51 52 4150 4151 4152 4153")                  # save volatiles
    a.raw("48 81 EC A8000000")
    for i in range(6):                                      # movdqu [rsp+40h+i*16], xmmi
        a.raw("F3 0F 7F %02X 24" % (0x84 | (i << 3)) + u32(0x40 + 16 * i))
    a._rel("FF15", IAT_GET_FOREGROUND_WINDOW)
    a.raw("48 85 C0").je("restore")
    a.raw("48 89 C1 48 8D 54 24 30")._rel("FF15", IAT_GET_WINDOW_THREAD_PID)
    a._rel("FF15", IAT_GET_CURRENT_PID)
    a.raw("3B 44 24 30").jne("restore")
    a.raw("B9" + u32(VK_SPACE))._rel("FF15", IAT_GET_ASYNC_KEY_STATE)
    a.raw("66 A9 0080").jne("held")
    a.raw("31 C9 48 8D 54 24 20")._rel("FF15", IAT_XINPUT_GET_STATE)
    a.raw("85 C0").jne("restore")
    a.raw("0F B7 44 24 24")                                 # wButtons
    a.raw("A9" + u32(XINPUT_A_OR_B)).je("restore")
    a.label("held")
    a.raw("F3 0F 10 87" + u32(PM_JUMP_TIME))
    a.rip("0F 2F 05", "t")                                  # comiss xmm0, T
    a._rel("0F86", "restore")                               # t <= T: keep
    a.rip("F3 0F 10 05", "t")
    a.raw("F3 0F 11 87" + u32(PM_JUMP_TIME))
    a.raw("C7 87" + u32(PM_AIR_TIME) + "00000000")
    a.label("restore")
    for i in range(6):
        a.raw("F3 0F 6F %02X 24" % (0x84 | (i << 3)) + u32(0x40 + 16 * i))
    a.raw("48 81 C4 A8000000")
    a.raw("415B 415A 4159 4158 5A 59 58")
    a.raw(ARC_ORIG.hex())
    a.jmp(ARC_SITE + 8)
    a.f32("t", HOLD_ARC_TIME)
    dest = va(cave_off)
    cave_off = _place(data, cave_off, cave_end, a.build())
    _jmp_site(data, ARC_SITE, dest, 8)

    # Airborne max speed x1.5 (this branch only runs off the ground).
    a = Asm(va(cave_off))
    a.raw(AIRSPEED_ORIG.hex())
    a.rip("F3 0F 59 05", "k")
    a.jmp(AIRSPEED_SITE + 8)
    a.f32("k", AIR_SPEED_MUL)
    dest = va(cave_off)
    cave_off = _place(data, cave_off, cave_end, a.build())
    _jmp_site(data, AIRSPEED_SITE, dest, 8)

    # Input direction follows the stick much faster in the air.
    a = Asm(va(cave_off))
    a.raw(INTERP_ORIG.hex())
    a.raw("80 BF" + u32(PM_ON_GROUND) + "00").jne("back")
    a.rip("F3 0F 59 05", "k")
    a.label("back").jmp(INTERP_SITE + 8)
    a.f32("k", AIR_INTERP_MUL)
    dest = va(cave_off)
    cave_off = _place(data, cave_off, cave_end, a.build())
    _jmp_site(data, INTERP_SITE, dest, 8)

    # Turn rate: undo the airborne rotation damping.
    a = Asm(va(cave_off))
    a.raw(TURN_ORIG.hex())
    a.raw("80 BF" + u32(PM_ON_GROUND) + "00").jne("back")
    a.rip("F3 0F 59 05", "k")
    a.label("back").jmp(TURN_SITE + 8)
    a.f32("k", AIR_TURN_MUL)
    dest = va(cave_off)
    cave_off = _place(data, cave_off, cave_end, a.build())
    _jmp_site(data, TURN_SITE, dest, 8)
    return cave_off


# ---------------------------------------------------------------------------
# Title refocus: with the intro skipped, the title menu comes up with the
# controller reported as disconnected until the window is deactivated and
# reactivated. The first time the title menu ticks, a short-lived thread
# posts the deactivate/activate messages a tab-out and tab-in would send.
# ---------------------------------------------------------------------------
TITLE_TICK_IMPL  = 0x140B8A000   # EnableCountUpNoInputTime(): movzx eax,[flag]; ret
TITLE_TICK_ORIG  = bytes.fromhex("0fb60521e34b03c3")
TITLE_TICK_FLAG  = 0x144048328   # the byte the original returns
REFOCUS_DONE     = 0x1549A9800   # spare zeroed byte in a writable section page
IAT_CREATE_THREAD = 0x1549AEAC0
IAT_SLEEP         = 0x1549AF088
IAT_POST_MESSAGE  = 0x1549AF918
WM_ACTIVATE       = 0x0006
WM_ACTIVATEAPP    = 0x001C
REFOCUS_DELAY_MS  = 600
REFOCUS_GAP_MS    = 250


def patch_refocus(data: bytearray, cave_off: int, cave_end: int) -> int | None:
    if bytes(data[off(TITLE_TICK_IMPL):off(TITLE_TICK_IMPL) + 8]) != TITLE_TICK_ORIG:
        return None

    def u32(v): return struct.pack("<I", v).hex()

    def post(msg, wparam):
        a.raw("48 89 D9 BA" + u32(msg) + "41 B8" + u32(wparam) + "45 31 C9")
        a._rel("FF15", IAT_POST_MESSAGE)

    a = Asm(va(cave_off))
    a._rel("8A 05", REFOCUS_DONE).raw("84 C0").jne("orig")
    a.raw("B0 01")._rel("88 05", REFOCUS_DONE)
    a.raw("48 83 EC 38 31 C9 31 D2")
    a._rel("4C 8D 05", "thread")
    a.raw("45 31 C9 48 C7 44 24 20 00 00 00 00 48 C7 44 24 28 00 00 00 00")
    a._rel("FF15", IAT_CREATE_THREAD)
    a.raw("48 83 C4 38")
    a.label("orig")
    a._rel("0F B6 05", TITLE_TICK_FLAG).raw("C3")

    a.label("thread")
    a.raw("53 48 83 EC 30")
    a.raw("B9" + u32(REFOCUS_DELAY_MS))._rel("FF15", IAT_SLEEP)
    a._rel("FF15", IAT_GET_FOREGROUND_WINDOW)
    a.raw("48 89 C3 48 85 C0").je("done")
    a.raw("48 89 C1 48 8D 54 24 28")._rel("FF15", IAT_GET_WINDOW_THREAD_PID)
    a._rel("FF15", IAT_GET_CURRENT_PID)
    a.raw("3B 44 24 28").jne("done")
    post(WM_ACTIVATE, 0)
    post(WM_ACTIVATEAPP, 0)
    a.raw("B9" + u32(REFOCUS_GAP_MS))._rel("FF15", IAT_SLEEP)
    post(WM_ACTIVATEAPP, 1)
    post(WM_ACTIVATE, 1)
    a.label("done")
    a.raw("31 C0 48 83 C4 30 5B C3")

    dest = va(cave_off)
    cave_off = _place(data, cave_off, cave_end, a.build())
    _jmp_site(data, TITLE_TICK_IMPL, dest, 8)
    return cave_off
