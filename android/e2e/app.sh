#!/usr/bin/env bash
# Ставить APK на емулятор, підключається до тестового сервера і знімає екрани.
set -x
OUT="${GITHUB_WORKSPACE:-$PWD}/ci-out"
mkdir -p "$OUT"
PKG=app.vidbox

# якщо емулятор зник (буває на GitHub), не висимо, а виходимо з поміткою
alive() { [ "$(timeout 10 adb get-state 2>/dev/null)" = "device" ] || { echo "emulator died before: $1" >> "$OUT/EMULATOR_DIED"; exit 0; }; }
shot() { alive "$1"; timeout 30 adb exec-out screencap -p > "$OUT/$1.png"; }
# назви сервер чистить («Фрактал HEVC» → «Фрактал»), тож шукаємо за початком назви
id_of() { python3 -c "import json,sys; d=json.load(open('/tmp/ids.json')); print(next(v for k, v in d.items() if k.startswith(sys.argv[1])))" "$1"; }
# підказка Android «Viewing full screen» з'являється при першому повноекранному режимі
dismiss_hint() { has_text "Got it" && tap_text "Got it"; }
open_route() { adb shell am start -n $PKG/.MainActivity --es route "$1" > /dev/null; }
dump() { timeout 25 adb shell uiautomator dump /sdcard/ui.xml > /dev/null 2>&1; timeout 10 adb shell cat /sdcard/ui.xml 2>/dev/null; }
has_text() { dump | grep -q "$1"; }
tap_text() {
  local xy
  xy=$(dump | python3 -c "
import re, sys
xml = sys.stdin.read()
for m in re.finditer(r'<node [^>]*>', xml):
    n = m.group(0)
    if 'text=\"' + sys.argv[1] + '\"' in n or 'content-desc=\"' + sys.argv[1] + '\"' in n:
        b = re.search(r'bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"', n)
        if b:
            x1, y1, x2, y2 = map(int, b.groups())
            print((x1 + x2) // 2, (y1 + y2) // 2)
            break
" "$1")
  [ -n "$xy" ] && adb shell input tap $xy
}
# лише падіння самої VidBox (системні апки емулятора теж іноді падають)
crashed() { timeout 60 adb logcat -d | grep -A 30 "FATAL EXCEPTION" | grep -A 28 "Process: app.vidbox" | head -60; }

adb install -r VidBox-*.apk || { echo "install failed" > "$OUT/FAIL"; exit 0; }
adb shell settings put system screen_off_timeout 1800000
adb shell svc power stayon true
adb logcat -c

# ── перший запуск: апка шукає ПК у мережі (емулятор бачить ПК як 10.0.2.2) ──
adb shell am start -W -n $PKG/.MainActivity
sleep 2.5
shot 01-connect
connected=0
for i in $(seq 1 25); do
  sleep 2
  if ! has_text "Знайди свій ПК"; then connected=1; break; fi
done
if [ $connected = 0 ]; then
  shot 01b-connect-not-found
  echo "auto-discovery failed, typing the address" >> "$OUT/NOTES.txt"
  tap_text "192.168.1.10:8800"; sleep 1
  adb shell input text "10.0.2.2:8800"; sleep 0.5
  adb shell input keyevent 66; sleep 6
fi
sleep 5
shot 02-home
adb shell input swipe 540 1900 540 600 350; sleep 1.5
shot 03-home-2
adb shell input swipe 540 1900 540 500 350; sleep 1.5
shot 04-home-3

open_route lib; sleep 3
shot 05-library
tap_text "Тривалість"; sleep 2
shot 06-library-duration
tap_text "Усі"; sleep 1

open_route pl; sleep 3
shot 07-playlists
open_route pl/short; sleep 3
shot 08-playlist
open_route top; sleep 3
shot 09-top
# ── аніме ──
open_route anime; sleep 4
shot 09b-anime
SID=$(python3 -c "import json;print([t['sid'] for t in json.load(open('/tmp/anime.json'))['titles'] if 'Frieren' in t['title']][0])")
open_route "anime/$SID"; sleep 4
shot 09c-anime-title
tap_text "Дивитися з першої"; sleep 3
dismiss_hint; sleep 4
shot 09d-anime-player
adb shell input keyevent 4; sleep 2
open_route "i/$(id_of 'Захід сонця')"; sleep 4
shot 10-info
adb shell input swipe 540 1900 540 700 350; sleep 1.5
shot 11-info-2
open_route settings; sleep 4
shot 12-settings
adb shell input swipe 540 1900 540 600 350; sleep 1.5
shot 13-settings-2
adb shell input swipe 540 1900 540 300 350; sleep 1.5
shot 13b-settings-3

# ── плеєр: звичайний MP4 ──
open_route "v/$(id_of 'Захід сонця')"; sleep 2
dismiss_hint; sleep 0.6
shot 14-player-controls
sleep 7
shot 15-player-playing
# кнопки (контролер Quest / пульт): пауза й перемотка вперед
adb shell input keyevent 62; sleep 1; adb shell input keyevent 22; sleep 1.5
shot 15a-player-keys
adb shell input keyevent 4; sleep 2

# якість 480p: ПК перекодовує на льоту
adb shell am start -n $PKG/.MainActivity --es quality 480 --es route "v/$(id_of 'Захід сонця')" > /dev/null; sleep 2.5
dismiss_hint; sleep 0.3
shot 15b-player-live480
sleep 6
shot 15c-player-live480-playing
adb shell input keyevent 4; sleep 2
adb shell am start -n $PKG/.MainActivity --es quality auto > /dev/null; sleep 1

# HEVC у MKV — телефон грає напряму
open_route "v/$(id_of 'Фрактал')"; sleep 2; dismiss_hint; sleep 7
shot 16-player-hevc
adb shell input keyevent 4; sleep 2

# MKV зі звуком AC3: у емулятора немає декодера → ПК робить копію MP4
open_route "v/$(id_of 'Концерт')"; sleep 2; dismiss_hint; sleep 3
shot 17-player-ac3-prepare
sleep 30
shot 18-player-ac3-playing
adb shell input keyevent 4; sleep 2

# AVI (MPEG-4 Part 2 + MP3)
open_route "v/$(id_of 'old clip')"; sleep 2; dismiss_hint; sleep 6
shot 19-player-avi
adb shell input keyevent 4; sleep 2

# плейлист: відтворення підряд
open_route pl/short; sleep 3
tap_text "Відтворити все"; sleep 2; dismiss_hint; sleep 1
shot 20-player-queue
adb shell input keyevent 4; sleep 2
shot 21-after-player

# ── перевірки ──
pid=$(adb shell pidof $PKG | tr -d '\r')
timeout 60 adb logcat -d > "$OUT/logcat-all.txt"
[ -n "$pid" ] && timeout 60 adb logcat -d --pid="$pid" > "$OUT/logcat-app.txt"
curl -s localhost:8800/api/library > "$OUT/library.json"
python3 - "$OUT" <<'EOF' >> "$OUT/NOTES.txt"
import json, sys
lib = json.load(open(sys.argv[1] + '/library.json'))
for v in lib['videos']:
    print('%-22s views=%-2s pos=%-7.1f prep=%s ready=%s' % (v['title'], v['views'], v['pos'] or 0, v['prep'], v['ready']))
EOF
cat "$OUT/NOTES.txt"
c=$(crashed)
if [ -n "$c" ]; then
  echo "$c" > "$OUT/CRASH.txt"
  echo "CRASH"
elif [ -z "$pid" ]; then
  echo "app is not running" > "$OUT/FAIL"
else
  touch "$OUT/OK"
fi
exit 0
