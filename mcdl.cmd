@echo off
rem mcdl launcher: switch to UTF-8 code page and run from the repo root.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m mcdl %* & exit /b %ERRORLEVEL%)
python -m mcdl %*
exit /b %ERRORLEVEL%
