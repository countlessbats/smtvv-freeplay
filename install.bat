@echo off
setlocal EnableDelayedExpansion
:: Optional argument: the SMT5V folder (skips the automatic search).
set "ARGDIR=%~1"

echo.
echo  ============================================================
echo   SMT5V: Vengeance - Freeplay Mod Installer
echo  ============================================================

:: --- Locate Python ---
set "PYTHON=%~dp0python\python.exe"
if exist "%PYTHON%" goto :have_python
where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
    goto :have_python
)
echo  ERROR: Python not found.
pause
exit /b 1

:have_python

:: --- Locate game (auto-detect, then ask the user to paste the path) ---
set "EXE=SMT5V-Win64-Shipping.exe"
call :locate
if not defined BINDIR (
    echo.
    echo  Cancelled -- no game folder provided.
    pause
    exit /b 1
)
:: Clean game root (for the patcher's --game-dir), derived from BINDIR
for %%I in ("!BINDIR!\..\..\..") do set "GAMEDIR=%%~fI"

:: --- What is installed now ---
set "BOOL_KEYS=essences heal mimans miracles compendium jump shop magatsuhi intro masakado newborn"
set "STATE=!BINDIR!\Freeplay.features"
for %%K in (%BOOL_KEYS%) do set "INST_%%K="
set "INST_itemhacks="
set "INST_autosave="
if exist "!STATE!" (
    for /f "usebackq tokens=1,2 delims==" %%A in ("!STATE!") do (
        for %%K in (%BOOL_KEYS%) do if /i "%%A"=="%%K" if "%%B"=="1" set "INST_%%K=1"
        if /i "%%A"=="itemhacks" if /i "%%B"=="refill" set "INST_itemhacks=refill"
        if /i "%%A"=="itemhacks" if /i "%%B"=="stockpile" set "INST_itemhacks=stockpile"
        if /i "%%A"=="autosave" for /l %%N in (1,1,20) do if "%%B"=="%%N" set "INST_autosave=%%N"
    )
)
set /a NINST=0
for %%K in (%BOOL_KEYS%) do if defined INST_%%K set /a NINST+=1
if defined INST_itemhacks set /a NINST+=1
if defined INST_autosave set /a NINST+=1
set /a NALL=13

:: An install that predates the feature record: the executable differs from
:: the backup, or a Freeplay data pak is present.
set "LEGACY="
if not exist "!STATE!" (
    if exist "!BINDIR!\%EXE%.original" (
        call :sha256 "!BINDIR!\%EXE%" H1
        call :sha256 "!BINDIR!\%EXE%.original" H2
        if not "!H1!"=="!H2!" set "LEGACY=1"
    )
    for %%P in (93_FreeplayStockpile 94_FreeplayNewborn 95_FreeplayMap 96_FreeplayQuest 97_FreeplayBoot 98_FreeplayShop 99_NGPlusMiracles) do (
        if exist "!GAMEDIR!\Project\Content\Paks\pakchunk%%P_P.pak" set "LEGACY=1"
    )
)

echo.
if !NINST! geq !NALL! goto :all_installed
if !NINST! gtr 0 goto :some_installed
if defined LEGACY goto :legacy_installed
echo   No mods from this pack are installed. Choose the ones you want:
goto :choose

:all_installed
echo   All mods in this pack are currently installed.
set "A="
set /p "A=  Uninstall all? Choose N to list each for individual uninstall. [y/n]: "
if /i "!A!"=="y" goto :uninstall
if /i "!A!"=="n" goto :choose
goto :all_installed

:some_installed
echo   Some mods from this pack are installed ^(marked [installed] below^).
set "A="
set /p "A=  Uninstall all of them first? [y/N]: "
if /i "!A!"=="y" goto :uninstall
if not defined A goto :choose
if /i "!A!"=="n" goto :choose
goto :some_installed

:legacy_installed
echo   An earlier version of this pack is installed. It did not record which
echo   mods it installed.
set "A="
set /p "A=  Uninstall it? Choose N to choose mods now. [y/N]: "
if /i "!A!"=="y" goto :uninstall
if not defined A goto :choose
if /i "!A!"=="n" goto :choose
goto :legacy_installed

:: --- One question per mod ---
:choose
echo.
call :ask essences "Reusable Essences (essences not consumed)"
call :ask heal "Leyline Auto-Heal (full HP/MP on leyline use)"
call :ask mimans "Miman Reveal (all miman positions shown on map)"
call :ask miracles "NG+ Miracles (unlock NG+ miracles early)"
call :ask compendium "Free Compendium (compendium summons cost nothing)"
call :ask_items
call :ask jump "Superjump (hold jump to rise, faster air control)"
call :ask shop "Free Growth Items (Gospels, Grimoires, Sutras, Balms, Incenses free in shop)"
call :ask magatsuhi "Full Magatsuhi (gauge full at the start of every battle)"
call :ask intro "Skip Intro (no logos or opening movie; boot to title menu)"
call :ask masakado "Masakado Unlock (powered-up Masakado fight without the Kiou Sword)"
call :ask newborn "Newborn Clears Compendium (NG+ Newborn starts with an empty compendium)"
call :ask_autosave

set "FLAGS="
set /a NSEL=0
for %%K in (%BOOL_KEYS%) do (
    if defined SEL_%%K (
        set /a NSEL+=1
    ) else (
        set "FLAGS=!FLAGS! --no-%%K"
    )
)
if /i "!SEL_itemhacks!"=="refill" set /a NSEL+=1
if /i "!SEL_itemhacks!"=="stockpile" (
    set /a NSEL+=1
    set "FLAGS=!FLAGS! --stockpile"
)
if /i "!SEL_itemhacks!"=="none" set "FLAGS=!FLAGS! --no-refill"
if defined SEL_autosave (
    set /a NSEL+=1
    set "FLAGS=!FLAGS! --autosave-slot !SEL_autosave!"
)
if !NSEL! equ 0 (
    echo.
    echo   No mods chosen.
    if !NINST! gtr 0 goto :uninstall
    if defined LEGACY goto :uninstall
    pause
    exit /b 0
)
goto :run_patcher

:: call :sha256 "<file>" <var> -- sets <var> to the file's SHA-256
:sha256
set "%~2="
for /f "skip=1 delims=" %%H in ('%SystemRoot%\System32\certutil.exe -hashfile "%~1" SHA256') do (
    if not defined %~2 set "%~2=%%H"
)
exit /b 0

:: call :ask <key> "<description>" -- sets SEL_<key>=1 to install or keep it
:ask
set "K=%~1"
set "D=%~2"
set "SEL_%K%="
set "Q=   !D! - install? [y/N]: "
set "DEF=n"
if defined INST_%K% set "Q=   !D! [installed] - keep? [Y/n]: "
if defined INST_%K% set "DEF=y"
:ask_again
set "A="
set /p "A=!Q!"
if not defined A set "A=!DEF!"
if /i "!A!"=="y" (
    set "SEL_%K%=1"
    exit /b 0
)
if /i "!A!"=="n" exit /b 0
goto :ask_again

:ask_items
echo    Item Hacks: [R] Battle Refill (any battle item you've found once tops off at the start of every battle)
echo                [S] Stockpile (stack battle items to 99; normal limit per battle)
echo                [N] Neither
set "SEL_itemhacks="
set "Q=   Item Hacks? [r/s/N]: "
set "DEF=n"
if /i "!INST_itemhacks!"=="refill" set "Q=   Item Hacks [installed: Battle Refill] - keep? [R/s/n]: "
if /i "!INST_itemhacks!"=="refill" set "DEF=r"
if /i "!INST_itemhacks!"=="stockpile" set "Q=   Item Hacks [installed: Stockpile] - keep? [r/S/n]: "
if /i "!INST_itemhacks!"=="stockpile" set "DEF=s"
:ask_items_again
set "A="
set /p "A=!Q!"
if not defined A set "A=!DEF!"
if /i "!A!"=="r" set "SEL_itemhacks=refill"
if /i "!A!"=="s" set "SEL_itemhacks=stockpile"
if /i "!A!"=="n" set "SEL_itemhacks=none"
if not defined SEL_itemhacks goto :ask_items_again
exit /b 0

:ask_autosave
echo    Autosave After Battle: saves to one slot after every battle,
echo                           overwriting that slot each time.
set "SEL_autosave="
set "Q=   Autosave After Battle - install? Enter a save slot (1-20), or blank to skip: "
if defined INST_autosave set "Q=   Autosave After Battle [installed: slot !INST_autosave!] - keep? Enter for slot !INST_autosave!, another slot (1-20), or N to remove: "
:ask_autosave_again
set "A="
set /p "A=!Q!"
if not defined A (
    if defined INST_autosave set "SEL_autosave=!INST_autosave!"
    exit /b 0
)
if /i "!A!"=="n" exit /b 0
for /l %%N in (1,1,20) do if "!A!"=="%%N" set "SEL_autosave=%%N"
if defined SEL_autosave exit /b 0
echo    Please enter a slot number from 1 to 20.
goto :ask_autosave_again

:run_patcher
echo.
"%PYTHON%" "%~dp0patch_smtvv_freeplay.py" --game-dir "%GAMEDIR%" %FLAGS%
if errorlevel 1 (
    echo.
    echo  Patcher failed. See errors above.
    pause
    exit /b 1
)

:: --- Backup & install executable patches (only if the patcher produced one) ---
if exist "%BINDIR%\%EXE%.patched" (
    if not exist "%BINDIR%\%EXE%.original" (
        echo  Backing up original executable...
        copy /Y "%BINDIR%\%EXE%" "%BINDIR%\%EXE%.original" >nul
    )
    echo  Installing patched executable...
    copy /Y "%BINDIR%\%EXE%.patched" "%BINDIR%\%EXE%" >nul
)
if exist "%BINDIR%\Freeplay.features.new" move /Y "%BINDIR%\Freeplay.features.new" "%BINDIR%\Freeplay.features" >nul

call :remove_legacy_superjump

echo.
echo  ============================================================
echo   Done - mods installed.
echo.
echo   To change or remove mods, run this installer again.
echo  ============================================================
echo.
pause
exit /b 0

:uninstall
set "EXE=SMT5V-Win64-Shipping.exe"
if not defined BINDIR call :locate
if not defined BINDIR (
    echo.
    echo  Cancelled -- no game folder provided.
    pause
    exit /b 1
)
if exist "!BINDIR!\%EXE%.original" (
    echo  Restoring original executable...
    copy /Y "!BINDIR!\%EXE%.original" "!BINDIR!\%EXE%" >nul
    echo  Done - original executable restored.
) else (
    echo  No backup found. Use Steam ^> Verify Integrity instead.
)
for %%I in ("!BINDIR!\..\..\..") do set "GAMEDIR=%%~fI"
if exist "!GAMEDIR!\Project\Content\Paks\pakchunk99_NGPlusMiracles_P.pak" (
    echo  Removing NG+ miracle data pak...
    del /Q "!GAMEDIR!\Project\Content\Paks\pakchunk99_NGPlusMiracles_P.pak" >nul 2>nul
)
if exist "!GAMEDIR!\Project\Content\Paks\pakchunk98_FreeplayShop_P.pak" (
    echo  Removing shop data pak...
    del /Q "!GAMEDIR!\Project\Content\Paks\pakchunk98_FreeplayShop_P.pak" >nul 2>nul
)
if exist "!GAMEDIR!\Project\Content\Paks\pakchunk97_FreeplayBoot_P.pak" (
    echo  Removing intro data pak...
    del /Q "!GAMEDIR!\Project\Content\Paks\pakchunk97_FreeplayBoot_P.pak" >nul 2>nul
)
if exist "!GAMEDIR!\Project\Content\Paks\pakchunk96_FreeplayQuest_P.pak" (
    echo  Removing quest data pak...
    del /Q "!GAMEDIR!\Project\Content\Paks\pakchunk96_FreeplayQuest_P.pak" >nul 2>nul
)
if exist "!GAMEDIR!\Project\Content\Paks\pakchunk95_FreeplayMap_P.pak" (
    echo  Removing map data pak...
    del /Q "!GAMEDIR!\Project\Content\Paks\pakchunk95_FreeplayMap_P.pak" >nul 2>nul
)
if exist "!GAMEDIR!\Project\Content\Paks\pakchunk94_FreeplayNewborn_P.pak" (
    echo  Removing carry-over text pak...
    del /Q "!GAMEDIR!\Project\Content\Paks\pakchunk94_FreeplayNewborn_P.pak" >nul 2>nul
)
if exist "!GAMEDIR!\Project\Content\Paks\pakchunk93_FreeplayStockpile_P.pak" (
    echo  Removing Stockpile data pak...
    del /Q "!GAMEDIR!\Project\Content\Paks\pakchunk93_FreeplayStockpile_P.pak" >nul 2>nul
)
if exist "!BINDIR!\xinput1_3.dll" (
    call :remove_legacy_superjump
)
del /Q "!BINDIR!\Freeplay.features" "!BINDIR!\Freeplay.features.new" >nul 2>nul
echo.
pause
exit /b 0

:remove_legacy_superjump
if not exist "!BINDIR!\xinput1_3.dll" exit /b 0
set "LEGACY_SUPERJUMP_SHA256=4D51DC377C15006EE4903DE265CCDA3514900A059D2019498B66EE9DCC56B819"
set "MATCHED_SUPERJUMP="
for /f "usebackq delims=" %%H in (`certutil -hashfile "!BINDIR!\xinput1_3.dll" SHA256 ^| findstr /i "!LEGACY_SUPERJUMP_SHA256!"`) do set "MATCHED_SUPERJUMP=1"
if defined MATCHED_SUPERJUMP (
    echo  Removing legacy Superjump module ^(xinput1_3.dll^)...
    del /Q "!BINDIR!\xinput1_3.dll" >nul 2>nul
) else (
    echo  NOTE: Found xinput1_3.dll, but it does not match the old Superjump module.
    echo        Leaving it in place.
)
set "MATCHED_SUPERJUMP="
exit /b 0

:: ==========================================================================
:: :locate -- sets BINDIR to the game's ...\Project\Binaries\Win64 folder.
:: Tries common Steam locations, then asks the user to paste the path.
:: Leaves BINDIR undefined only if the user cancels (blank input).
:: ==========================================================================
:locate
set "BINDIR="
if defined ARGDIR (
    set "USERPATH=!ARGDIR!"
    set "ARGDIR="
    goto :locate_check
)
for %%D in (C D E F G H) do (
    for %%P in (
        "%%D:\SteamLibrary\steamapps\common\SMT5V"
        "%%D:\Program Files (x86)\Steam\steamapps\common\SMT5V"
        "%%D:\Program Files\Steam\steamapps\common\SMT5V"
    ) do (
        if exist "%%~P\Project\Binaries\Win64\%EXE%" (
            set "BINDIR=%%~P\Project\Binaries\Win64"
            exit /b 0
        )
    )
)
for %%R in ("%~dp0.." "%~dp0..\.." "%~dp0..\..\..") do (
    if exist "%%~R\Project\Binaries\Win64\%EXE%" (
        set "BINDIR=%%~R\Project\Binaries\Win64"
        exit /b 0
    )
)

echo.
echo  Could not find SMT5V automatically.
echo  In Steam: right-click SMT5V ^> Manage ^> Browse local files,
echo  then copy that folder's path from the address bar and paste it here.
echo.

:locate_ask
set "USERPATH="
set /p "USERPATH=  SMT5V folder (or blank to cancel): "
if not defined USERPATH exit /b 1
:locate_check
set USERPATH=%USERPATH:"=%
if /i "!USERPATH:~-4!"==".exe" for %%I in ("!USERPATH!") do set "USERPATH=%%~dpI"
if "!USERPATH:~-1!"=="\" set "USERPATH=!USERPATH:~0,-1!"
if exist "!USERPATH!\%EXE%" (
    set "BINDIR=!USERPATH!"
    exit /b 0
)
if exist "!USERPATH!\Project\Binaries\Win64\%EXE%" (
    set "BINDIR=!USERPATH!\Project\Binaries\Win64"
    exit /b 0
)
echo.
echo  That folder doesn't contain %EXE%. Paste the SMT5V folder
echo  (or its Project\Binaries\Win64 folder), or press Enter to cancel.
echo.
goto :locate_ask
