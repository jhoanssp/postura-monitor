@echo off
REM =============================================================================
REM build_windows.bat — Monitor de Postura v4 — Build Windows
REM =============================================================================
setlocal enabledelayedexpansion

set APP_NAME=postura-monitor
set APP_VERSION=4.5.1
set PROJECT_ROOT=%~dp0..

echo ============================================================
echo   Monitor de Postura v4 - Build Windows
echo ============================================================
cd /d "%PROJECT_ROOT%"

REM ── Verificar Python ─────────────────────────────────────────────────────────
echo.
echo [0/5] Verificando Python...
set PYTHON_CMD=
for %%v in (python3.11 python3.10 python) do (
    where %%v >nul 2>&1
    if not errorlevel 1 (
        for /f "tokens=*" %%i in ('%%v -c "import sys; v=sys.version_info; print(str(v.major)+'.'+str(v.minor))"') do set PYVER=%%i
        if "!PYVER!"=="3.10" set PYTHON_CMD=%%v
        if "!PYVER!"=="3.11" set PYTHON_CMD=%%v
    )
)
if "!PYTHON_CMD!"=="" (
    echo ERROR: No se encontro Python 3.10 o 3.11.
    exit /b 1
)
echo     Usando: !PYTHON_CMD! (!PYVER!)

REM ── 1. Entorno virtual ───────────────────────────────────────────────────────
echo.
echo [1/5] Preparando entorno virtual...
if exist "venv\" rmdir /s /q "venv\"
!PYTHON_CMD! -m venv venv
call venv\Scripts\activate.bat

python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet
echo     Dependencias instaladas.

REM ── 2. Entrenar modelos RF ────────────────────────────────────────────────────
echo.
echo [2/5] Entrenando modelos Random Forest...
if not exist "models\rf_upperbody.pkl" (
    if exist "data.csv" (
        python entrenamiento_rf.py --csv data.csv --no-cv
        echo     Modelos RF generados.
    ) else (
        echo     ADVERTENCIA: data.csv no encontrado.
    )
) else (
    echo     Modelos RF ya existen, reutilizando.
)

REM ── 3. PyInstaller ───────────────────────────────────────────────────────────
echo.
echo [3/5] Compilando con PyInstaller...
if exist "dist\" rmdir /s /q "dist\"
if exist "build\" rmdir /s /q "build\"

pyinstaller packaging\postura_monitor.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller fallo.
    exit /b 1
)

REM ── Copiar models al ejecutable (xcopy /Y evita la pregunta interactiva) ──────
if exist "models\" (
    echo     Copiando modelos RF al ejecutable...
    xcopy /E /I /Y /Q "models\" "dist\postura-monitor\_internal\models\"
    echo     Modelos copiados.
)
echo     Compilacion exitosa.

REM ── 4. Comprimir distribucion ────────────────────────────────────────────────
echo.
echo [4/5] Preparando distribucion...
if not exist "build_output\" mkdir build_output

set ZIP_OUT=build_output\postura-monitor_%APP_VERSION%_windows.zip
set ZIP_SRC=dist\postura-monitor\

powershell -Command "Compress-Archive -Path '%ZIP_SRC%*' -DestinationPath '%ZIP_OUT%' -Force"
if errorlevel 1 (
    echo ERROR: No se pudo crear el ZIP.
    exit /b 1
)
echo     ZIP creado: %ZIP_OUT%

REM ── 5. Inno Setup ────────────────────────────────────────────────────────────
echo.
echo [5/5] Buscando Inno Setup...
set "INNO="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "INNO=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "INNO=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if defined INNO (
    echo     Inno Setup encontrado. Creando instalador .exe...
    "%INNO%" packaging\instalador_windows.iss
    if not errorlevel 1 (
        echo     Instalador .exe creado en build_output\
    )
) else (
    echo     Inno Setup no encontrado, usando solo el ZIP.
)

call venv\Scripts\deactivate.bat

echo.
echo ============================================================
echo   BUILD COMPLETADO - Archivos en: build_output\
echo ============================================================
