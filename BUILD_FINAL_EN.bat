@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PROJECT_PYTHON=.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
  echo ERROR: Project virtual environment was not found. Run SETUP.bat.
  goto :failed
)
if not exist "input\topic.json" (
  echo ERROR: input\topic.json does not exist.
  goto :failed
)

"%PROJECT_PYTHON%" -m src.final_assembler --manifest input\topic.json --language en %*
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo ENGLISH FINAL BUILD FAILED. Read the error above.
exit /b 1
