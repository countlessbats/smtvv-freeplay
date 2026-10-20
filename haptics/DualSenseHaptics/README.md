# SMT V: Vengeance DualSense Haptics

Authored DualSense haptic effects for Shin Megami Tensei V: Vengeance on PC, with a panel for tuning each one, and quick exit for the game window.

Effects are triggered by the sounds the game plays: the plugin watches every sound cue and plays the effect `cue-map.txt` assigns to it. Battle hits fire as each damage number lands, by element, along with criticals, blocks, repels, drains and misses. Skills, press turns, Magatsuhi, field actions and menus are covered too.

## Requirements

- A DualSense connected by USB cable. Bluetooth cannot carry the haptic channels.
- Windows 10 or 11.

## Installing

Extract the release zip into the game folder (the folder holding `SMT5V.exe`), so that `xinput1_3.dll` lands in `Project\Binaries\Win64` and the mod's files in `Project\Binaries\Win64\DualSenseHaptics`. Launch the game from Steam as usual. The game executable is not modified.

## Uninstalling

Quit the game and run `uninstall.bat` in `Project\Binaries\Win64\DualSenseHaptics`. It removes the mod's `xinput1_3.dll` and that folder.

## Quick exit

Closing the game window with Alt+F4, the title bar or the taskbar ends the game at once instead of waiting through its slow shutdown. Avoid closing the window while the game is saving. Set `QuickExit=0` under `[General]` in `SMTVHaptics.ini` in the mod's folder to restore the normal shutdown.

## Using the panel

Run `SMTVHaptics.exe` in the mod's folder. The panel starts the haptics bridge, which drives the controller's actuators through its USB audio endpoint.

- Double-click an effect, or select it and press **Preview**.
- **Strength** sets the effect's level from 0 to 150%.
- **Duration** stretches or shortens the effect from 50 to 200%.
- **Preview when I let go of a slider** plays the effect each time you finish adjusting it.
- **Master strength** scales every effect.
- **Mark this effect in the test log** writes the time and effect name to `test-markers.log`.

Changes are saved immediately to `SMTVHaptics.ini`. While the game runs, the panel's status area shows the plugin's state. The panel does not need to be open while you play.

**Replace the game's own vibration** silences the game's rumble while the haptics bridge is running, so only the authored effects are felt. It is off by default.

## Cue map

`cue-map.txt` in the mod's folder assigns effects to sound cues, one per line: `*/cue = effect [strength]`. Cue names already carry their sheet (`btl_hit_06_fire`, `skill_005_sk102_20`), so the sheet part is written as `*`. Several effects can be combined with `+`, `*` matches any run of characters, `none` as the effect ignores a cue, and the first matching line wins. The plugin rereads the file while the game runs.

The plugin writes every cue the game plays to `cues.log`, with the effect it triggered. Its own log is `game.log`.

## Building

Run `Build.ps1`. It builds with the Visual Studio 2022 Build Tools, runs the waveform and bridge transport tests, writes the release zip to `stage\` and installs into the game folder named in `local.gamedir` (or `-GameDir`). `Build.ps1 -NoInstall` stages without installing; `-InstallOnly` installs the last staged build. `re/make_cue_map.py` regenerates `data/cue-map.txt`.
