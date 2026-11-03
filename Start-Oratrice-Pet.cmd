@echo off
setlocal DisableDelayedExpansion
set "ORATRICE_PET_ROOT=%~dp0"
set "ORATRICE_PET_PYTHON=%ORATRICE_PET_ROOT%.venv\Scripts\pythonw.exe"
if defined ORATRICE_PYTHON set "ORATRICE_PET_PYTHON=%ORATRICE_PYTHON%"
for %%P in ("%ORATRICE_PET_PYTHON%") do set "ORATRICE_PET_PYTHON=%%~fP"
if not exist "%ORATRICE_PET_PYTHON%" (
    echo Oratrice's Python environment was not found.
    echo Run scripts\setup_oratrice.ps1 first, or set ORATRICE_PYTHON to Python.
    pause
    exit /b 2
)
for %%P in ("%ORATRICE_PET_PYTHON%") do (
    if /I "%%~nxP"=="python.exe" if exist "%%~dpPpythonw.exe" set "ORATRICE_PET_PYTHON=%%~dpPpythonw.exe"
)
pushd "%ORATRICE_PET_ROOT%"
if errorlevel 1 exit /b 2
start "" "%ORATRICE_PET_PYTHON%" -m frontends.pet %*
set "ORATRICE_PET_EXIT=%ERRORLEVEL%"
popd
exit /b %ORATRICE_PET_EXIT%
