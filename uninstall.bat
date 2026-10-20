@echo off
setlocal

echo.
echo  ============================================================
echo   SMT5V: Vengeance - Freeplay Mod
echo   UNINSTALL
echo  ============================================================
echo.

:: --- Locate game executable -------------------------------------------
set "BINDIR=%~dp0..\..\Project\Binaries\Win64"
set "EXE=SMT5V-Win64-Shipping.exe"

if not exist "%BINDIR%\%EXE%.original" (
    :: Try searching
    for %%D in (C D E F G H) do (
        for %%P in (
            "%%D:\SteamLibrary\steamapps\common\SMT5V"
            "%%D:\Program Files (x86)\Steam\steamapps\common\SMT5V"
            "%%D:\Program Files\Steam\steamapps\common\SMT5V"
        ) do (
            if exist "%%~P\Project\Binaries\Win64\%EXE%.original" (
                set "BINDIR=%%~P\Project\Binaries\Win64"
                goto :found
            )
        )
    )

    echo  ERROR: Original backup not found.
    echo.
    echo  To restore the game executable, use:
    echo    Steam ^> Right-click SMT5V ^> Properties ^> Local Files
    echo    ^> Verify Integrity of Game Files
    echo.
    pause
    exit /b 1
)

:found
echo  Restoring original executable...
copy /Y "%BINDIR%\%EXE%.original" "%BINDIR%\%EXE%" >nul
set "HAPTICS="
if exist "%BINDIR%\Freeplay.features" (
    for /f "usebackq tokens=1,2 delims==" %%A in ("%BINDIR%\Freeplay.features") do (
        if /i "%%A"=="haptics" if "%%B"=="1" set "HAPTICS=1"
    )
)
if defined HAPTICS call :haptics_remove
del /Q "%BINDIR%\Freeplay.features" "%BINDIR%\Freeplay.features.new" >nul 2>nul

for %%I in ("%BINDIR%\..\..\..") do set "GAMEDIR=%%~fI"
if exist "%GAMEDIR%\Project\Content\Paks\pakchunk99_NGPlusMiracles_P.pak" (
    echo  Removing NG+ miracle data pak...
    del /Q "%GAMEDIR%\Project\Content\Paks\pakchunk99_NGPlusMiracles_P.pak" >nul 2>nul
)
if exist "%GAMEDIR%\Project\Content\Paks\pakchunk98_FreeplayShop_P.pak" (
    echo  Removing shop data pak...
    del /Q "%GAMEDIR%\Project\Content\Paks\pakchunk98_FreeplayShop_P.pak" >nul 2>nul
)
if exist "%GAMEDIR%\Project\Content\Paks\pakchunk97_FreeplayBoot_P.pak" (
    echo  Removing intro data pak...
    del /Q "%GAMEDIR%\Project\Content\Paks\pakchunk97_FreeplayBoot_P.pak" >nul 2>nul
)
if exist "%GAMEDIR%\Project\Content\Paks\pakchunk96_FreeplayQuest_P.pak" (
    echo  Removing quest data pak...
    del /Q "%GAMEDIR%\Project\Content\Paks\pakchunk96_FreeplayQuest_P.pak" >nul 2>nul
)
if exist "%GAMEDIR%\Project\Content\Paks\pakchunk95_FreeplayMap_P.pak" (
    echo  Removing map data pak...
    del /Q "%GAMEDIR%\Project\Content\Paks\pakchunk95_FreeplayMap_P.pak" >nul 2>nul
)
if exist "%GAMEDIR%\Project\Content\Paks\pakchunk94_FreeplayNewborn_P.pak" (
    echo  Removing carry-over text pak...
    del /Q "%GAMEDIR%\Project\Content\Paks\pakchunk94_FreeplayNewborn_P.pak" >nul 2>nul
)
if exist "%GAMEDIR%\Project\Content\Paks\pakchunk93_FreeplayStockpile_P.pak" (
    echo  Removing Stockpile data pak...
    del /Q "%GAMEDIR%\Project\Content\Paks\pakchunk93_FreeplayStockpile_P.pak" >nul 2>nul
)

if exist "%BINDIR%\xinput1_3.dll" (
    call :remove_legacy_superjump
)

echo.
echo  ============================================================
echo   DONE!  Original executable restored.
echo   Freeplay patches are now removed.
echo  ============================================================
echo.
pause
exit /b 0

:: DualSense Haptics: its xinput1_3.dll (if still the haptics loader) and folder
:haptics_remove
call :haptics_owned
if defined HOWNED del /Q "%BINDIR%\xinput1_3.dll" >nul 2>nul
if not exist "%BINDIR%\DualSenseHaptics\" exit /b 0
echo  Removing DualSense Haptics...
rd /S /Q "%BINDIR%\DualSenseHaptics" >nul 2>nul
if exist "%BINDIR%\DualSenseHaptics\" (
    echo  NOTE: Some haptics files are still in use. Close the haptics panel, or
    echo        restart Windows, then delete %BINDIR%\DualSenseHaptics.
)
exit /b 0

:: Sets HOWNED when xinput1_3.dll is the haptics loader recorded in its folder.
:haptics_owned
set "HOWNED="
if not exist "%BINDIR%\xinput1_3.dll" exit /b 0
if not exist "%BINDIR%\DualSenseHaptics\loader.sha256" exit /b 0
set "HCUR="
for /f "skip=1 delims=" %%H in ('%SystemRoot%\System32\certutil.exe -hashfile "%BINDIR%\xinput1_3.dll" SHA256') do if not defined HCUR set "HCUR=%%H"
set "HCUR=%HCUR: =%"
set "HREC="
set /p "HREC=" <"%BINDIR%\DualSenseHaptics\loader.sha256"
if /i "%HCUR%"=="%HREC%" set "HOWNED=1"
exit /b 0

:remove_legacy_superjump
call :haptics_owned
if defined HOWNED exit /b 0
set "LEGACY_SUPERJUMP_SHA256=4D51DC377C15006EE4903DE265CCDA3514900A059D2019498B66EE9DCC56B819"
set "MATCHED_SUPERJUMP="
for /f "usebackq delims=" %%H in (`certutil -hashfile "%BINDIR%\xinput1_3.dll" SHA256 ^| findstr /i "%LEGACY_SUPERJUMP_SHA256%"`) do set "MATCHED_SUPERJUMP=1"
if defined MATCHED_SUPERJUMP (
    echo  Removing legacy Superjump module ^(xinput1_3.dll^)...
    del /Q "%BINDIR%\xinput1_3.dll"
) else (
    echo  NOTE: Found xinput1_3.dll, but it does not match the old Superjump module.
    echo        Leaving it in place.
)
set "MATCHED_SUPERJUMP="
exit /b 0
