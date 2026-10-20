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

  3. Miman Reveal  -- every Miman position is shown on the map.

  4. NG+ Miracles  -- selected NG+ miracles are visible and purchasable
     before clearing the game.

  5. Free Compendium  -- summoning demons from the compendium costs nothing.
     The shared demon-cost formula (used by every compendium price path)
     returns 0.

  6. Item Hacks  -- one of:
     Battle Refill: at the start of every battle, each battle-usable item
     the player has ever obtained is topped up to its carry limit.
     Stockpile: battle items stack to 99, but each battle allows only the
     normal carry limit of each (data pak built from the player's game
     files).

  7. Superjump  -- hold jump to keep rising; faster air movement and
     near-instant turning while airborne.

  8. Free Growth Items  -- Gospels, Grimoires, Sutras, Balms and Incenses
     are sold from the start for 0 Macca (data pak built from the player's
     game files).

  9. Full Magatsuhi  -- the Magatsuhi gauge is filled at the start of every
     battle.

 10. Skip Intro  -- no logo or warning screens, opening movie or "press any
     button" screen; the game boots straight to the title menu (data pak
     built from the player's game files).

 11. Masakado Unlock  -- Masakado offers his powered-up fight without the
     Kiou Sword (data pak built from the player's game files).

 12. Newborn Clears Compendium  -- a New Game+ started with Newborn also
     empties the Demon Compendium; the carry-over lists say so (data pak
     built from the player's game files).

 13. Autosave after battle  -- (optional, --autosave-slot N) the game is
     saved to slot N (1-20) after every battle, once back on the field.

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
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameplay_patches  # noqa: E402
import shop_pak  # noqa: E402
import boot_pak  # noqa: E402
import quest_pak  # noqa: E402
import newborn  # noqa: E402
import stockpile  # noqa: E402
import autosave  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MOD_VERSION = "5.7.41"
FEATURES_FILE = "Freeplay.features"   # installed features, kept next to the executable

EXE_NAME = "SMT5V-Win64-Shipping.exe"
EXE_SUBPATH = os.path.join("Project", "Binaries", "Win64", EXE_NAME)
STEAM_APPID = "1546720"

# NG+ miracle data pak: built at install time from the user's own game data.
# GodParameterDataTable is extracted from pakchunk0 with the bundled repak
# tool, edited, and repacked as a small override pak.
PAKS_SUBPATH = os.path.join("Project", "Content", "Paks")
SOURCE_PAK = "pakchunk0-WindowsNoEditor.pak"
LEGACY_MAP_PAK = "pakchunk95_FreeplayMap_P.pak"   # removed Timed Quest Markers
MIRACLE_PAK = "pakchunk99_NGPlusMiracles_P.pak"
GP_TABLE_ENTRY = ("Project/Content/Blueprints/Gamedata/BinTable/"
                  "GodParameter/Table/GodParameterDataTable")

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

# CheckMimanPositionFlag C++ implementation  (is a miman shown on the map?)
# Signature: bool CheckMimanPositionFlag(int index).  The map asks this when
# it builds its markers; patched to "mov al, 1; ret" so every position shows.
MIMAN_POS_CHECK_OFFSET = 0x00ADB180   # VA 0x140ADBB80
MIMAN_POS_CHECK_ORIG   = bytes.fromhex("48895c240848896c2410488974241857")

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

# Demon cost formula (compendium summon price). Called by
# CalcDevilCost_ByBibleData / _ByDevilData / _ByPartyData; returns the
# Macca cost in EAX. Patched to "xor eax, eax; ret".
DEVIL_COST_OFFSET = 0x00BFB480
DEVIL_COST_ORIG   = bytes.fromhex("4c8bdc49894b0841574881ecc0000000")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def file_to_va(foff: int) -> int:
    return RDATA_VA + (foff - RDATA_RAW)


def find_cc_cave(data: bytes | bytearray, min_size: int = 32,
                 exclude: tuple[int, int] | None = None) -> tuple[int, int] | None:
    """Return (offset, length) of the largest CC-padded region in .rdata,
    optionally ignoring the region exclude = (start, end)."""
    rdata_end = RDATA_RAW + 0x03072A00
    best: tuple[int, int] | None = None
    i = RDATA_RAW
    while i < rdata_end:
        if data[i] == 0xCC:
            j = i
            while j < rdata_end and data[j] == 0xCC:
                j += 1
            length = j - i
            outside = exclude is None or j <= exclude[0] or i >= exclude[1]
            if outside and length >= min_size and (best is None or length > best[1]):
                best = (i, length)
            i = j
        else:
            i += 1
    return best


def find_cc_caves(data: bytes | bytearray, min_size: int, count: int,
                  exclude: tuple[int, int] | None = None) -> list[tuple[int, int]]:
    """Up to count CC-padded regions in .rdata of at least min_size bytes,
    largest first, ignoring the region exclude = (start, end)."""
    rdata_end = RDATA_RAW + 0x03072A00
    found = []
    for m in re.finditer(b"\xCC{%d,}" % min_size, data[RDATA_RAW:rdata_end]):
        i, j = RDATA_RAW + m.start(), RDATA_RAW + m.end()
        if exclude is None or j <= exclude[0] or i >= exclude[1]:
            found.append((i, j - i))
    found.sort(key=lambda c: -c[1])
    return found[:count]


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


def find_repak() -> str | None:
    """Locate the bundled repak binary (fall back to one on PATH)."""
    here = os.path.abspath(os.path.dirname(__file__))
    if platform.system() == "Windows":
        bundled = os.path.join(here, "repak", "win64", "repak.exe")
    else:
        bundled = os.path.join(here, "repak", "linux64", "repak")
    if os.path.isfile(bundled):
        return bundled
    return shutil.which("repak")


def run_repak(repak: str, *args: str) -> bytes:
    """Run repak, returning stdout bytes. Raises RuntimeError on failure."""
    import subprocess
    try:
        proc = subprocess.run([repak, *args], capture_output=True)
    except OSError as exc:
        raise RuntimeError(f"could not run repak: {exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"repak {args[0]} failed: {err or 'unknown error'}")
    return proc.stdout


def build_miracle_pak(game_dir: str) -> None:
    """Extract GodParameterDataTable from the user's pakchunk0, apply the
    NG+ edits (F5=1, F6=0 for the unlocked miracle rows), and pack it as
    an override pak. Raises RuntimeError with a user-facing reason."""
    import tempfile

    paks_dir = os.path.join(game_dir, PAKS_SUBPATH)
    src_pak = os.path.join(paks_dir, SOURCE_PAK)
    if not os.path.isfile(src_pak):
        raise RuntimeError(f"{SOURCE_PAK} not found in {paks_dir}")

    repak = find_repak()
    if repak is None:
        raise RuntimeError("bundled repak tool not found (repak/ folder "
                           "missing from the mod bundle)")

    def get_entry(suffix: str) -> bytes:
        entry = GP_TABLE_ENTRY + suffix
        try:
            return run_repak(repak, "get", src_pak, entry)
        except RuntimeError:
            # Fall back to searching the raw pak listing (no prefix
            # stripping) in case the entry path layout differs from the
            # expected mount point.
            listing = run_repak(repak, "list", "--strip-prefix", "",
                                src_pak)
            base = ("GodParameterDataTable" + suffix).encode()
            for line in listing.splitlines():
                if line.strip().endswith(base):
                    return run_repak(repak, "get", "--strip-prefix", "",
                                     src_pak, line.strip().decode())
            raise

    gp_data = bytearray(get_entry(".uexp"))
    gp_uasset = get_entry(".uasset")

    needed = 89 + max(22, 23, 30, 31) * 20 + 12
    if len(gp_data) < needed:
        raise RuntimeError(f"GodParameterDataTable.uexp is smaller than "
                           f"expected ({len(gp_data)} bytes) — game update?")

    for idx in [22, 23, 30, 31]:
        goff = 89 + idx * 20
        gp_data[goff + 7] = 1
        struct.pack_into("<I", gp_data, goff + 8, 0)

    staging = tempfile.mkdtemp(prefix="smtvv_gp_")
    try:
        table_dir = os.path.join(staging, *GP_TABLE_ENTRY.split("/")[:-1])
        os.makedirs(table_dir, exist_ok=True)
        with open(os.path.join(table_dir, "GodParameterDataTable.uexp"),
                  "wb") as fh:
            fh.write(gp_data)
        with open(os.path.join(table_dir, "GodParameterDataTable.uasset"),
                  "wb") as fh:
            fh.write(gp_uasset)

        pak_out = os.path.join(paks_dir, MIRACLE_PAK)
        pak_tmp = pak_out + ".tmp"
        try:
            run_repak(repak, "pack", "--version", "V11", staging, pak_tmp)
            os.replace(pak_tmp, pak_out)
        finally:
            if os.path.isfile(pak_tmp):
                os.remove(pak_tmp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

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
    parser.add_argument("--no-compendium", action="store_true",
                        help="Skip the Free Compendium patch")
    parser.add_argument("--no-refill", action="store_true",
                        help="Skip the Battle Refill patch")
    parser.add_argument("--stockpile", action="store_true",
                        help="Install Stockpile instead of Battle Refill")
    parser.add_argument("--no-masakado", action="store_true",
                        help="Skip the Masakado Unlock patch")
    parser.add_argument("--no-intro", action="store_true",
                        help="Skip the Skip Intro patch")
    parser.add_argument("--no-magatsuhi", action="store_true",
                        help="Skip the Full Magatsuhi patch")
    parser.add_argument("--no-shop", action="store_true",
                        help="Skip the Free Growth Items shop patch")
    parser.add_argument("--no-jump", action="store_true",
                        help="Skip the Superjump patch")
    parser.add_argument("--no-markers", action="store_true",
                        help=argparse.SUPPRESS)   # removed feature; accepted for old scripts
    parser.add_argument("--no-newborn", action="store_true",
                        help="Skip the Newborn Clears Compendium patch")
    parser.add_argument("--autosave-slot", type=int, metavar="N",
                        choices=range(autosave.SLOT_MIN, autosave.SLOT_MAX + 1),
                        help="Save to slot N (1-20) after every battle")
    args = parser.parse_args()

    do_essences = not args.no_essences
    do_heal     = not args.no_heal
    do_mimans   = not args.no_mimans
    do_miracles = not args.no_miracles
    do_compendium = not args.no_compendium
    do_stockpile = args.stockpile
    do_refill = not args.no_refill and not do_stockpile
    do_jump = not args.no_jump
    do_magatsuhi = not args.no_magatsuhi
    do_intro = not args.no_intro
    do_masakado = not args.no_masakado
    do_shop = not args.no_shop
    do_newborn = not args.no_newborn
    autosave_slot = args.autosave_slot

    game_dir = locate_game_dir(args.game_dir)
    if game_dir is None:
        print("ERROR: Could not find the SMT5V install folder.")
        print("       Use --game-dir <path> to specify it manually.")
        sys.exit(1)

    exe_path  = os.path.join(game_dir, EXE_SUBPATH)
    bak_path  = exe_path + ".original"
    out_path  = exe_path + ".patched"

    print("=" * 62)
    print(f"  SMT5V: Vengeance - Freeplay Patcher v{MOD_VERSION}")
    print("=" * 62)
    print(f"  Game folder : {game_dir}")
    print(f"  Executable  : {exe_path}")
    print()

    # ------------------------------------------------------------------
    # Tidy up state left by earlier installs. The executable is always
    # rebuilt from the original backup, so the override pak must match
    # the patches selected *this* run: remove it here and rebuild it
    # below only if the miracles patch is enabled and succeeds.
    # ------------------------------------------------------------------
    for pak in (MIRACLE_PAK, shop_pak.SHOP_PAK, boot_pak.BOOT_PAK, quest_pak.QUEST_PAK,
                LEGACY_MAP_PAK, newborn.NEWBORN_PAK, stockpile.STOCK_PAK):
        stale_pak = os.path.join(game_dir, PAKS_SUBPATH, pak)
        if os.path.isfile(stale_pak):
            print(f"  Removing previous {pak} (rebuilt if selected)")
            os.remove(stale_pak)

    legacy_extract = os.path.join(game_dir, PAKS_SUBPATH,
                                  "pakchunk0-WindowsNoEditor")
    if os.path.isdir(legacy_extract):
        print(f"  NOTE: extracted game data at "
              f"Paks{os.sep}pakchunk0-WindowsNoEditor{os.sep} is no longer")
        print(f"        needed by this mod and can be deleted to free space.")

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
                                ("Miracles", do_miracles),
                                ("Compendium", do_compendium),
                                ("Refill", do_refill),
                                ("Stockpile", do_stockpile),
                                ("Jump", do_jump),
                                ("Magatsuhi", do_magatsuhi),
                                ("Shop", do_shop),
                                ("Intro", do_intro),
                                ("Masakado", do_masakado),
                                ("Newborn", do_newborn),
                                ("Autosave", autosave_slot is not None)] if on]
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
    # PATCH: Leyline Auto-Heal
    # ==================================================================
    if do_heal:
        ry_actual = bytes(data[RYUKETSU_TRAMP_OFFSET : RYUKETSU_TRAMP_OFFSET + 5])
        if ry_actual != RYUKETSU_TRAMP_ORIG:
            print(f"\n  WARNING: Leyline AOB mismatch — skipping heal patch")
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
            hsc += b"\xE8"                     # call PartyAllCure
            cf = h_va + len(hsc) + 4
            hsc += struct.pack("<i", PARTY_ALL_CURE_VA - cf)
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

            patch_num += 1
            print(f"\n  [{patch_num}/{total}] Leyline Auto-Heal")
            print(f"    Code cave     : 0x{h_off:08X}  ({len(hsc)} bytes)")
            print(f"    Trampoline    : 0x{RYUKETSU_TRAMP_OFFSET:08X}  -> cave")
            next_cave_off = h_off + ((len(hsc) + 15) & ~15)

    # ==================================================================
    # PATCH: Miman Reveal
    # ==================================================================
    if do_mimans:
        actual = bytes(data[MIMAN_POS_CHECK_OFFSET : MIMAN_POS_CHECK_OFFSET + 16])
        if actual != MIMAN_POS_CHECK_ORIG:
            print(f"\n  WARNING: Miman AOB mismatch at "
                  f"0x{MIMAN_POS_CHECK_OFFSET:08X} - skipping")
        else:
            data[MIMAN_POS_CHECK_OFFSET : MIMAN_POS_CHECK_OFFSET + 3] = b"\xB0\x01\xC3"
            patch_num += 1
            print(f"\n  [{patch_num}/{total}] Miman Reveal")
            print(f"    Position check: 0x{MIMAN_POS_CHECK_OFFSET:08X}  -> true")

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

        # 3. Build data pak from the user's own game data
        #    (F5=1, F6=0, keep original Glory costs)
        if miracles_ok:
            try:
                build_miracle_pak(game_dir)
                print(f"    Data pak      : {MIRACLE_PAK}")
            except RuntimeError as exc:
                print(f"    WARNING: NG+ miracle data pak not built — {exc}")
                print(f"             The miracle shop hooks are still "
                      f"installed, but some NG+ miracles may stay locked.")

    # ==================================================================
    # PATCH: Free Compendium
    # ==================================================================
    if do_compendium:
        actual = bytes(data[DEVIL_COST_OFFSET : DEVIL_COST_OFFSET + 16])
        if actual != DEVIL_COST_ORIG:
            print(f"\n  WARNING: Compendium AOB mismatch at "
                  f"0x{DEVIL_COST_OFFSET:08X} - skipping")
        else:
            data[DEVIL_COST_OFFSET : DEVIL_COST_OFFSET + 3] = b"\x33\xC0\xC3"
            patch_num += 1
            print(f"\n  [{patch_num}/{total}] Free Compendium")
            print(f"    Cost formula  : 0x{DEVIL_COST_OFFSET:08X}  -> 0")

    # ==================================================================
    # PATCH: Battle Refill / Superjump / Full Magatsuhi
    # ==================================================================
    cave_end = cave_off + cave_len
    # ==================================================================
    # PATCH: Stockpile (exe + item list pak; reads the ItemTable carry limits)
    # ==================================================================
    stockpile_ok = False
    if do_stockpile:
        repak = find_repak()
        try:
            if repak is None:
                raise RuntimeError("bundled repak tool not found")
            item_asset, item_exp = stockpile.read_item_table(game_dir, PAKS_SUBPATH, SOURCE_PAK,
                                                         repak, run_repak)
            limits = stockpile.battle_item_limits(item_exp)
            start = next_cave_off
            side = find_cc_caves(data, min_size=96, count=3, exclude=(cave_off, cave_end))
            if not side:
                raise RuntimeError("no second code cave")
            trial = bytearray(data)       # applied only if the whole patch fits
            result = stockpile.patch_stockpile(trial, next_cave_off, cave_end, limits,
                                            [[o, o + n] for o, n in side])
            if result is None:
                raise RuntimeError("AOB mismatch")
            data[:] = trial
            del trial
            next_cave_off = result
            stockpile_ok = True
            patch_num += 1
            print(f"\n  [{patch_num}/{total}] Stockpile")
            print(f"    Code cave     : 0x{start:08X}  ({next_cave_off - start} bytes)")
            print(f"    Battle items  : {len(limits)} can be stocked to {stockpile.STOCK_MAX}")
        except RuntimeError as exc:
            print(f"\n  WARNING: Stockpile skipped - {exc}")
        if stockpile_ok:
            try:
                stockpile.build_stock_pak(game_dir, PAKS_SUBPATH, SOURCE_PAK, repak, run_repak)
                print(f"    Data pak      : {stockpile.STOCK_PAK}")
            except RuntimeError as exc:
                print(f"    WARNING: Stockpile data pak not built - {exc}")

    for on, label, builder in ((do_refill, "Battle Refill", gameplay_patches.patch_refill),
                               (do_jump, "Superjump", gameplay_patches.patch_jump)):
        if not on:
            continue
        start = next_cave_off
        result = builder(data, next_cave_off, cave_end)
        if result is None:
            print(f"\n  WARNING: {label} AOB mismatch - skipping")
            continue
        next_cave_off = result
        patch_num += 1
        print(f"\n  [{patch_num}/{total}] {label}")
        print(f"    Code cave     : 0x{start:08X}  ({next_cave_off - start} bytes)")

    # ==================================================================
    # PATCH: Full Magatsuhi / Autosave after battle (section padding caves)
    # ==================================================================
    slack = None
    if do_magatsuhi or autosave_slot is not None:
        trial = bytearray(data)
        slack = gameplay_patches.slack_caves(trial)
        data[:] = trial                   # padding refilled with CC only
        del trial
    if do_magatsuhi:
        try:
            trial = bytearray(data)       # applied only if the whole patch fits
            if not gameplay_patches.patch_magatsuhi(trial, slack):
                raise RuntimeError("AOB mismatch")
            data[:] = trial
            del trial
            patch_num += 1
            print(f"\n  [{patch_num}/{total}] Full Magatsuhi")
        except RuntimeError as exc:
            print(f"\n  WARNING: Full Magatsuhi skipped - {exc}")
    if autosave_slot is not None:
        area_labels = None
        try:
            repak = find_repak()
            if repak is None:
                raise RuntimeError("bundled repak tool not found")
            area_labels = autosave.read_area_labels(game_dir, PAKS_SUBPATH, SOURCE_PAK,
                                                    repak, run_repak)
        except Exception as exc:
            print(f"\n  NOTE: Autosave location names unavailable - {exc}")
        try:
            trial = bytearray(data)
            if not autosave.patch_autosave(trial, slack, autosave_slot, area_labels):
                raise RuntimeError("AOB mismatch")
            data[:] = trial
            del trial
            patch_num += 1
            print(f"\n  [{patch_num}/{total}] Autosave after battle")
            print(f"    Save slot     : {autosave_slot}")
            if area_labels:
                print(f"    Location names: {len(area_labels)}")
        except RuntimeError as exc:
            print(f"\n  WARNING: Autosave skipped - {exc}")

    # ==================================================================
    # PATCH: Free Growth Items (data pak only)
    # ==================================================================
    if do_shop:
        patch_num += 1
        print(f"\n  [{patch_num}/{total}] Free Growth Items")
        repak = find_repak()
        try:
            if repak is None:
                raise RuntimeError("bundled repak tool not found")
            shop_pak.build_shop_pak(game_dir, PAKS_SUBPATH, SOURCE_PAK, repak, run_repak)
            print(f"    Data pak      : {shop_pak.SHOP_PAK}")
        except RuntimeError as exc:
            print(f"    WARNING: shop data pak not built - {exc}")

    # ==================================================================
    # PATCH: Skip Intro (data pak + title refocus)
    # ==================================================================
    if do_intro:
        patch_num += 1
        print(f"\n  [{patch_num}/{total}] Skip Intro")
        repak = find_repak()
        try:
            if repak is None:
                raise RuntimeError("bundled repak tool not found")
            boot_pak.build_boot_pak(game_dir, PAKS_SUBPATH, SOURCE_PAK, repak, run_repak)
            print(f"    Data pak      : {boot_pak.BOOT_PAK}")
        except RuntimeError as exc:
            print(f"    WARNING: intro data pak not built - {exc}")
        start = next_cave_off
        result = gameplay_patches.patch_refocus(data, next_cave_off, cave_end)
        if result is None:
            print("    WARNING: title refocus AOB mismatch - skipping")
        else:
            next_cave_off = result
            print(f"    Code cave     : 0x{start:08X}  ({next_cave_off - start} bytes)")

    # ==================================================================
    # PATCH: Masakado Unlock (data pak only)
    # ==================================================================
    if do_masakado:
        patch_num += 1
        print(f"\n  [{patch_num}/{total}] Masakado Unlock")
        repak = find_repak()
        try:
            if repak is None:
                raise RuntimeError("bundled repak tool not found")
            quest_pak.build_quest_pak(game_dir, PAKS_SUBPATH, repak, run_repak)
            print(f"    Data pak      : {quest_pak.QUEST_PAK}")
        except RuntimeError as exc:
            print(f"    WARNING: quest data pak not built - {exc}")

    # ==================================================================
    # PATCH: Newborn Clears Compendium (exe + text pak)
    # ==================================================================
    if do_newborn:
        start = next_cave_off
        result = newborn.patch_newborn(data, next_cave_off, cave_end)
        if result is None:
            print("\n  WARNING: Newborn Clears Compendium AOB mismatch - skipping")
        else:
            next_cave_off = result
            patch_num += 1
            print(f"\n  [{patch_num}/{total}] Newborn Clears Compendium")
            print(f"    Code cave     : 0x{start:08X}  ({next_cave_off - start} bytes)")
            repak = find_repak()
            try:
                if repak is None:
                    raise RuntimeError("bundled repak tool not found")
                newborn.build_newborn_pak(game_dir, PAKS_SUBPATH, repak, run_repak)
                print(f"    Data pak      : {newborn.NEWBORN_PAK}")
            except RuntimeError as exc:
                print(f"    WARNING: carry-over text pak not built - {exc}")

    # ------------------------------------------------------------------
    # Backup & save
    # ------------------------------------------------------------------
    if not os.path.isfile(bak_path):
        print(f"\n  Backing up original -> {os.path.basename(bak_path)}")
        shutil.copy2(exe_path, bak_path)

    print(f"  Writing patched -> {os.path.basename(out_path)}")
    with open(out_path, "wb") as fh:
        fh.write(data)

    # Feature record for the installer; it becomes FEATURES_FILE once the
    # patched executable is in place.
    features = {"essences": do_essences, "heal": do_heal, "mimans": do_mimans,
                "miracles": do_miracles, "compendium": do_compendium, "jump": do_jump,
                "shop": do_shop, "magatsuhi": do_magatsuhi, "intro": do_intro,
                "masakado": do_masakado, "newborn": do_newborn}
    lines = [f"{k}={int(v)}" for k, v in features.items()]
    lines.append("itemhacks=" + ("stockpile" if do_stockpile else "refill" if do_refill else "none"))
    lines.append(f"autosave={autosave_slot or 0}")
    with open(os.path.join(os.path.dirname(out_path), FEATURES_FILE + ".new"), "w",
              newline="\r\n") as fh:
        fh.write("\n".join(lines) + "\n")

    print()
    print("  " + "-" * 58)
    print("  Next steps:")
    print("    * install.bat / install.sh activates the patched EXE")
    print("    * uninstall.bat / uninstall.sh restores the original")
    print("  " + "-" * 58)


if __name__ == "__main__":
    main()
