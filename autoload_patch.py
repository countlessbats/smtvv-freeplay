"""
Auto Load: once per boot, the title menu loads the most recent save by itself.

When the title menu first ticks and at least one save exists, the patch arms
itself. While armed, Blueprint checks for the confirm button being pressed
report a press. The title menu's cursor starts on Load when saves exist, and
the load menu opened from the title starts on the newest save, so the two
presses load that save. The patch disarms as soon as the save starts loading,
or after a timeout, and never arms again until the game is restarted.
"""

from __future__ import annotations

from gameplay_patches import Asm, _place, off, va

ARM_CALL        = 0x140C6FBCC   # EnableCountUpNoInputTime thunk: call impl
ARM_IMPL        = 0x140B8A000
PAD_CHECK_CALL  = 0x140CFDC1E   # IsActionPadCheckCore thunk: call impl
PAD_CHECK_IMPL  = 0x140A849C0   # (controller, action, type, key*) -> bool
DATA_LOAD_CALL  = 0x140D27A7E   # StartDataLoad thunk: call impl
DATA_LOAD_IMPL  = 0x140BDCDF0

SAVE_HEADERS    = 0x1443005B0   # save header array (0x70-byte entries)
SAVE_HEADER_NUM = 0x1443005B8   # entry count; entry +0 == 1 for a used slot
SAVE_HEADER_SIZE = 0x70

STATE           = 0x1549A9801   # 0 idle, 1 armed, 2 done (spare zeroed byte)
ARM_TIME        = 0x1549A9808   # GetTickCount64 at arming
IAT_GET_TICK_COUNT64 = 0x1549AED78

ACTION_DECIDE   = 0
CHECK_PRESSED   = 1
START_DELAY_MS  = 1200          # let the title settle (and refocus) first
TIMEOUT_MS      = 20000


def _call_site(data: bytearray, site: int, impl: int) -> bool:
    o = off(site)
    if data[o] != 0xE8:
        return False
    rel = int.from_bytes(data[o + 1:o + 5], "little", signed=True)
    return site + 5 + rel == impl


def _redirect_call(data: bytearray, site: int, dest: int) -> None:
    o = off(site)
    data[o + 1:o + 5] = (dest - (site + 5)).to_bytes(4, "little", signed=True)


def patch_autoload(data: bytearray, cave_off: int, cave_end: int) -> int | None:
    for site, impl in ((ARM_CALL, ARM_IMPL), (PAD_CHECK_CALL, PAD_CHECK_IMPL),
                       (DATA_LOAD_CALL, DATA_LOAD_IMPL)):
        if not _call_site(data, site, impl):
            return None

    def u32(v): return v.to_bytes(4, "little").hex()

    # Arm on the title menu's first tick if any save slot is in use.
    a = Asm(va(cave_off))
    a._rel("8A 05", STATE).raw("84 C0").jne("arm_tail")
    a._rel("48 8B 05", SAVE_HEADERS)
    a._rel("48 63 0D", SAVE_HEADER_NUM)
    a.raw("B2 02 48 85 C9").jle("arm_store")
    a.label("arm_loop")
    a.raw("83 38 01").je("arm_found")
    a.raw("48 05" + u32(SAVE_HEADER_SIZE) + "48 FF C9").jne("arm_loop")
    a.jmp("arm_store")
    a.label("arm_found")
    a.raw("B2 01")
    a.label("arm_store")
    a._rel("88 15", STATE)
    a.raw("48 83 EC 28")._rel("FF 15", IAT_GET_TICK_COUNT64).raw("48 83 C4 28")
    a._rel("48 89 05", ARM_TIME)
    a.label("arm_tail")
    a.jmp(ARM_IMPL)

    # While armed, report the confirm button as pressed.
    a.label("check")
    a._rel("8A 05", STATE).raw("3C 01").jne("check_tail")
    a.raw("84 D2").jne("check_tail")
    a.raw("41 83 F8" + "%02x" % CHECK_PRESSED).jne("check_tail")
    a.raw("51 52 41 50 41 51 48 83 EC 28")
    a._rel("FF 15", IAT_GET_TICK_COUNT64)
    a.raw("48 83 C4 28 41 59 41 58 5A 59")
    a._rel("48 2B 05", ARM_TIME)
    a.raw("48 3D" + u32(START_DELAY_MS))._rel("0F 82", "check_tail")
    a.raw("48 3D" + u32(TIMEOUT_MS))._rel("0F 83", "check_expire")
    a.raw("B0 01 C3")
    a.label("check_expire")
    a.raw("B0 02")._rel("88 05", STATE)
    a.label("check_tail")
    a.jmp(PAD_CHECK_IMPL)

    # Loading has started: disarm.
    a.label("loaded")
    a.raw("B0 02")._rel("88 05", STATE)
    a.jmp(DATA_LOAD_IMPL)

    base = va(cave_off)
    code = a.build()
    cave_off = _place(data, cave_off, cave_end, code)
    _redirect_call(data, ARM_CALL, base)
    _redirect_call(data, PAD_CHECK_CALL, base + a.labels["check"])
    _redirect_call(data, DATA_LOAD_CALL, base + a.labels["loaded"])
    return cave_off
