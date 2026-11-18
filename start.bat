@echo off
rem Сумісність: VidBox тепер — застосунок Hata і живе в apps\vidbox.
rem Python і ffmpeg, завантажені раніше сюди, переносяться туди один раз, щоб не качати знову.
chcp 65001 >nul
cd /d "%~dp0"
if exist "python\python.exe" if not exist "apps\vidbox\python" move "python" "apps\vidbox\python" >nul
if exist "ffmpeg" if not exist "apps\vidbox\ffmpeg" move "ffmpeg" "apps\vidbox\ffmpeg" >nul
for %%F in (ffmpeg.exe ffprobe.exe .no-ffmpeg) do if exist "%%F" if not exist "apps\vidbox\%%F" move "%%F" "apps\vidbox\%%F" >nul
call "%~dp0apps\vidbox\start.bat" %*
