@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PROJECT_PYTHON=.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
  echo ERROR: Project virtual environment was not found. Run SETUP.bat.
  goto :failed
)
if not exist "input\script.vi.json" (
  echo ERROR: input\script.vi.json does not exist.
  goto :failed
)
"%PROJECT_PYTHON%" -m src.pipeline --script input\script.vi.json --build
if errorlevel 1 goto :failed
echo.
echo ================================
echo VIETNAMESE VIDEO BUILD COMPLETE
echo ================================
pause
exit /b 0
:failed
echo.
echo VIETNAMESE BUILD FAILED. Read the error above.
pause
exit /b 1
