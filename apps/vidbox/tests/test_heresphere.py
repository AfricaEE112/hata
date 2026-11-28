"""Протокол HereSphere у VidBox: вхід, каталог, картка відео, субтитри SRT, події → прогрес.

Запускає справжній vidbox.py на тимчасових теках. Відео — коротке, з ffmpeg (якщо його немає — фіктивні файли,
тоді перевірка субтитрів пропускається).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VB = os.path.join(HERE, '..', 'vidbox.py')


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def post(url, d=None):
    req = urllib.request.Request(url, data=json.dumps(d or {}).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.headers, json.loads(r.read())


def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.status, r.read()


def main():
    tmp = tempfile.mkdtemp()
    films, anime, data = (os.path.join(tmp, x) for x in ('Films', 'Anime', 'data'))
    os.makedirs(os.path.join(anime, 'Frieren'))
    os.makedirs(films)
    os.makedirs(data)
    ff = shutil.which('ffmpeg')
    movie = os.path.join(films, 'Test Movie.mp4')
    if ff:
        subprocess.run([ff, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24', '-f', 'lavfi', '-i', 'sine',
                        '-t', '4', '-c:v', 'libx264', '-b:v', '600k', '-c:a', 'aac', '-shortest', movie], check=True)
    else:
        open(movie, 'wb').write(b'\0' * 200000)      # сканер пропускає файли < 64 КБ
    for n in (1, 2):
        shutil.copy(movie, os.path.join(anime, 'Frieren', 'Frieren - %02d.mp4' % n))
    open(os.path.join(films, 'Test Movie.uk.srt'), 'w', encoding='utf-8').write('1\n00:00:01,000 --> 00:00:03,000\nПривіт\n')
    json.dump({'anime_folder': anime, 'folders': [films, anime], 'open_browser': False}, open(os.path.join(data, 'config.json'), 'w'))
    port = free_port()
    proc = subprocess.Popen([sys.executable, VB, films, anime, '--data', data, '--port', str(port), '--password', 'secret1',
                             '--no-browser'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = 'http://127.0.0.1:%d' % port
    try:
        for _ in range(60):
            try:
                h, idx = post(base + '/heresphere', {'username': 'x', 'password': 'secret1'})
                if sum(len(s['list']) for s in idx.get('library', [])) >= 3:
                    break
            except OSError:
                pass
            time.sleep(1)
        assert h.get('HereSphere-JSON-Version') == '1', dict(h)
        assert idx['access'] == 1, idx
        names = [s['name'] for s in idx['library']]
        print('розділи:', names)
        assert 'Нове' in names and 'Аніме · Frieren' in names and 'Films' in names, names
        # без пароля — просить вхід, з неправильним — відмова
        assert post(base + '/heresphere')[1]['access'] == 0
        assert post(base + '/heresphere', {'username': 'x', 'password': 'bad'})[1]['access'] == -1
        film_url = next(s for s in idx['library'] if s['name'] == 'Films')['list'][0]
        assert '?k=' in film_url, film_url
        _, card = post(film_url, {'needsMediaSource': True})
        print('картка:', card['title'], card['duration'], [m['name'] for m in card['media']], [s['name'] for s in card['subtitles']])
        assert card['title'] == 'Test Movie' and card['projection'] == 'perspective' and card['stereo'] == 'mono'
        src = card['media'][-1 if len(card['media']) == 1 else 0]['sources'][0]['url']
        st, body = get(next(m for m in card['media'] if m['name'].startswith('Оригінал'))['sources'][0]['url'])
        assert st == 200 and len(body) > 1000, st
        assert card['subtitles'] and card['subtitles'][0]['language'] == 'uk', card['subtitles']
        if ff:
            st, srt = get(card['subtitles'][0]['url'])
            assert 'Привіт' in srt.decode() and '00:00:01,000 --> 00:00:03,000' in srt.decode(), srt
        # чужий токен у посиланні — 401
        try:
            get(src.split('?')[0] + '?k=bad')
            assert False, 'мало бути 401'
        except urllib.error.HTTPError as e:
            assert e.code == 401
        # подія «пауза на 2,5 с» → прогрес у VidBox
        ev = card['eventServer']
        post(ev, {'event': 1, 'time': 500})
        post(ev, {'event': 2, 'time': 2500})
        vid = film_url.split('/heresphere/')[1].split('?')[0]
        _, card2 = post(film_url, {'isFavorite': True})
        assert card2['isFavorite'] is True
        with urllib.request.urlopen(urllib.request.Request(base + '/api/library', headers={'Cookie': 'vb=' + film_url.split('k=')[1]})) as r:
            lib = json.loads(r.read())
        v = next(x for x in lib['videos'] if x['id'] == vid)
        print('прогрес:', v['pos'], 'голос:', v['vote'])
        assert abs(v['pos'] - 2.5) < 0.01, v
        assert v['vote'] == 1
        st, page = get(base + '/heresphere')
        assert st == 200 and b'HereSphere' in page
        print('HereSphere: OK')
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=10)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            out = ''
        if sys.exc_info()[0]:
            print(out[-3000:])
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
