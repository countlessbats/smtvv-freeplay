# SMT5V: Vengeance - Freeplay Mod

Quality-of-life patch bundle for Shin Megami Tensei V: Vengeance.

## Features

1. **Reusable Essences** - essences are no longer consumed when used.
   Discover an essence once, then apply it repeatedly for skills or
   resistances.

2. **Miman Reveal** - Miman positions are pre-revealed on the map when
   leyline logic runs.

3. **Leyline Auto-Heal** - accessing a leyline fount restores the full
   party's HP and MP for free.

4. **NG+ Miracles From Start** - selected NG+ miracle gates are bypassed so
   they are available without a cleared save.

## Requirements

- Shin Megami Tensei V: Vengeance — the **Steam** version, on Windows or
  Steam Deck / Linux (via Proton). Game Pass / Microsoft Store editions use a
  different executable and are not supported.
- No separate Python install is required when using the packaged release.
  A portable Python runtime is included (Windows); on Linux it uses `python3`.
- Nothing else to download: the [repak](https://github.com/trumank/repak)
  pak tool used by the NG+ Miracles patch is bundled (`repak/`, MIT/Apache-2.0
  licensed) for both Windows and Linux/Steam Deck.

See **[INSTALL.md](INSTALL.md)** for the full step-by-step. Quick version below.

## Install (Windows)

1. Place this folder inside or near your SMT5V install directory. The
   installer also searches common Steam library locations automatically,
   and if it still can't find the game it asks you to paste your SMT5V
   folder path (in Steam: right-click SMT5V > Manage > Browse local files,
   then copy the path from the address bar).

2. Double-click `install.bat`.

3. Choose all patches, or pick individual ones (Reusable Essences,
   Leyline Auto-Heal, Miman Reveal, NG+ Miracles).

The installer backs up the original executable as:

```text
Project/Binaries/Win64/SMT5V-Win64-Shipping.exe.original
```

It writes the patched executable as:

```text
Project/Binaries/Win64/SMT5V-Win64-Shipping.exe.patched
```

Then it installs the patched executable over the live executable.

## Steam Deck / Linux

Steam Deck runs the same Steam Windows build through Proton, so the patches are
identical. Only the installer differs. In **Desktop Mode**, open the extracted
`SMTVV Freeplay` folder in a terminal (Konsole), or `cd` into it, and run:

```bash
chmod +x install.sh
./install.sh
```

With no switches, it installs all four features. To install only some of them,
add a skip-switch for each feature you do **not** want:

```text
--no-essences
--no-heal
--no-mimans
--no-miracles
```

For example, to install only Reusable Essences and Miman Reveal, skipping
Leyline Auto-Heal and NG+ Miracles:

```bash
./install.sh --no-heal --no-miracles
```

You leave out the switch for anything you want to keep, and add the switch for
anything you want to skip. If the script can't find the game automatically, it
will ask you to paste your SMT5V folder path.

Uninstall with `./uninstall.sh`. (`python3`, used by the patcher, ships with
Desktop Mode.)

If you previously installed an older build with Superjump, remove the old
`WINEDLLOVERRIDES="xinput1_3=n,b" %command%` launch option. The current
installers also remove the known legacy Superjump DLL when they find it.

## Manual Usage

```powershell
python patch_smtvv_freeplay.py
python patch_smtvv_freeplay.py --game-dir "D:\Games\SMT5V"
```

Optional patch flags:

```text
--no-essences
--no-heal
--no-mimans
--no-miracles
```

`patch_essences.py` is kept as a compatibility wrapper for older instructions.
New work should use `patch_smtvv_freeplay.py`.

## Uninstall

Run `uninstall.bat` (Windows) or `./uninstall.sh` (Linux), or run `install.bat`
and choose uninstall. This restores the original executable and removes the
NG+ miracle data pak.

You can also restore the executable through Steam:

```text
Steam -> SMT5V -> Properties -> Installed Files -> Verify integrity
```

Note that Verify Integrity does not remove
`pakchunk99_NGPlusMiracles_P.pak` (Steam leaves unknown files alone) — use the
uninstall scripts, or delete that file from `Project/Content/Paks` yourself.

## Building from source

Nothing needs to be compiled to *use* this bundle — the executable patcher
(`patch_smtvv_freeplay.py`) is plain Python, a portable runtime is bundled in
`python/`, and prebuilt [repak](https://github.com/trumank/repak) binaries are
bundled in `repak/` (win64 + linux64, v0.2.3, dual MIT/Apache-2.0 — see
`repak/LICENSE-MIT` and `repak/LICENSE-APACHE`).

## How It Works

### Reusable Essences

Essences are regular inventory items with IDs 311-615. When the player applies
an essence, the game calls `ItemErase` to remove it from inventory. The patch
redirects that trampoline through a code cave that checks the item ID in `ECX`
and returns early for essences. Other items still erase normally.

### Leyline Auto-Heal

The leyline access trampoline is redirected through a code cave that calls the
game's own `PartyAllCure` implementation before continuing to normal leyline
logic.

### Miman Reveal

The same leyline hook can also loop through Miman save-buffer indexes and call
`SetMimanPositionFlag(index, true)`.

### NG+ Miracles From Start

This combines executable hooks for miracle visibility and purchasability with
a data-pak edit for `GodParameterDataTable`. The installer extracts the table
from your own `pakchunk0-WindowsNoEditor.pak` with the bundled `repak` tool,
applies the edits, and packs the result as
`Project/Content/Paks/pakchunk99_NGPlusMiracles_P.pak`. No game data is
redistributed with the mod — everything is derived from your installed copy
at install time.

## Compatibility Notes

- The executable patches are AOB guarded. If a game update changes the
  expected bytes, the patcher refuses that patch instead of writing blindly.
- Safe to use with existing saves. The installer modifies the executable and
  optional pak files, not save data.

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE).
You are free to use, modify, and redistribute it.

The bundled portable Python runtime in `python/` is distributed under the Python
Software Foundation License (see `python/LICENSE.txt`). The bundled `repak`
tool in `repak/` is distributed under its dual MIT/Apache-2.0 license (see
`repak/LICENSE-MIT` and `repak/LICENSE-APACHE`).
