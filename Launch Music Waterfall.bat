@echo off
setlocal

pushd "%~dp0"
if errorlevel 1 goto directory_error

set "MUSIC_WATERFALL_UV="
where.exe uv.exe >nul 2>&1
if not errorlevel 1 set "MUSIC_WATERFALL_UV=uv.exe"

if not defined MUSIC_WATERFALL_UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "MUSIC_WATERFALL_UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined MUSIC_WATERFALL_UV if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" set "MUSIC_WATERFALL_UV=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
if not defined MUSIC_WATERFALL_UV if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\uv.exe" set "MUSIC_WATERFALL_UV=%LOCALAPPDATA%\Microsoft\WindowsApps\uv.exe"

if not defined MUSIC_WATERFALL_UV goto uv_missing
if /I "%~1"=="--check" goto check_only

echo Starting Music Waterfall...
"%MUSIC_WATERFALL_UV%" run music-waterfall-gui
set "MUSIC_WATERFALL_EXIT=%ERRORLEVEL%"
if "%MUSIC_WATERFALL_EXIT%"=="0" goto finish

echo.
echo Music Waterfall did not start successfully.
echo Run the Windows installer again, then run: uv run music-waterfall doctor
pause
goto finish

:check_only
echo Music Waterfall launcher found uv at: %MUSIC_WATERFALL_UV%
"%MUSIC_WATERFALL_UV%" --version
set "MUSIC_WATERFALL_EXIT=%ERRORLEVEL%"
goto finish

:uv_missing
echo Music Waterfall cannot start because uv was not found.
echo.
echo Run this command from the repository directory:
echo powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\install-windows.ps1"
echo.
pause
popd
exit /b 1

:directory_error
echo Music Waterfall could not open its repository directory.
pause
exit /b 1

:finish
popd
exit /b %MUSIC_WATERFALL_EXIT%
