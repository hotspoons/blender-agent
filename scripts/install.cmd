@echo off
REM SPDX-FileCopyrightText: 2026 Blender Authors
REM SPDX-License-Identifier: GPL-3.0-or-later
REM
REM Double-click this from a checkout, or run it from cmd. It launches the
REM PowerShell installer with Bypass scoped to THIS process only - no admin
REM rights and no machine-wide Set-ExecutionPolicy. Any args are forwarded:
REM   install.cmd -Uninstall
REM   install.cmd -PackagesOnly
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo. & echo Install failed (exit %RC%) - see messages above.
echo.
pause
exit /b %RC%
