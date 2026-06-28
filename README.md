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

5. **Superjump** - hold B (controller) or SPACE (keyboard) while airborne to
   ascend and steer through the air (including 180s). Release to fall; press
   F8 in-game to toggle it off/on. Ships as a runtime DLL (see How It Works).

## Requirements

- Shin Megami Tensei V: Vengeance — the **Steam** version, on Windows or
  Steam Deck / Linux (via Proton). Game Pass / Microsoft Store editions use a
  different executable and are not supported.
- No separate Python install is required when using the packaged release.
  A portable Python runtime is included (Windows); on Linux it uses `python3`.
- `repak` is required only when rebuilding the NG+ miracle data pak from
  extracted game data.

See **[INSTALL.md](INSTALL.md)** for the full step-by-step. Quick version below.

## Install (Windows)

1. Place this folder inside or near your SMT5V install directory. The
   installer also searches common Steam library locations automatically,
   and if it still can't find the game it asks you to paste your SMT5V
   folder path (in Steam: right-click SMT5V > Manage > Browse local files,
   then copy the path from the address bar).

2. Double-click `install.bat`.

3. Choose all patches, or pick individual ones (Reusable Essences,
   Leyline Auto-Heal, Miman Reveal, NG+ Miracles, Superjump).

The installer backs up the original executable as:

```text
Project/Binaries/Win64/SMT5V-Win64-Shipping.exe.original
```

It writes the patched executable as:

```text
Project/Binaries/Win64/SMT5V-Win64-Shipping.exe.patched
```

Then it installs the patched executable over the live executable. If Superjump is
selected, it also copies `xinput1_3.dll` into `Project/Binaries/Win64/`.

## Steam Deck / Linux

Steam Deck runs the same Steam Windows build through Proton, so the patches are
identical — only the installer differs (Linux can't run the `.bat`). In **Desktop
Mode**, open a terminal (Konsole) in this folder and run:

```bash
chmod +x install.sh
./install.sh
```

With no switches it installs everything. To install only some of the features,
add a skip-switch for each one you don't want. The switches are --no-essences,
--no-heal, --no-mimans, --no-miracles, and --no-superjump — you leave out the
switch for anything you want to keep. For example, to install only Reusable
Essences and Miman Reveal (skipping the other three):

```bash
./install.sh --no-heal --no-miracles --no-superjump
```

Uninstall with `./uninstall.sh`. (`python3`, used by the patcher, ships with
Desktop Mode.)

**Superjump** additionally needs a Proton DLL override so the proxy DLL loads —
add this to the game's Steam **Launch Options** (Properties → General):

```text
WINEDLLOVERRIDES="xinput1_3=n,b" %command%
```

The other four patches work without it; it's only needed for Superjump.

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
and choose uninstall.

You can also restore through Steam:

```text
Steam -> SMT5V -> Properties -> Installed Files -> Verify integrity
```

## Building from source

Nothing needs to be compiled to *use* this bundle — the executable patcher
(`patch_smtvv_freeplay.py`) is plain Python, and a portable runtime is bundled
in `python/`.

The only native component is the **Superjump** module. To rebuild its DLL you
need **Visual Studio Build Tools** with the "Desktop development with C++"
workload:

```bat
cd superjump
build.bat
```

This compiles `superjump/src/` into `superjump/xinput1_3.dll`, which the installer
then copies into the game when Superjump is selected.

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
an optional data-pak edit for `GodParameterDataTable`.

### Superjump

Ships as `xinput1_3.dll` (in this bundle's `superjump/` folder), a proxy the game
already loads. The installer copies it into `Project/Binaries/Win64/`. It
forwards every real XInput call untouched, polls the controller B button and
keyboard SPACE, and while you hold either in the air it reverses the player
movement component's jump-gravity to ascend and drives the horizontal velocity
axis for steering. It changes no executable or save data; remove it by deleting
the DLL (uninstall does this automatically).

## Compatibility Notes

- The executable patches are AOB guarded. If a game update changes the
  expected bytes, the patcher refuses that patch instead of writing blindly.
- Safe to use with existing saves. The installer modifies the executable and
  optional pak files, not save data.
- Superjump is a runtime DLL (`xinput1_3.dll`), not an executable patch, so it is
  unaffected by game updates that change executable bytes, and it forwards all
  real controller input untouched.

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE).
You are free to use, modify, and redistribute it.

The bundled portable Python runtime in `python/` is distributed under the Python
Software Foundation License (see `python/LICENSE.txt`). The Superjump module's C++
source is in `superjump/src/` and builds with `superjump/build.bat` (Visual Studio
Build Tools); a prebuilt `superjump/xinput1_3.dll` is included for convenience.
