@echo off
setlocal
cd /d "%~dp0"
if not exist bin mkdir bin
where cl >nul 2>nul && goto build
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto missing
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSROOT=%%i"
if not defined VSROOT goto missing
call "%VSROOT%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
:build
cl /nologo /O2 /EHsc /std:c++17 /MT /W3 native\capture.cpp /Fo:bin\capture.obj /Fe:bin\capture.exe /link Ole32.lib Mmdevapi.lib
exit /b %errorlevel%
:missing
echo Install Visual Studio or Build Tools with the "Desktop development with C++" workload, then run this again.
exit /b 1
