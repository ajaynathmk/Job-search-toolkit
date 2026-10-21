@echo off
rem Double-click to start the job-search application (Windows).
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python app.py %*
) else (
  where py >nul 2>nul
  if %errorlevel%==0 ( py -3 app.py %* ) else ( echo Python 3.10 or newer is needed: https://www.python.org/downloads/ )
)
echo.
pause
