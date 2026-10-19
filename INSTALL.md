# SMTVV Freeplay — Installation

A quality-of-life patch bundle for *Shin Megami Tensei V: Vengeance*: Reusable
Essences, Leyline Auto-Heal, Miman Reveal, NG+ Miracles From Start, Free Compendium,
Item Hacks (Battle Refill or Stockpile), Superjump, Free Growth Items, Full Magatsuhi,
Skip Intro, Masakado Unlock, Newborn Clears Compendium, and (optional)
Autosave After Battle.

**Requirements:** the **Steam** version of the game, on Windows or Steam Deck /
Linux (via Proton). Close the game before installing. Game Pass / Microsoft Store
editions use a different executable and are not supported.

---

## Windows

1. Download and **extract** the zip (don't run it from inside the archive).
2. Close the game.
3. Double-click **`install.bat`**.
4. Answer one question per mod: **Y** to install it, Enter to skip it. For
   Autosave After Battle, type the save slot (1-20) it should use.
   Run `install.bat` again later to add or remove mods; it shows which ones are
   installed and offers to uninstall all of them.
5. If it can't find the game automatically, paste your SMT5V folder path when
   asked (Steam → right-click SMT5V:V → Manage → Browse local files → copy the
   path from the address bar).
6. Launch the game from Steam.

---

## Steam Deck / Linux

The Deck runs the same Steam build through Proton, so the patches are identical.
Only the installer differs.

1. Download and **extract** the zip.
2. On Steam Deck, switch to **Desktop Mode**.
3. Open the extracted `SMTVV Freeplay` folder in a terminal (**Konsole**), or
   `cd` into it.
4. Run:

   ```bash
   chmod +x install.sh
   ./install.sh
   ```

   With no switches, this installs all twelve features, with Battle Refill as
   the Item Hack; add `--stockpile` to get Stockpile instead. To install only
   some of them, add a skip-switch for each feature you do **not** want:

   ```text
   --no-essences
   --no-heal
   --no-mimans
   --no-miracles
   --no-compendium
   --no-refill
   --no-jump
   --no-shop
   --no-magatsuhi
   --no-intro
   --no-masakado
   --no-newborn
   ```

   For example, to install **only Reusable Essences and Miman Reveal** (skipping
   Leyline Auto-Heal and NG+ Miracles):

   ```bash
   ./install.sh --no-heal --no-miracles
   ```

   You leave out the switch for anything you want to keep, and add the switch
   for anything you want to skip.

   Autosave After Battle is off unless you ask for it: add
   `--autosave-slot N` with a save slot from 1 to 20. That slot is overwritten
   after every battle.

   On Windows, `install.bat` asks for the slot.

   If the script can't find the game automatically, it will ask you to paste your
   SMT5V folder path.

5. Launch the game from Steam (Game Mode or Desktop).

---

## Uninstall

- **Windows:** run `install.bat` and answer **Y** to uninstall all, or run
  `uninstall.bat`.
- **Steam Deck / Linux:** run `./uninstall.sh`.

The uninstall scripts restore the original executable and remove the mod's
NG+ miracle data pak (`pakchunk99_NGPlusMiracles_P.pak`).

Steam → SMT5V:V → Properties → Installed Files → **Verify integrity of game
files** also restores the original executable, but leaves the miracle data pak
behind — if you uninstall that way, also delete
`Project/Content/Paks/pakchunk99_NGPlusMiracles_P.pak`, or just run the
uninstall script instead.

The installer backs up your original executable as
`SMT5V-Win64-Shipping.exe.original` and does not touch save data, so it is fully
reversible. Re-running the installer at any time is safe: it always rebuilds
from the backed-up original and cleans up anything left by a previous install.

If you previously installed an older build with Superjump, remove the old
`WINEDLLOVERRIDES="xinput1_3=n,b" %command%` launch option. The current
installers also remove the known legacy Superjump DLL when they find it.
