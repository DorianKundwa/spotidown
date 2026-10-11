@echo off
setlocal
cd /d "%~dp0"
title SpotiDown Launcher

echo Starting SpotiDown Launcher...
echo.

:: 1. Try Python 3.12 launcher
where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3.12 launcher.py %*
    if %errorlevel% equ 0 goto :success
    
    :: 2. Fall back to generic py -3
    py -3 launcher.py %*
    if %errorlevel% equ 0 goto :success
)

:: 3. Fall back to default python
where python >nul 2>&1
if %errorlevel% equ 0 (
    python launcher.py %*
    if %errorlevel% equ 0 goto :success
)

echo.
echo [ERROR] Could not start SpotiDown with Python.
echo Please ensure Python 3.10+ is installed and in your PATH.
echo.
pause
exit /b 1

:success
endlocal
exit /b 0
