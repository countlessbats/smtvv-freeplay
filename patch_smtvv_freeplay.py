"""
SMT5V: Vengeance - Freeplay Patcher
===================================
Applies quality-of-life patches to the game executable and optional data paks:

  1. Reusable Essences  -- essences are not consumed when used.
     Redirects the ItemErase trampoline (0x00ACDD40) through a code cave
     that skips erasure for item IDs 311-615 (the essence range).

  2. Leyline Auto-Heal  -- full party HP/MP restored on leyline access.
     Hooks SetRyuketsuSaveAccess (0x00CD57D0) to call PartyAllCure
     (VA 0x140AB94B0) before the original leyline logic runs.

  3. Miman Reveal  -- leyline access marks Miman map positions as revealed.

  4. NG+ Miracles  -- selected NG+ miracles are visible and purchasable
     before clearing the game.

Note on Flight:

  * Flight is a runtime DLL (xinput1_3.dll), not an executable patch, so it is
    deployed by install.bat (copied into Project/Binaries/Win64), not by this
    script. This patcher only handles the executable / pak patches above.

Executable patches share the same large CC cave in .rdata.

Usage
-----
    python patch_smtvv_freeplay.py [--game-dir <path>]

If --game-dir is not supplied the script tries to auto-detect the game
from common Steam library locations.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import struct
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXE_NAME = "SMT5V-Win64-Shipping.exe"
EXE_SUBPATH = os.path.join("Project", "Binaries", "Win64", EXE_NAME)
STEAM_APPID = "1546720"

# Essence item-ID range (inclusive)
ESSENCE_ID_MIN = 311   # 0x137
ESSENCE_ID_MAX = 615   # 0x267

# PE section layout (for VA <-> file-offset conversion in .rdata)
RDATA_RAW  = 0x600
RDATA_VA   = 0x140001000

# ItemErase implementation trampoline
# This 5-byte JMP (E9 xx xx xx xx) is the single bottleneck through which
# every item-erase call passes.  Seven call-sites total.
TRAMP_OFFSET = 0x00ACDD40
TRAMP_ORIG   = bytes([0xE9, 0xEB, 0x6F, 0x8C, 0x06])

# SetRyuketsuSaveAccess exec trampoline  (leyline fount access entry point)
# NOTE: 0x00CD5700 is the FName-init trampoline (called at startup — do NOT
# touch it).  0x00CDB6C0 is the *exec-body* trampoline, invoked only when
# the player actually accesses a leyline fount.
RYUKETSU_TRAMP_OFFSET = 0x00CDB6C0
RYUKETSU_TRAMP_ORIG   = bytes([0xE9, 0x8B, 0xD5, 0x65, 0x0A])

# PartyAllCure C++ implementation  (full party HP/MP restore)
# Self-contained: fetches NkmDataManager singleton internally,
# so it can be called with any register state.
PARTY_ALL_CURE_VA = 0x140AB94B0

# SetMimanPositionFlag C++ implementation  (reveal miman map positions)
# Self-contained: fetches MapDataManager singleton internally.
# Signature: SetMimanPositionFlag(int index, bool revealed)
#   ECX = miman save-buffer index,  DL = 1 to reveal
SET_MIMAN_POS_FLAG_VA = 0x140AE28B0   # VA of impl at file 0x00AE1EB0
MIMAN_INDEX_MAX = 200                  # generous upper bound (game has ~200 mimans)

# NG+ Miracle unlock patches
# IsAddedSelectableGodParameterSkill trampoline — controls shop visibility
MIRACLE_ADDED_TRAMP  = 0x00ACBD90
MIRACLE_ADDED_ORIG   = bytes([0xE9, 0xEB, 0x37, 0x89, 0x06])

# GetGodParameterSkillState trampoline — controls miracle purchasability
MIRACLE_STATE_TRAMP  = 0x00ACB780
MIRACLE_STATE_ORIG   = bytes([0xE9, 0x5B, 0xEB, 0x88, 0x06])

# Hardcoded "cmp ecx, 666; je BLOCK" that hides Divine Persuasion
MIRACLE_666_NOP_ADDR = 0x00551AEE   # 6-byte JE instruction to NOP

# Miracle IDs/enums to force-unlock (both 0-based and 1-based to cover
# all code paths: some functions use enum=ID-1, others use raw ID)
MIRACLE_UNLOCK_IDS   = [22, 23, 24, 30, 31, 32]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def file_to_va(foff: int) -> int:
    return RDATA_VA + (foff - RDATA_RAW)


def find_cc_cave(data: bytes | bytearray, min_size: int = 32) -> tuple[int, int] | None:
    """Return (offset, length) of the largest CC-padded region in .rdata."""
    rdata_end = RDATA_RAW + 0x03072A00
    best: tuple[int, int] | None = None
    i = RDATA_RAW
    while i < rdata_end:
        if data[i] == 0xCC:
            j = i
            while j < rdata_end and data[j] == 0xCC:
                j += 1
            length = j - i
            if length >= min_size and (best is None or length > best[1]):
                best = (i, length)
            i = j
        else:
            i += 1
    return best


def locate_game_dir(hint: str | None = None) -> str | None:
    """Try to find the SMT5V install folder."""
    candidates: list[str] = []

    if hint:
        candidates.append(hint)

    # Common Steam library roots (Windows)
    if platform.system() == "Windows":
        for drive in "CDEFGH":
            candidates.append(os.path.join(f"{drive}:\\", "SteamLibrary",
                              "steamapps", "common", "SMT5V"))
            candidates.append(os.path.join(f"{drive}:\\", "Program Files (x86)",
                              "Steam", "steamapps", "common", "SMT5V"))
            candidates.append(os.path.join(f"{drive}:\\", "Program Files",
                              "Steam", "steamapps", "common", "SMT5V"))

    # Check if we're already inside the game tree
    here = os.path.abspath(os.path.dirname(__file__))
    parts = here.replace("\\", "/").split("/")
    for i, p in enumerate(parts):
        if p.upper() == "SMT5V":
            candidates.insert(0, os.sep.join(parts[: i + 1]))

    for c in candidates:
        exe = os.path.join(c, EXE_SUBPATH)
        if os.path.isfile(exe):
            return c

    return None

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SMT5V: Vengeance - Freeplay Patcher")
    parser.add_argument("--game-dir", default=None,
                        help="Path to the SMT5V install folder")
    parser.add_argument("--no-essences", action="store_true",
                        help="Skip the Reusable Essences patch")
    parser.add_argument("--no-heal", action="store_true",
                        help="Skip the Leyline Auto-Heal patch")
    parser.add_argument("--no-mimans", action="store_true",
                        help="Skip the Miman Position Reveal patch")
    parser.add_argument("--no-miracles", action="store_true",
                        help="Skip the NG+ Miracles Unlock patch")
    args = parser.parse_args()

    do_essences = not args.no_essences
    do_heal     = not args.no_heal
    do_mimans   = not args.no_mimans
    do_miracles = not args.no_miracles

    game_dir = locate_game_dir(args.game_dir)
    if game_dir is None:
        print("ERROR: Could not find the SMT5V install folder.")
        print("       Use --game-dir <path> to specify it manually.")
        sys.exit(1)

    exe_path  = os.path.join(game_dir, EXE_SUBPATH)
    bak_path  = exe_path + ".original"
    out_path  = exe_path + ".patched"

    print("=" * 62)
    print("  SMT5V: Vengeance - Freeplay Patcher")
    print("=" * 62)
    print(f"  Game folder : {game_dir}")
    print(f"  Executable  : {exe_path}")
    print()

    # Always patch from the original backup if one exists
    source = bak_path if os.path.isfile(bak_path) else exe_path
    print(f"  Reading {os.path.basename(source)} ...")
    with open(source, "rb") as fh:
        data = bytearray(fh.read())
    print(f"  File size: {len(data):,} bytes")

    # ------------------------------------------------------------------
    # Find code cave (shared by all patches)
    # ------------------------------------------------------------------
    cave = find_cc_cave(data, min_size=128)
    if cave is None:
        print("\n  ERROR: no suitable CC cave found in .rdata.")
        sys.exit(1)
    cave_off, cave_len = cave
    next_cave_off = cave_off
    patch_num = 0
    enabled = [n for n, on in [("Essences", do_essences),
                                ("Heal", do_heal),
                                ("Mimans", do_mimans),
                                ("Miracles", do_miracles)] if on]
    total = len(enabled)

    if total == 0:
        print("\n  All patches disabled — nothing to do.")
        sys.exit(0)

    print(f"\n  Patches selected: {', '.join(enabled)}")

    # ==================================================================
    # PATCH: Reusable Essences
    # ==================================================================
    if do_essences:
        actual = bytes(data[TRAMP_OFFSET : TRAMP_OFFSET + 5])
        if actual != TRAMP_ORIG:
            print(f"\n  ERROR: Essence AOB mismatch at 0x{TRAMP_OFFSET:08X}")
            sys.exit(1)

        orig_disp   = struct.unpack_from("<i", data, TRAMP_OFFSET + 1)[0]
        tramp_va    = file_to_va(TRAMP_OFFSET)
        orig_target = tramp_va + 5 + orig_disp
        p_off       = next_cave_off
        p_va        = file_to_va(p_off)

        sc = bytearray()
        sc += b"\x81\xF9"; sc += struct.pack("<I", ESSENCE_ID_MIN)  # cmp ecx, 311
        sc += b"\x72";     jb_pos = len(sc); sc += b"\x00"          # jb .pass
        sc += b"\x81\xF9"; sc += struct.pack("<I", ESSENCE_ID_MAX)  # cmp ecx, 615
        sc += b"\x77";     ja_pos = len(sc); sc += b"\x00"          # ja .pass
        sc += b"\xC3"                                                 # ret (skip)
        not_ess = len(sc)
        sc[jb_pos] = not_ess - (jb_pos + 1)
        sc[ja_pos] = not_ess - (ja_pos + 1)
        sc += b"\xE9"                                                 # jmp original
        sc += struct.pack("<i", orig_target - (p_va + len(sc) + 4))

        for i in range(len(sc)):
            assert data[p_off + i] == 0xCC
        data[p_off : p_off + len(sc)] = sc
        struct.pack_into("<i", data, TRAMP_OFFSET + 1, p_va - (tramp_va + 5))

        patch_num += 1
        print(f"\n  [{patch_num}/{total}] Reusable Essences")
        print(f"    Code cave     : 0x{p_off:08X}  ({len(sc)} bytes)")
        print(f"    Trampoline    : 0x{TRAMP_OFFSET:08X}  -> cave")
        next_cave_off = p_off + ((len(sc) + 15) & ~15)

    # ==================================================================
    # PATCH: Leyline hook (Heal + Mimans share the same hook point)
    # ==================================================================
    if do_heal or do_mimans:
        ry_actual = bytes(data[RYUKETSU_TRAMP_OFFSET : RYUKETSU_TRAMP_OFFSET + 5])
        if ry_actual != RYUKETSU_TRAMP_ORIG:
            print(f"\n  WARNING: Leyline AOB mismatch — skipping heal/miman patches")
        else:
            ry_disp     = struct.unpack_from("<i", data, RYUKETSU_TRAMP_OFFSET + 1)[0]
            ry_tramp_va = file_to_va(RYUKETSU_TRAMP_OFFSET)
            ry_orig_tgt = ry_tramp_va + 5 + ry_disp

            h_off = next_cave_off
            h_va  = file_to_va(h_off)

            hsc = bytearray()
            hsc += b"\x51"                     # push rcx
            hsc += b"\x52"                     # push rdx
            hsc += b"\x41\x50"                 # push r8
            hsc += b"\x41\x51"                 # push r9
            hsc += b"\x53"                     # push rbx
            hsc += b"\x48\x83\xEC\x20"        # sub rsp, 20h

            if do_heal:
                hsc += b"\xE8"                 # call PartyAllCure
                cf = h_va + len(hsc) + 4
                hsc += struct.pack("<i", PARTY_ALL_CURE_VA - cf)

            if do_mimans:
                hsc += b"\x33\xDB"             # xor ebx, ebx
                loop_top = len(hsc)
                hsc += b"\x8B\xCB"             # mov ecx, ebx
                hsc += b"\xB2\x01"             # mov dl, 1
                hsc += b"\xE8"                 # call SetMimanPositionFlag
                cf2 = h_va + len(hsc) + 4
                hsc += struct.pack("<i", SET_MIMAN_POS_FLAG_VA - cf2)
                hsc += b"\xFF\xC3"             # inc ebx
                hsc += b"\x81\xFB"             # cmp ebx, MAX
                hsc += struct.pack("<I", MIMAN_INDEX_MAX)
                jl_off = loop_top - (len(hsc) + 2)
                hsc += b"\x7C"
                hsc += struct.pack("b", jl_off)

            hsc += b"\x48\x83\xC4\x20"        # add rsp, 20h
            hsc += b"\x5B"                     # pop rbx
            hsc += b"\x41\x59"                 # pop r9
            hsc += b"\x41\x58"                 # pop r8
            hsc += b"\x5A"                     # pop rdx
            hsc += b"\x59"                     # pop rcx
            hsc += b"\xE9"                     # jmp original
            hsc += struct.pack("<i", ry_orig_tgt - (h_va + len(hsc) + 4))

            for i in range(len(hsc)):
                assert data[h_off + i] == 0xCC
            data[h_off : h_off + len(hsc)] = hsc
            struct.pack_into("<i", data, RYUKETSU_TRAMP_OFFSET + 1,
                             h_va - (ry_tramp_va + 5))

            parts = []
            if do_heal:
                parts.append("Auto-Heal")
            if do_mimans:
                parts.append(f"Reveal Mimans (x{MIMAN_INDEX_MAX})")
            patch_num += 1
            print(f"\n  [{patch_num}/{total}] Leyline: {' + '.join(parts)}")
            print(f"    Code cave     : 0x{h_off:08X}  ({len(hsc)} bytes)")
            print(f"    Trampoline    : 0x{RYUKETSU_TRAMP_OFFSET:08X}  -> cave")
            next_cave_off = h_off + ((len(hsc) + 15) & ~15)

    # ==================================================================
    # PATCH: NG+ Miracles Unlock
    # ==================================================================
    if do_miracles:
        miracles_ok = True

        # 1. NOP the hardcoded "cmp ecx, 666; je BLOCK"
        expected_je = bytes([0x0F, 0x84])
        if data[MIRACLE_666_NOP_ADDR : MIRACLE_666_NOP_ADDR + 2] == expected_je:
            for i in range(6):
                data[MIRACLE_666_NOP_ADDR + i] = 0x90
        else:
            print(f"\n  WARNING: 666-block AOB mismatch — skipping NOP")
            miracles_ok = False

        # 2. Hook IsAddedSelectableGodParameterSkill -> true for NG+ IDs
        ma_actual = bytes(data[MIRACLE_ADDED_TRAMP : MIRACLE_ADDED_TRAMP + 5])
        ms_actual = bytes(data[MIRACLE_STATE_TRAMP : MIRACLE_STATE_TRAMP + 5])

        if ma_actual != MIRACLE_ADDED_ORIG:
            print(f"\n  WARNING: IsAdded AOB mismatch")
            miracles_ok = False
        if ms_actual != MIRACLE_STATE_ORIG:
            print(f"\n  WARNING: GetState AOB mismatch")
            miracles_ok = False

        if miracles_ok:
            # Hook IsAddedSelectable
            ma_disp = struct.unpack_from("<i", data, MIRACLE_ADDED_TRAMP + 1)[0]
            ma_va   = file_to_va(MIRACLE_ADDED_TRAMP)
            ma_tgt  = ma_va + 5 + ma_disp

            mc1 = next_cave_off
            sc_a = bytearray()
            je_a = []
            for mid in MIRACLE_UNLOCK_IDS:
                sc_a += b"\x83\xF9" + bytes([mid]) + b"\x74"
                je_a.append(len(sc_a)); sc_a += b"\x00"
            sc_a += b"\xE9"
            sc_a += struct.pack("<i", ma_tgt - (file_to_va(mc1) + len(sc_a) + 4))
            yes_a = len(sc_a)
            for jp in je_a:
                sc_a[jp] = yes_a - (jp + 1)
            sc_a += b"\xB0\x01\xC3"

            for i in range(len(sc_a)):
                assert data[mc1 + i] == 0xCC
            data[mc1 : mc1 + len(sc_a)] = sc_a
            data[MIRACLE_ADDED_TRAMP] = 0xE9
            struct.pack_into("<i", data, MIRACLE_ADDED_TRAMP + 1,
                             file_to_va(mc1) - (ma_va + 5))
            next_cave_off = mc1 + ((len(sc_a) + 15) & ~15)

            # Hook GetGodParameterSkillState -> return 4 (purchasable)
            ms_disp = struct.unpack_from("<i", data, MIRACLE_STATE_TRAMP + 1)[0]
            ms_va   = file_to_va(MIRACLE_STATE_TRAMP)
            ms_tgt  = ms_va + 5 + ms_disp

            mc2 = next_cave_off
            sc_s = bytearray()
            je_s = []
            for mid in MIRACLE_UNLOCK_IDS:
                sc_s += b"\x83\xF9" + bytes([mid]) + b"\x74"
                je_s.append(len(sc_s)); sc_s += b"\x00"
            sc_s += b"\xE9"
            sc_s += struct.pack("<i", ms_tgt - (file_to_va(mc2) + len(sc_s) + 4))
            yes_s = len(sc_s)
            for jp in je_s:
                sc_s[jp] = yes_s - (jp + 1)
            sc_s += b"\xB0\x04\xC3"

            for i in range(len(sc_s)):
                assert data[mc2 + i] == 0xCC
            data[mc2 : mc2 + len(sc_s)] = sc_s
            data[MIRACLE_STATE_TRAMP] = 0xE9
            struct.pack_into("<i", data, MIRACLE_STATE_TRAMP + 1,
                             file_to_va(mc2) - (ms_va + 5))
            next_cave_off = mc2 + ((len(sc_s) + 15) & ~15)

            patch_num += 1
            print(f"\n  [{patch_num}/{total}] NG+ Miracles Unlock")
            print(f"    Code caves    : 0x{mc1:08X} ({len(sc_a)}B)"
                  f" + 0x{mc2:08X} ({len(sc_s)}B)")
            print(f"    NOP 666-block : 0x{MIRACLE_666_NOP_ADDR:08X}")

        # 3. Create data pak (F5=1, F6=0, keep original Glory costs)
        if miracles_ok:
            pak_src = os.path.join(game_dir, "Project", "Content", "Paks",
                        "pakchunk0-WindowsNoEditor")
            gp_uexp = os.path.join(pak_src, "Project", "Content", "Blueprints",
                        "Gamedata", "BinTable", "GodParameter", "Table",
                        "GodParameterDataTable.uexp")
            gp_uasset = gp_uexp.replace(".uexp", ".uasset")

            if os.path.isfile(gp_uexp):
                import tempfile
                with open(gp_uexp, "rb") as fh:
                    gp_data = bytearray(fh.read())

                for idx in [22, 23, 30, 31]:
                    goff = 89 + idx * 20
                    gp_data[goff + 7] = 1
                    struct.pack_into("<I", gp_data, goff + 8, 0)

                pak_dir = os.path.join(tempfile.gettempdir(), "gp_mod",
                            "Project", "Content", "Blueprints", "Gamedata",
                            "BinTable", "GodParameter", "Table")
                os.makedirs(pak_dir, exist_ok=True)

                uexp_out = os.path.join(pak_dir, "GodParameterDataTable.uexp")
                uasset_out = os.path.join(pak_dir, "GodParameterDataTable.uasset")

                import subprocess
                shutil.copy2(gp_uasset, uasset_out)

                with open(uexp_out, "wb") as fh:
                    fh.write(gp_data)

                pak_root = os.path.join(tempfile.gettempdir(), "gp_mod")
                pak_out = os.path.join(game_dir, "Project", "Content", "Paks",
                            "pakchunk99_NGPlusMiracles_P.pak")
                subprocess.run(["repak", "pack", "--version", "V11",
                                pak_root, pak_out],
                               check=True, capture_output=True)
                print(f"    Data pak      : {os.path.basename(pak_out)}")
            else:
                print(f"    WARNING: GodParameterDataTable not extracted — "
                      f"run repak unpack first")

    # ------------------------------------------------------------------
    # Backup & save
    # ------------------------------------------------------------------
    if not os.path.isfile(bak_path):
        print(f"\n  Backing up original -> {os.path.basename(bak_path)}")
        shutil.copy2(exe_path, bak_path)

    print(f"  Writing patched -> {os.path.basename(out_path)}")
    with open(out_path, "wb") as fh:
        fh.write(data)

    print()
    print("  " + "-" * 58)
    print("  Next steps:")
    print("    * Run  install.bat   to activate the mod")
    print("    * Run  uninstall.bat to restore the original EXE")
    print("    * Or use Steam -> Verify Integrity to revert any time")
    print("  " + "-" * 58)


if __name__ == "__main__":
    main()
