@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto cannot_enter_repo

where py >nul 2>&1
if errorlevel 1 goto python_missing
py -3.14 --version >nul 2>&1
if errorlevel 1 goto python_missing

where docker >nul 2>&1
if errorlevel 1 goto docker_missing
docker info >nul 2>&1
if errorlevel 1 goto docker_not_running

if exist ".venv\Scripts\python.exe" goto check_venv
echo Creando entorno virtual con Python 3.14...
py -3.14 -m venv .venv
if errorlevel 1 goto venv_failed

:check_venv
".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info[:2] != (3, 14))"
if errorlevel 1 goto wrong_venv

echo Instalando o verificando dependencias de desarrollo...
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 goto dependencies_failed

if not defined LOCALAPPDATA goto localappdata_missing
set "QA_TEMP_ROOT=%LOCALAPPDATA%\PollsQA"
if not exist "%QA_TEMP_ROOT%" mkdir "%QA_TEMP_ROOT%"
if errorlevel 1 goto temp_root_failed

set "QA_BASETEMP=%QA_TEMP_ROOT%\run-%RANDOM%-%RANDOM%"
mkdir "%QA_BASETEMP%"
if errorlevel 1 goto basetemp_failed

echo.
echo Ejecutando pruebas de servicio, contrato e integracion...
".venv\Scripts\python.exe" -m pytest -o "addopts=" --basetemp="%QA_BASETEMP%" -v --tb=short
set "QA_EXIT_CODE=%ERRORLEVEL%"
if not "%QA_EXIT_CODE%"=="0" goto tests_failed

rmdir /s /q "%QA_BASETEMP%" >nul 2>&1
echo.
echo QA completo: todas las pruebas seleccionadas terminaron correctamente.
exit /b 0

:cannot_enter_repo
echo ERROR: no se pudo abrir la carpeta del repositorio.
exit /b 1

:python_missing
echo ERROR: no se encontro Python 3.14 mediante el lanzador "py".
echo Instala Python 3.14 y vuelve a ejecutar este archivo.
echo Puedes revisar las versiones detectadas con: py -0p
exit /b 1

:docker_missing
echo ERROR: no se encontro el comando docker. Instala Docker Desktop.
exit /b 1

:docker_not_running
echo ERROR: Docker no esta disponible. Inicia Docker Desktop y vuelve a intentarlo.
exit /b 1

:venv_failed
echo ERROR: no se pudo crear .venv con Python 3.14.
exit /b 1

:wrong_venv
echo ERROR: el entorno .venv existente no usa Python 3.14.
echo Renombra o elimina manualmente .venv y vuelve a ejecutar este archivo.
exit /b 1

:dependencies_failed
echo ERROR: no se pudieron instalar las dependencias de requirements-dev.txt.
exit /b 1

:localappdata_missing
echo ERROR: Windows no definio LOCALAPPDATA; no se puede preparar la carpeta temporal.
exit /b 1

:temp_root_failed
echo ERROR: no se pudo crear "%QA_TEMP_ROOT%".
exit /b 1

:basetemp_failed
echo ERROR: no se pudo crear la carpeta temporal "%QA_BASETEMP%".
exit /b 1

:tests_failed
echo.
echo QA termino con errores. Codigo de salida: %QA_EXIT_CODE%.
echo La carpeta temporal de esta ejecucion se conserva en: %QA_BASETEMP%
exit /b %QA_EXIT_CODE%
