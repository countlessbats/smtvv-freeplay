# SMTVV Freeplay — Installation

A quality-of-life patch bundle for *Shin Megami Tensei V: Vengeance*: Reusable
Essences, Leyline Auto-Heal, Miman Reveal, NG+ Miracles From Start, and Superjump
(hold B / SPACE to fly).

**Requirements:** the **Steam** version of the game, on Windows or Steam Deck /
Linux (via Proton). Close the game before installing. Game Pass / Microsoft Store
editions use a different executable and are not supported.

---

## Windows

1. Download and **extract** the zip (don't run it from inside the archive).
2. Close the game.
3. Double-click **`install.bat`**.
4. Choose **[1] All patches**, or **[2]** to choose individually.
5. If it can't find the game automatically, paste your SMT5V folder path when
   asked (Steam → right-click SMT5V:V → Manage → Browse local files → copy the
   path from the address bar).
6. Launch the game from Steam.

Superjump works as-is on Windows — no extra step.

---

## Steam Deck / Linux

The Deck runs the same Steam build through Proton, so the patches are identical —
only the installer differs.

1. Download and **extract** the zip.
2. On Steam Deck, switch to **Desktop Mode**.
3. Open the extracted folder in a terminal (**Konsole**), or `cd` into it.
4. Install:

   ```bash
   chmod +x install.sh
   ./install.sh
   ```

   With no switches, this installs all five features. To install only some of
   them, add a skip-switch for each one you don't want. The switches are
   --no-essences, --no-heal, --no-mimans, --no-miracles, and --no-superjump —
   you leave out the switch for anything you want to keep.

   For example, to install **only Reusable Essences and Miman Reveal** (skipping
   Leyline Auto-Heal, NG+ Miracles, and Superjump):

   ```bash
   ./install.sh --no-heal --no-miracles --no-superjump
   ```

   If the script can't find the game automatically, it will ask you to paste your
   SMT5V folder path.

5. **Extra step — required for Superjump only.** Proton needs a DLL override so
   the mod's proxy DLL loads. In Steam, right-click SMT5V:V → **Properties →
   General → Launch Options**, and set:

   ```
   WINEDLLOVERRIDES="xinput1_3=n,b" %command%
   ```

   The other four patches work **without** this; it is only needed for Superjump.

6. Launch the game from Steam (Game Mode or Desktop).

---

## Uninstall

- **Windows:** run `install.bat` → **[3] Uninstall**, or run `uninstall.bat`.
- **Steam Deck / Linux:** run `./uninstall.sh` (and remove the launch option).
- **Either:** Steam → SMT5V:V → Properties → Installed Files → **Verify integrity
  of game files** restores the original executable.

The installer backs up your original executable as
`SMT5V-Win64-Shipping.exe.original` and does not touch save data, so it is fully
reversible.
