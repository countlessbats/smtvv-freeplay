@echo off
setlocal EnableDelayedExpansion

echo.
echo  ============================================================
echo   SMT5V: Vengeance - Freeplay Mod Installer
echo  ============================================================
echo.
echo   Select which patches to install:
echo.
echo     [1] All patches
echo     [2] Choose individually
echo     [3] Uninstall (restore original)
echo.
set /p CHOICE="  Your choice (1/2/3): "

if "%CHOICE%"=="3" goto :uninstall
if "%CHOICE%"=="2" goto :individual

:: Default: all patches
set "FLAGS="
set "DO_SUPERJUMP=1"
goto :run_patcher

:individual
echo.
echo   For each patch, enter Y or N:
echo.
set /p P1="   Reusable Essences (essences not consumed)? [Y/n]: "
set /p P2="   Leyline Auto-Heal (full HP/MP on leyline use)? [Y/n]: "
set /p P3="   Miman Reveal (all miman positions shown on map)? [Y/n]: "
set /p P4="   NG+ Miracles (unlock NG+ miracles early)? [Y/n]: "
set /p P5="   Superjump (hold B / SPACE to fly)? [Y/n]: "

set "FLAGS="
set "DO_SUPERJUMP=1"
if /i "%P1%"=="n" set "FLAGS=!FLAGS! --no-essences"
if /i "%P2%"=="n" set "FLAGS=!FLAGS! --no-heal"
if /i "%P3%"=="n" set "FLAGS=!FLAGS! --no-mimans"
if /i "%P4%"=="n" set "FLAGS=!FLAGS! --no-miracles"
if /i "%P5%"=="n" set "DO_SUPERJUMP=0"
goto :run_patcher

:run_patcher

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

:: --- Superjump module (runtime DLL proxy, not an executable patch) ---
if "%DO_SUPERJUMP%"=="1" (
    if exist "%~dp0superjump\xinput1_3.dll" (
        echo  Installing Superjump module ^(xinput1_3.dll^)...
        copy /Y "%~dp0superjump\xinput1_3.dll" "%BINDIR%\xinput1_3.dll" >nul
    ) else (
        echo  NOTE: superjump\xinput1_3.dll not found - skipping Superjump.
    )
)

echo.
echo  ============================================================
echo   DONE!  Mod installed successfully.
echo.
echo   To uninstall: run this script again and choose option 3,
echo   or use Steam ^> Verify Integrity of Game Files.
echo  ============================================================
echo.
pause
exit /b 0

:uninstall
set "EXE=SMT5V-Win64-Shipping.exe"
call :locate
if not defined BINDIR (
    echo.
    echo  Cancelled -- no game folder provided.
    pause
    exit /b 1
)
if exist "!BINDIR!\%EXE%.original" (
    echo  Restoring original executable...
    copy /Y "!BINDIR!\%EXE%.original" "!BINDIR!\%EXE%" >nul
    echo  Done! Original executable restored.
) else (
    echo  No backup found. Use Steam ^> Verify Integrity instead.
)
if exist "!BINDIR!\xinput1_3.dll" (
    echo  Removing Superjump module...
    del /Q "!BINDIR!\xinput1_3.dll" >nul 2>nul
)
echo.
pause
exit /b 0

:: ==========================================================================
:: :locate -- sets BINDIR to the game's ...\Project\Binaries\Win64 folder.
:: Tries common Steam locations, then asks the user to paste the path.
:: Leaves BINDIR undefined only if the user cancels (blank input).
:: ==========================================================================
:locate
set "BINDIR="
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
