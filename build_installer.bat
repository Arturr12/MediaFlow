@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MediaFlow - Crear instalador
set "VENV=%~dp0.build-venv"
set "PYEXE=%VENV%\Scripts\python.exe"
set "ISCC="
for /f "tokens=2" %%A in (VERSION.txt) do set "APP_VERSION=%%A"
if not defined APP_VERSION set "APP_VERSION=0.4.4"
where py >nul 2>nul || goto ERROR
py -3.13 --version >nul 2>nul || goto ERROR
if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "ISCC=%%I"
if not defined ISCC goto ERROR
if not exist "%PYEXE%" py -3.13 -m venv "%VENV%"
if errorlevel 1 goto ERROR
"%PYEXE%" -m pip install --disable-pip-version-check -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto ERROR
"%PYEXE%" tools\set_version.py --version "%APP_VERSION%"
if errorlevel 1 goto ERROR
"%PYEXE%" -m PyInstaller --noconfirm --clean --windowed --onedir --name MediaFlow --icon mediaflow.ico --add-data "mediaflow.ico;." --collect-all yt_dlp --collect-all yt_dlp_ejs --copy-metadata yt-dlp --copy-metadata yt-dlp-ejs app.py
if errorlevel 1 goto ERROR
if exist payload\MediaFlow rmdir /s /q payload\MediaFlow
mkdir payload\MediaFlow
xcopy dist\MediaFlow\* payload\MediaFlow\ /E /I /H /Y >nul
copy /Y THIRD_PARTY_NOTICES.txt payload\MediaFlow\THIRD_PARTY_NOTICES.txt >nul
if exist Output rmdir /s /q Output
mkdir Output
"%ISCC%" /DMyAppVersion=%APP_VERSION% MediaFlow-Setup.iss
if errorlevel 1 goto ERROR
"%PYEXE%" tools\create_update_manifest.py --version "%APP_VERSION%" --installer "Output\MediaFlow-Setup-%APP_VERSION%.exe" --output "Output\mediaflow-update.json" --notes RELEASE_NOTES.md
if errorlevel 1 goto ERROR
echo.
echo Instalador generado: Output\MediaFlow-Setup-%APP_VERSION%.exe
echo Manifiesto generado: Output\mediaflow-update.json
echo.
pause
exit /b 0
:ERROR
echo No se pudo crear el instalador. Revisa Python 3.13, Inno Setup y el mensaje anterior.
pause
exit /b 1
