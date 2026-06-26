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

if exist "%BINDIR%\xinput1_3.dll" (
    echo  Removing Superjump module ^(xinput1_3.dll^)...
    del /Q "%BINDIR%\xinput1_3.dll"
)

echo.
echo  ============================================================
echo   DONE!  Original executable restored.
echo   Freeplay patches and Superjump module are now removed.
echo  ============================================================
echo.
pause
