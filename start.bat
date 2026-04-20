@echo off
title AI Baby Book Launcher
echo.
echo  =========================================
echo   AI Baby Book - Starting up...
echo  =========================================
echo.

:: Check .env exists
if not exist "%~dp0backend\.env" (
    echo  ERROR: backend\.env not found.
    echo  Create it with: ANTHROPIC_API_KEY=sk-ant-...
    echo.
    pause
    exit /b 1
)

:: Start backend
echo  Starting backend on http://localhost:8000 ...
start "AI Baby Book - Backend" cmd /k "cd /d "%~dp0backend" && python -m uvicorn main:app --reload --port 8000"

:: Brief pause so backend gets a head start
timeout /t 3 /nobreak > nul

:: Start frontend
echo  Starting frontend on http://localhost:3000 ...
start "AI Baby Book - Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo  Both servers are starting. Opening browser in 8 seconds...
echo  (Close the two server windows to shut everything down)
echo.
timeout /t 8 /nobreak > nul

start http://localhost:3000
exit
