@echo off
chcp 65001 >nul
title VidBox
cd /d "%~dp0"
set "PYEXE="
set "PYARG="

rem --- 1. Portable Python next to VidBox (downloaded on first run) ---
if exist "%~dp0python\python.exe" set "PYEXE=%~dp0python\python.exe"
if defined PYEXE goto ffmpeg

rem --- 2. py launcher from python.org ---
py -3 -c "import sqlite3" >nul 2>nul
if not errorlevel 1 set "PYEXE=py"
if not errorlevel 1 set "PYARG=-3"
if defined PYEXE goto ffmpeg

rem --- 3. python in PATH (the Microsoft Store stub fails this check) ---
python -c "import sqlite3" >nul 2>nul
if not errorlevel 1 set "PYEXE=python"
if defined PYEXE goto ffmpeg

rem --- 4. Standard install folder, even if not in PATH ---
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
if defined PYEXE goto ffmpeg

rem --- 5. Nothing found: download portable Python (~11 MB) ---
echo.
echo Python на цьому комп'ютері не знайдено.
echo Завантажую портативний Python (~11 МБ) у папку "python" поруч з VidBox...
echo У систему нічого не встановлюється, це потрібно лише один раз.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' -OutFile 'python.zip'; Expand-Archive -Force 'python.zip' 'python'; Remove-Item 'python.zip'"
if exist "%~dp0python\python.exe" set "PYEXE=%~dp0python\python.exe"
if defined PYEXE goto ffmpeg
echo.
echo Не вдалося завантажити Python автоматично (немає інтернету?).
echo Встанови його вручну: https://www.python.org/downloads/
echo Під час встановлення постав галочку "Add python.exe to PATH".
goto end

:ffmpeg
rem --- ffmpeg: covers, frame strips, MKV/AVI conversion ---
if exist "%~dp0ffmpeg.exe" goto launch
if exist "%~dp0ffmpeg\ffmpeg.exe" goto launch
where ffmpeg >nul 2>nul
if not errorlevel 1 goto launch
if exist "%~dp0.no-ffmpeg" goto launch
echo.
echo Для обкладинок, нарізок кадрів і конвертації MKV/AVI потрібен ffmpeg (~90 МБ).
echo   1 - завантажити зараз
echo   2 - не зараз
echo   3 - не питати більше
choice /C 123 /N /M "[1/2/3]: "
if errorlevel 3 goto noask
if errorlevel 2 goto launch
echo.
echo Завантажую ffmpeg, це може зайняти кілька хвилин...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile 'ffmpeg.zip'; Add-Type -AssemblyName System.IO.Compression.FileSystem; New-Item -ItemType Directory -Force 'ffmpeg' | Out-Null; $dst = (Resolve-Path 'ffmpeg').Path; $z = [IO.Compression.ZipFile]::OpenRead((Resolve-Path 'ffmpeg.zip').Path); foreach ($e in $z.Entries) { if ($e.Name -eq 'ffmpeg.exe' -or $e.Name -eq 'ffprobe.exe') { [IO.Compression.ZipFileExtensions]::ExtractToFile($e, (Join-Path $dst $e.Name), $true) } }; $z.Dispose(); Remove-Item 'ffmpeg.zip'"
if exist "%~dp0ffmpeg\ffmpeg.exe" goto ffok
echo Не вдалося завантажити ffmpeg. Можна скачати вручну з https://www.gyan.dev/ffmpeg/builds/
echo і покласти ffmpeg.exe та ffprobe.exe поруч з vidbox.py.
goto launch
:ffok
echo ffmpeg готовий.
goto launch
:noask
type nul > "%~dp0.no-ffmpeg"

:launch
"%PYEXE%" %PYARG% vidbox.py %*

:end
echo.
pause
