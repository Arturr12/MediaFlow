@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MediaFlow 0.4.4 - Prueba directa

set "VENV=%~dp0.venv"
set "PYEXE=%VENV%\Scripts\python.exe"

echo.
echo ======================================================
echo   MEDIAFLOW 0.4.4 - EJECUCION DIRECTA (SIN INSTALADOR)
echo ======================================================
echo.

where py >nul 2>nul
if errorlevel 1 goto ERROR_NO_PY
py -3.13 --version
if errorlevel 1 goto ERROR_PY

if exist "%PYEXE%" goto VENV_READY
echo [1/3] Creando entorno virtual local...
py -3.13 -m venv "%VENV%"
if errorlevel 1 goto ERROR_RUN

:VENV_READY
echo [2/3] Comprobando dependencias...
"%PYEXE%" -c "import PySide6, yt_dlp" >nul 2>nul
if not errorlevel 1 goto DEPS_READY

echo Instalando dependencias necesarias. Esto solo ocurre en la primera ejecucion...
"%PYEXE%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto ERROR_RUN

:DEPS_READY
echo [3/3] Iniciando MediaFlow...
echo La ventana de esta consola debe permanecer abierta mientras pruebas la aplicacion.
echo.
"%PYEXE%" "%~dp0app.py"
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo MediaFlow termino con codigo: %APP_EXIT%
    echo Si aparecio un error, puedes copiarlo desde esta ventana.
)
echo.
echo Prueba finalizada. Presiona una tecla para cerrar esta ventana.
pause >nul
exit /b %APP_EXIT%

:ERROR_NO_PY
echo ERROR: No se encontro Python Launcher (py).
echo Instala Python 3.13 de 64 bits y vuelve a ejecutar este archivo.
goto ERROR_END

:ERROR_PY
echo ERROR: No se pudo ejecutar Python 3.13.
goto ERROR_END

:ERROR_RUN
echo ERROR: No se pudo preparar el entorno o iniciar MediaFlow.
goto ERROR_END

:ERROR_END
echo.
pause
exit /b 1
