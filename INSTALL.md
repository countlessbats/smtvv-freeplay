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

   With no switches, this installs all five features. To install only some of
   them, add a skip-switch for each feature you do **not** want:

   ```text
   --no-essences
   --no-heal
   --no-mimans
   --no-miracles
   --no-superjump
   ```

   For example, to install **only Reusable Essences and Miman Reveal** (skipping
   Leyline Auto-Heal, NG+ Miracles, and Superjump/Flight):

   ```bash
   ./install.sh --no-heal --no-miracles --no-superjump
   ```

   You leave out the switch for anything you want to keep, and add the switch
   for anything you want to skip.

   If the script can't find the game automatically, it will ask you to paste your
   SMT5V folder path.

5. **Extra step — required only if you installed Superjump/Flight.** Add a Proton
   DLL override so the mod's DLL loads. In Steam, right-click SMT5V:V →
   **Properties → General → Launch Options**, and set:

   ```
   WINEDLLOVERRIDES="xinput1_3=n,b" %command%
   ```

   If you used `--no-superjump`, do **not** add that launch option. The other
   four patches work without it.

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
