@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Publicar MediaFlow en GitHub

echo ==============================================
echo   PUBLICAR CODIGO DE MEDIAFLOW EN GITHUB
echo ==============================================
echo.
where git >nul 2>nul
if errorlevel 1 goto NO_GIT

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 git init
if errorlevel 1 goto ERROR

git branch -M main
if errorlevel 1 goto ERROR

git remote get-url origin >nul 2>nul
if errorlevel 1 git remote add origin https://github.com/Arturr12/MediaFlow.git
if errorlevel 1 goto ERROR

echo [1/3] Agregando archivos...
git add .
if errorlevel 1 goto ERROR

echo [2/3] Creando commit inicial...
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Publicar codigo fuente de MediaFlow 0.4.4"
  if errorlevel 1 goto ERROR
) else (
  echo No hay cambios nuevos que confirmar.
)

echo [3/3] Subiendo a https://github.com/Arturr12/MediaFlow ...
git push -u origin main
if errorlevel 1 goto ERROR

echo.
echo ==============================================
echo   CODIGO PUBLICADO CORRECTAMENTE
echo ==============================================
echo Ahora ejecuta PUBLICAR-PRIMERA-RELEASE.bat
echo para compilar y publicar MediaFlow 0.4.4.
echo.
pause
exit /b 0

:NO_GIT
echo No se encontro Git para Windows.
echo Instala Git for Windows, cierra esta ventana y vuelve a ejecutar este archivo.
echo Descarga oficial: https://git-scm.com/download/win
goto ERROR
:ERROR
echo.
echo No se pudo publicar. Copia el mensaje anterior para revisar el problema.
pause
exit /b 1
