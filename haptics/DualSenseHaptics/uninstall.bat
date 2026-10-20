@echo off
setlocal
:: Removes SMT V DualSense Haptics: the xinput1_3.dll next to the game, if it is still ours, and
:: this folder with its settings and logs.
set "HERE=%~dp0"
set "WIN64=%HERE%.."
tasklist /FI "IMAGENAME eq SMT5V-Win64-Shipping.exe" 2>nul | %SystemRoot%\System32\find.exe /I "SMT5V-Win64-Shipping.exe" >nul
if not errorlevel 1 (
  echo Quit the game first, then run this again.
  pause
  exit /b 1
)
taskkill /IM SMTVHaptics.exe >nul 2>&1
set "OURS="
for /f "usebackq delims=" %%H in (`%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command "if ((Get-FileHash -LiteralPath '%WIN64%\xinput1_3.dll' -Algorithm SHA256).Hash -eq (Get-Content -LiteralPath '%HERE%loader.sha256' -Raw).Trim()) { 'yes' }" 2^>nul`) do set "OURS=%%H"
if "%OURS%"=="yes" (
  del /f /q "%WIN64%\xinput1_3.dll"
) else (
  echo xinput1_3.dll is not this mod's file; leaving it in place.
)
echo DualSense Haptics removed.
cd /d "%WIN64%"
start "" /b cmd /c "timeout /t 1 /nobreak >nul & rmdir /s /q ""%HERE%"""
exit /b 0
