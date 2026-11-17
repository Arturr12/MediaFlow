@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Publicar primera Release de MediaFlow 0.4.4
where git >nul 2>nul
if errorlevel 1 goto ERROR

echo Se publicara la primera version estable: v0.4.4
choice /M "Confirmas que el codigo ya esta subido a la rama main"
if errorlevel 2 exit /b 0

git tag v0.4.4 2>nul
if errorlevel 1 echo La etiqueta v0.4.4 ya existia o no pudo crearse.
git push origin v0.4.4
if errorlevel 1 goto ERROR

echo.
echo Etiqueta enviada. GitHub Actions construira el instalador y creara la Release.
echo Revisa la pestana Actions en https://github.com/Arturr12/MediaFlow/actions
echo.
pause
exit /b 0
:ERROR
echo No se pudo subir la etiqueta. Comprueba que el repositorio y la rama main existan.
pause
exit /b 1
