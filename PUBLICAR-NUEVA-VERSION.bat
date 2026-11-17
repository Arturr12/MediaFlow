@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Publicar nueva version de MediaFlow
where git >nul 2>nul
if errorlevel 1 goto ERROR

echo Antes de continuar, edita RELEASE_NOTES.md con las novedades reales.
echo.
set /p VERSION=Escribe la nueva version (ejemplo 0.4.5):
if "%VERSION%"=="" goto ERROR

echo Preparando MediaFlow %VERSION%...
py -3.13 tools\set_version.py --version "%VERSION%"
if errorlevel 1 goto ERROR

git add .
git commit -m "Preparar MediaFlow %VERSION%"
if errorlevel 1 goto ERROR
git push origin main
if errorlevel 1 goto ERROR
git tag "v%VERSION%"
if errorlevel 1 goto ERROR
git push origin "v%VERSION%"
if errorlevel 1 goto ERROR

echo.
echo Etiqueta publicada. GitHub Actions construira y publicara el instalador.
echo Revisa: https://github.com/Arturr12/MediaFlow/actions
echo.
pause
exit /b 0
:ERROR
echo No se pudo completar la publicacion. Revisa version, Git y RELEASE_NOTES.md.
pause
exit /b 1
