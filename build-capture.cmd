@echo off
setlocal
cd /d "%~dp0"
if not exist bin mkdir bin
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1
cl /nologo /O2 /EHsc /std:c++17 /MT native\capture.cpp /Fo:bin\capture.obj /Fe:bin\capture.exe /link Ole32.lib Mmdevapi.lib
exit /b %errorlevel%
