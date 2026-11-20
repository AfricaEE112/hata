#!/usr/bin/env bash
# Тестова бібліотека для перевірки апки: різні формати й тривалості, потім запуск VidBox.
set -euo pipefail
V="$HOME/vids"
mkdir -p "$V/Кліпи" "$V/Серіали" "$V/Фільми"
# файл уже є (з кешу CI) — не генеруємо заново
gen() { local out="${@: -1}"; [ -s "$out" ] && return 0; ffmpeg -nostdin -v error -y "$@"; }

gen -f lavfi -i "testsrc2=s=1280x720:r=30" -f lavfi -i "sine=f=440:r=44100" -t 15 -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest "$V/Кліпи/Захід сонця.mp4"
gen -f lavfi -i "smptehdbars=s=1280x720:r=30" -f lavfi -i "sine=f=330:r=44100" -t 12 -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest "$V/Кліпи/Кліп 1.mp4"
gen -f lavfi -i "mandelbrot=s=1280x720:r=25" -f lavfi -i "sine=f=550:r=44100" -t 14 -c:v libx265 -preset fast -pix_fmt yuv420p -c:a aac -shortest "$V/Кліпи/Фрактал HEVC.mkv"
gen -f lavfi -i "testsrc=s=1280x720:r=25" -f lavfi -i "sine=f=660:r=48000" -t 20 -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a ac3 -shortest "$V/Кліпи/Концерт AC3.mkv"
gen -f lavfi -i "rgbtestsrc=s=640x360:r=25" -f lavfi -i "sine=f=770:r=44100" -t 10 -c:v mpeg4 -q:v 5 -c:a libmp3lame -shortest "$V/Кліпи/old clip.avi"
gen -f lavfi -i "testsrc2=s=640x360:r=2" -f lavfi -i "sine=f=220:r=22050" -t 1500 -c:v libx264 -preset ultrafast -g 20 -c:a aac -b:a 32k -shortest "$V/Серіали/Серія 01.mp4"
gen -f lavfi -i "smptebars=s=640x360:r=2" -f lavfi -i "sine=f=250:r=22050" -t 1620 -c:v libx264 -preset ultrafast -g 20 -c:a aac -b:a 32k -shortest "$V/Серіали/Серія 02.mp4"
gen -f lavfi -i "smptehdbars=s=640x360:r=1" -f lavfi -i "sine=f=200:r=22050" -t 3900 -c:v libx264 -preset ultrafast -g 10 -c:a aac -b:a 32k -shortest "$V/Фільми/Фільм на вечір.mp4"
# аніме: окрема папка, тайтл = підпапка
A="$HOME/anime/[SubsPlease] Sousou no Frieren (1080p)"
mkdir -p "$A" "$HOME/anime/Cowboy Bebop"
for n in 01 02 10; do
  gen -f lavfi -i "testsrc2=s=1280x720:r=24" -f lavfi -i "sine=f=500:r=44100" -t 10 -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest "$A/[SubsPlease] Sousou no Frieren - $n (1080p).mkv"
done
gen -f lavfi -i "smptebars=s=1280x720:r=24" -f lavfi -i "sine=f=300:r=44100" -t 10 -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest "$HOME/anime/Cowboy Bebop/Cowboy Bebop - 01 - Asteroid Blues.mp4"
# манга: тайтл з розділами-теками і тайтл-«книжка» (сторінки прямо в теці)
M="$HOME/manga"
for ch in 1 2; do
  mkdir -p "$M/Steel Rain/Chapter 00$ch"
  for pg in 1 2 3 4; do gen -f lavfi -i "testsrc2=s=900x1300" -frames:v 1 "$M/Steel Rain/Chapter 00$ch/$pg.jpg"; done
done
mkdir -p "$M/Kaze no Tabibito"
for pg in 1 2 3 4 5 6; do gen -f lavfi -i "smptebars=s=900x1300" -frames:v 1 "$M/Kaze no Tabibito/$pg.jpg"; done
ls -laR "$V" "$HOME/anime" "$M"

nohup python3 "$(dirname "$0")/../../vidbox.py" "$V" --data "$HOME/vbdata" --no-browser > /tmp/vidbox-server.log 2>&1 &
for i in $(seq 1 60); do curl -sf localhost:8800/api/hello && break; sleep 1; done
echo
curl -sf -XPOST localhost:8800/api/settings -d "{\"anime_folder\": \"$HOME/anime\"}"; echo
sleep 3
curl -sf localhost:8800/api/anime > /tmp/anime.json; cat /tmp/anime.json; echo
curl -sf -XPOST localhost:8800/api/settings -d "{\"manga_folder\": \"$HOME/manga\"}"; echo
sleep 2
curl -sf localhost:8800/api/manga > /tmp/manga.json; cat /tmp/manga.json; echo

# чекаємо, поки сервер прочитає файли й наріже кадри
python3 - <<'EOF'
import json, time, urllib.request
def get(p):
    return json.load(urllib.request.urlopen('http://localhost:8800' + p, timeout=30))
def post(p, d):
    r = urllib.request.Request('http://localhost:8800' + p, json.dumps(d).encode(), {'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(r, timeout=30))
for i in range(300):
    lib = get('/api/library')
    if lib['pending'] == 0 and lib['spritesPending'] == 0:
        break
    time.sleep(2)
print('videos:', len(lib['videos']), 'pending:', lib['pending'], 'sprites pending:', lib['spritesPending'])
ids = {v['title']: v['id'] for v in lib['videos']}
print(json.dumps(ids, ensure_ascii=False, indent=1))
# трохи історії переглядів, щоб були рейтинг і «Продовжити перегляд»
seed = [('Кліп 1', 12, 12, True), ('Захід сонця', 15, 15, True), ('Серія 01', 420, 400, False), ('Фільм на вечір', 1300, 1200, False)]
for k, (t, pos, w, end) in enumerate(seed):
    v = next(x for x in lib['videos'] if x['title'] == t)
    post('/api/ping', {'sid': 'seed%d' % k, 'id': v['id'], 'pos': pos, 'dur': v['dur'], 'watched': w, 'start': 0, 'ended': end})
post('/api/vote', {'id': ids['Захід сонця'], 'vote': 1})
json.dump(ids, open('/tmp/ids.json', 'w'), ensure_ascii=False)
EOF
