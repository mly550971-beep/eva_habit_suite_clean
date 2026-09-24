@echo off
setlocal
cd /d "%~dp0"

echo [1/3] Installing runtime + packaging dependencies...
py -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail

echo [2/3] Building Habit Tracker...
py -m PyInstaller --noconfirm --clean --windowed --name HabitTracker main.py
if errorlevel 1 goto :fail

echo [3/3] Done. The executable is in dist\HabitTracker\HabitTracker.exe
exit /b 0

:fail
echo.
echo Build failed. Check the message above.
exit /b 1
