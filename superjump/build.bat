@echo off
setlocal
:: Build the SMTVV Superjump module from source into xinput1_3.dll next to this
:: script. Requires Visual Studio Build Tools ("Desktop development with C++").

set "ROOT=%~dp0"
set "SRC=%ROOT%src"

set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

if not exist "%VCVARS%" (
  echo ERROR: Visual Studio Build Tools vcvars64.bat not found.
  echo Install "Desktop development with C++" and retry.
  exit /b 1
)

call "%VCVARS%" >nul
if errorlevel 1 exit /b 1

cl /nologo /EHsc /std:c++17 /O2 /LD ^
  "%SRC%\xinput_proxy.cpp" ^
  "%SRC%\flight_backend.cpp" ^
  /Fe:"%ROOT%xinput1_3.dll" ^
  /Fo:"%ROOT%" ^
  /link /DEF:"%SRC%\xinput_proxy.def" user32.lib

if errorlevel 1 exit /b 1
echo Built "%ROOT%xinput1_3.dll"
