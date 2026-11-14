#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VidBox — домашній відеосервер «як Jellyfin, але свій».

Запуск:
    python vidbox.py                         # спитає папку і запам'ятає її
    python vidbox.py "D:\\Videos" "E:\\Кіно"   # одна або кілька папок
    python vidbox.py --port 8800 --password 1234
    python vidbox.py --pick                  # вибрати папку заново

Потім відкрий на телефоні адресу, яку покаже програма (телефон у тому ж Wi-Fi).
Працює на чистому Python 3.8+, без сторонніх бібліотек.
ffmpeg — необов'язковий: з ним будуть прев'юшки і конвертація MKV/AVI для телефону.
"""
import argparse
import datetime
import hashlib
import hmac
import http.cookies
import http.server
import json
import math
import os
import queue
import random
import re
import secrets
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
import zlib
import platform
import string
from concurrent.futures import ThreadPoolExecutor

APP = 'VidBox'
VERSION = '0.4'

VIDEO_EXT = {
    '.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mov': 'video/quicktime',
    '.webm': 'video/webm', '.mkv': 'video/x-matroska', '.avi': 'video/x-msvideo',
    '.wmv': 'video/x-ms-wmv', '.flv': 'video/x-flv', '.ts': 'video/mp2t',
    '.m2ts': 'video/mp2t', '.mpg': 'video/mpeg', '.mpeg': 'video/mpeg', '.3gp': 'video/3gpp',
}
NATIVE_EXT = {'.mp4', '.m4v', '.webm', '.mov'}          # браузер телефону грає напряму
OK_VCODEC = {'h264', 'hevc', 'vp8', 'vp9', 'av1'}
OK_ACODEC = {'aac', 'mp3', 'opus', 'vorbis', 'flac', None}
SKIP_DIRS = {'$recycle.bin', 'system volume information', '.vidbox'}
JUNK_RE = re.compile(
    r'\b(2160p|1080p|720p|480p|4k|uhd|x26[45]|h[ .]?26[45]|hevc|web[ -]?dl|web[ -]?rip|'
    r'blu[ -]?ray|bdrip|brrip|hdrip|dvdrip|hdtv|aac|ac3|dts|hdr|10bit|8bit|remux)\b', re.I)
ID_RE = re.compile(r'[0-9a-f]{16}')
HALF_LIFE_DAYS = 90            # наскільки швидко «забуваються» старі перегляди в рейтингу
NOWIN = 0x08000000 if os.name == 'nt' else 0   # без чорних вікон ffmpeg на Windows
BG_PRIO = (0x00004000 | NOWIN) if os.name == 'nt' else 0   # фонова робота не гальмує ПК
SPRITE_N, FRAME_W, FRAME_H = 20, 320, 180      # нарізка: 20 кадрів 320×180 в одній смужці


class Cfg:
    roots = []
    data = ''
    web = ''
    ffmpeg = None
    ffprobe = None
    port = 8800
    cfg = {}          # налаштування з config.json (див. розділ «налаштування»)
    verbose = False


C = Cfg()
DB = None
MEDIA_EVENT = threading.Event()
SCAN_LOCK = threading.Lock()
STATS_LOCK = threading.Lock()
WEEK_LOCK = threading.Lock()
PREP_LOCK = threading.Lock()
PREP = {}
PREP_Q = queue.Queue()


# ───────────────────────────── база даних ─────────────────────────────

SCHEMA = '''
CREATE TABLE IF NOT EXISTS videos(
  id TEXT PRIMARY KEY, path TEXT, root TEXT, folder TEXT, title TEXT, ext TEXT,
  size INTEGER, mtime REAL, added REAL, first_seen REAL,
  duration REAL, width INTEGER, height INTEGER, vcodec TEXT, acodec TEXT,
  probed INTEGER DEFAULT 0, thumb INTEGER DEFAULT 0, missing INTEGER DEFAULT 0,
  vote INTEGER DEFAULT 0, position REAL DEFAULT 0, position_at REAL DEFAULT 0,
  sprite INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, video_id TEXT, started REAL, last REAL,
  start_pos REAL, max_pos REAL, watched REAL, duration REAL, ended INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_sessions_video ON sessions(video_id);
CREATE TABLE IF NOT EXISTS weekly(week TEXT PRIMARY KEY, created REAL, data TEXT);
'''


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.con = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.con.row_factory = sqlite3.Row
        with self.lock:
            self.con.execute('PRAGMA journal_mode=WAL')
            self.con.executescript(SCHEMA)
            cols = {r[1] for r in self.con.execute('PRAGMA table_info(videos)')}
            if 'sprite' not in cols:   # база від версії 0.1
                self.con.execute('ALTER TABLE videos ADD COLUMN sprite INTEGER DEFAULT 0')
                self.con.commit()
        self.version = 0

    def q(self, sql, a=()):
        with self.lock:
            return self.con.execute(sql, a).fetchall()

    def one(self, sql, a=()):
        with self.lock:
            return self.con.execute(sql, a).fetchone()

    def x(self, sql, a=()):
        with self.lock:
            cur = self.con.execute(sql, a)
            self.con.commit()
            return cur.rowcount

    def many(self, sql, rows):
        with self.lock:
            self.con.executemany(sql, rows)
            self.con.commit()

    def bump(self):
        with self.lock:
            self.version += 1


# ───────────────────────────── сканування папок ─────────────────────────────

def make_id(path):
    key = os.path.normcase(os.path.abspath(path)).encode('utf-8', 'surrogateescape')
    return hashlib.sha1(key).hexdigest()[:16]


def clean_title(stem):
    t = stem
    t = re.sub(r'[._]+', ' ', t) if ' ' not in t else t.replace('_', ' ')
    t = JUNK_RE.sub(' ', t)
    t = re.sub(r'[\[(]\s*[\])]', ' ', t)
    t = re.sub(r'\s{2,}', ' ', t).strip(' -.')
    return t or stem


def thumb_path(vid):
    return os.path.join(C.data, 'thumbs', vid + '.jpg')


def prepared_path(vid):
    return os.path.join(C.data, 'prepared', vid + '.mp4')


def sprite_path(vid):
    return os.path.join(C.data, 'sprites', vid + '.jpg')


def scan():
    """Обходить папки, оновлює список відео. Повертає (усього, нових)."""
    with SCAN_LOCK:
        existing = {r['id']: (r['size'], r['mtime'])
                    for r in DB.q('SELECT id, size, mtime FROM videos')}
        seen, rows, changed = set(), [], []
        now = time.time()
        for root in C.roots:
            label = os.path.basename(os.path.normpath(root)) or root.rstrip('\\/:') or root
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(d for d in dirnames
                                     if not d.startswith('.') and d.lower() not in SKIP_DIRS)
                for fn in filenames:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in VIDEO_EXT or fn.startswith('._'):
                        continue
                    full = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    if st.st_size < 64 * 1024:
                        continue
                    vid = make_id(full)
                    if vid in seen:
                        continue
                    seen.add(vid)
                    rel = os.path.relpath(dirpath, root)
                    folder = label if rel == '.' else label + '/' + rel.replace(os.sep, '/')
                    bt = getattr(st, 'st_birthtime', None)
                    if bt is None and os.name == 'nt':
                        bt = st.st_ctime
                    added = max(st.st_mtime, bt or 0)
                    old = existing.get(vid)
                    if old and (old[0] != st.st_size or abs((old[1] or 0) - st.st_mtime) > 2):
                        changed.append(vid)
                    rows.append((vid, full, root, folder, clean_title(os.path.splitext(fn)[0]),
                                 ext, st.st_size, st.st_mtime, added, now))
        DB.many('''INSERT INTO videos(id,path,root,folder,title,ext,size,mtime,added,first_seen)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET path=excluded.path, root=excluded.root,
                     folder=excluded.folder, title=excluded.title, ext=excluded.ext,
                     size=excluded.size, mtime=excluded.mtime, added=excluded.added, missing=0''',
                rows)
        if changed:   # файл замінили — прев'ю і конвертовану копію треба перегенерувати
            DB.many('UPDATE videos SET probed=0, thumb=0, sprite=0, duration=NULL WHERE id=?',
                    [(v,) for v in changed])
            for v in changed:
                shutil.rmtree(os.path.join(C.data, 'frames', v), ignore_errors=True)
                for p in (thumb_path(v), prepared_path(v), sprite_path(v)):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        gone = [(v,) for v in existing if v not in seen]
        if gone:
            DB.many('UPDATE videos SET missing=1 WHERE id=?', gone)
        DB.bump()
        MEDIA_EVENT.set()
        return len(seen), len([r for r in rows if r[0] not in existing])


def rescan_loop():
    last = time.time()
    while True:
        time.sleep(20)
        if time.time() - last >= C.cfg.get('rescan_min', 10) * 60:
            last = time.time()
            try:
                scan()
            except Exception:
                traceback.print_exc()


# ───────────────────────────── ffmpeg: інфо, прев'ю, конвертація ─────────────────────────────

def run(cmd, timeout):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, creationflags=NOWIN)


def probe(path):
    if not C.ffprobe:
        return {}
    try:
        out = run([C.ffprobe, '-v', 'error', '-print_format', 'json',
                   '-show_format', '-show_streams', path], 60)
        j = json.loads(out.stdout.decode('utf-8', 'replace') or '{}')
    except Exception:
        return {}
    info = {}
    try:
        info['duration'] = float(j.get('format', {}).get('duration'))
    except (TypeError, ValueError):
        pass
    for s in j.get('streams', []):
        if s.get('codec_type') == 'video' and 'vcodec' not in info \
                and not s.get('disposition', {}).get('attached_pic'):
            info.update(vcodec=s.get('codec_name'), width=s.get('width'), height=s.get('height'))
        elif s.get('codec_type') == 'audio' and 'acodec' not in info:
            info['acodec'] = s.get('codec_name')
    return info


def make_thumb(path, duration, out):
    if not C.ffmpeg:
        return False
    t = max(0.0, min(duration * 0.15, 300.0)) if duration and duration > 3 else 0.0
    tmp = out + '.tmp.jpg'
    for ss in (t, 0.0):
        try:
            run([C.ffmpeg, '-v', 'error', '-y', '-ss', '%.2f' % ss, '-i', path,
                 '-frames:v', '1', '-vf', 'scale=480:-2', '-q:v', '4', tmp], 90)
        except Exception:
            pass
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, out)
            return True
        if ss == 0.0:
            break
    return False


def sprite_times(duration):
    """Моменти, з яких беруться 20 кадрів: рівномірно від 3% до 97% тривалості."""
    return [duration * (0.03 + 0.94 * i / (SPRITE_N - 1)) for i in range(SPRITE_N)]


def make_sprite(path, duration, out, background=True):
    """Нарізка кадрів: 20 кадрів → одна смужка JPEG (для наведення і вікна з інфою)."""
    if not C.ffmpeg or not duration or duration <= 0:
        return False
    tmpdir = out + '.d'
    shutil.rmtree(tmpdir, ignore_errors=True)
    os.makedirs(tmpdir)
    flags = BG_PRIO if background else NOWIN
    vf = ('scale=%d:%d:force_original_aspect_ratio=decrease,'
          'pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1' % (FRAME_W, FRAME_H, FRAME_W, FRAME_H))

    def fpath(i):
        return os.path.join(tmpdir, 'f%02d.jpg' % i)

    def grab(item):
        i, t = item
        try:
            subprocess.run([C.ffmpeg, '-v', 'error', '-y', '-ss', '%.2f' % t, '-i', path,
                            '-frames:v', '1', '-an', '-sn', '-vf', vf, '-q:v', '5', fpath(i)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=60, creationflags=flags)
        except Exception:
            pass
        return os.path.exists(fpath(i)) and os.path.getsize(fpath(i)) > 0

    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            ok = list(ex.map(grab, enumerate(sprite_times(duration))))
        if sum(ok) < SPRITE_N // 2:
            return False
        last = ok.index(True)
        for i in range(SPRITE_N):          # дірки (не вдалося взяти кадр) → сусідній кадр
            if ok[i]:
                last = i
            else:
                shutil.copyfile(fpath(last), fpath(i))
        tmp = out + '.tmp.jpg'
        subprocess.run([C.ffmpeg, '-v', 'error', '-y', '-framerate', '1',
                        '-i', os.path.join(tmpdir, 'f%02d.jpg'), '-vf', 'tile=%dx1' % SPRITE_N,
                        '-frames:v', '1', '-q:v', '5', tmp],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=60, creationflags=flags)
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, out)
            return True
        return False
    except Exception:
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


SPRITE_LOCKS = {}
SPRITE_LOCKS_LOCK = threading.Lock()
_frames_made = [0]


def frame_path(vid, i):
    return os.path.join(C.data, 'frames', vid, '%02d.jpg' % i)


def ensure_frame(vid, i):
    """Великий кадр (до 1280 px) для героя і вікна з інфою; робиться при першому запиті."""
    p = frame_path(vid, i)
    if os.path.exists(p):
        return p
    with SPRITE_LOCKS_LOCK:
        lk = SPRITE_LOCKS.setdefault((vid, i), threading.Lock())
    with lk:
        if os.path.exists(p):
            return p
        r = DB.one('SELECT path, duration FROM videos WHERE id=?', (vid,))
        if not r or not r['duration'] or not C.ffmpeg:
            return None
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp.jpg'
        try:
            subprocess.run([C.ffmpeg, '-v', 'error', '-y', '-ss', '%.2f' % sprite_times(r['duration'])[i],
                            '-i', r['path'], '-frames:v', '1', '-an', '-sn',
                            '-vf', "scale=w='min(1280,iw)':h=-2", '-q:v', '4', tmp],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, creationflags=NOWIN)
        except Exception:
            pass
        if not (os.path.exists(tmp) and os.path.getsize(tmp) > 0):
            return None
        os.replace(tmp, p)
        _frames_made[0] += 1
        if _frames_made[0] % 40 == 0:
            trim_frames()
        return p


def trim_frames():
    root = os.path.join(C.data, 'frames')
    dirs = []
    for n in os.listdir(root):
        d = os.path.join(root, n)
        try:
            files = [os.path.join(d, f) for f in os.listdir(d)]
            dirs.append((max((os.path.getmtime(f) for f in files), default=0), sum(os.path.getsize(f) for f in files), d))
        except OSError:
            pass
    total = sum(x[1] for x in dirs)
    for _, size, d in sorted(dirs):
        if total <= C.cfg.get('frames_cache_gb', 3) * 1024 ** 3:
            break
        shutil.rmtree(d, ignore_errors=True)
        total -= size


def ensure_sprite(vid, background=True):
    """Повертає версію нарізки (>0), -1 якщо не вийшло, 0 якщо неможливо (немає ffmpeg)."""
    with SPRITE_LOCKS_LOCK:
        lk = SPRITE_LOCKS.setdefault(vid, threading.Lock())
    with lk:
        r = DB.one('SELECT path, duration, sprite FROM videos WHERE id=?', (vid,))
        if not r:
            return 0
        if r['sprite'] and (r['sprite'] < 0 or os.path.exists(sprite_path(vid))):
            return r['sprite']
        if not C.ffmpeg:
            return 0
        dur = r['duration'] or probe(r['path']).get('duration')
        val = int(time.time()) if make_sprite(r['path'], dur, sprite_path(vid), background) else -1
        DB.x('UPDATE videos SET sprite=? WHERE id=?', (val, vid))
        DB.bump()
        return val


def media_worker():
    """У фоні: тривалість, кодеки, обкладинки, потім нарізки кадрів для всіх відео."""
    announced = False
    while True:
        MEDIA_EVENT.wait()
        MEDIA_EVENT.clear()
        if not C.ffprobe and not C.ffmpeg:
            continue
        while True:
            rows = DB.q('SELECT id, path, duration FROM videos '
                        'WHERE missing=0 AND probed=0 ORDER BY added DESC LIMIT 10')
            if not rows:
                if not C.ffmpeg or not C.cfg.get('sprites', True):
                    break
                todo = DB.one('SELECT COUNT(*) AS n FROM videos WHERE missing=0 AND sprite=0 '
                              'AND duration > 0')['n']
                if not todo:
                    if announced:
                        print('  ✔ Нарізки кадрів готові для всіх відео')
                        announced = False
                    break
                if not announced:
                    print('  … Готую нарізки кадрів у фоні: %d відео (ПК не гальмуватиме)' % todo)
                    announced = True
                for r in DB.q('SELECT id FROM videos WHERE missing=0 AND sprite=0 AND duration > 0 '
                              'ORDER BY added DESC LIMIT 3'):
                    ensure_sprite(r['id'])
                continue
            for r in rows:
                try:
                    info = probe(r['path'])
                    dur = info.get('duration') or r['duration']
                    th = int(time.time()) if make_thumb(r['path'], dur, thumb_path(r['id'])) else 0
                    DB.x('''UPDATE videos SET probed=1, duration=COALESCE(?, duration),
                            width=?, height=?, vcodec=?, acodec=?,
                            thumb=CASE WHEN ?>0 THEN ? ELSE thumb END WHERE id=?''',
                         (info.get('duration'), info.get('width'), info.get('height'),
                          info.get('vcodec'), info.get('acodec'), th, th, r['id']))
                except Exception:
                    traceback.print_exc()
                    DB.x('UPDATE videos SET probed=1 WHERE id=?', (r['id'],))
            DB.bump()


def needs_prepare(r):
    if r['ext'] not in NATIVE_EXT:
        return True
    if r['vcodec'] and r['vcodec'] not in OK_VCODEC:
        return True
    if r['acodec'] and r['acodec'] not in OK_ACODEC:
        return True
    return False


def prepare_status(vid):
    if os.path.exists(prepared_path(vid)):
        return {'state': 'ready', 'progress': 1.0}
    with PREP_LOCK:
        return dict(PREP.get(vid) or {'state': 'none', 'progress': 0.0})


def request_prepare(vid):
    if os.path.exists(prepared_path(vid)):
        return {'state': 'ready', 'progress': 1.0}
    if not C.ffmpeg:
        return {'state': 'error', 'progress': 0.0, 'error': 'ffmpeg не знайдено'}
    with PREP_LOCK:
        st = PREP.get(vid)
        if st and st['state'] in ('queued', 'working'):
            return dict(st)
        PREP[vid] = {'state': 'queued', 'progress': 0.0}
    PREP_Q.put(vid)
    return {'state': 'queued', 'progress': 0.0}


def prep_worker():
    while True:
        vid = PREP_Q.get()
        with PREP_LOCK:
            st = PREP[vid]
            st['state'] = 'working'
        try:
            convert(vid, st)
            with PREP_LOCK:
                st.update(state='ready', progress=1.0)
        except Exception as e:
            with PREP_LOCK:
                st.update(state='error', error=str(e)[-300:])
        DB.bump()


def convert(vid, st):
    """Робить MP4-копію, яку відкриє будь-який телефон. H.264/HEVC — без перекодування."""
    r = DB.one('SELECT * FROM videos WHERE id=?', (vid,))
    if not r:
        raise RuntimeError('відео не знайдено')
    info = {'vcodec': r['vcodec'], 'acodec': r['acodec'], 'duration': r['duration']}
    if not r['probed']:
        info.update(probe(r['path']))
    vc, ac = info.get('vcodec'), info.get('acodec')
    if vc in ('h264', 'hevc'):
        v = ['-c:v', 'copy'] + (['-tag:v', 'hvc1'] if vc == 'hevc' else [])
    else:
        v = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p']
    a = ['-c:a', 'copy'] if ac in ('aac', 'mp3') else ['-c:a', 'aac', '-b:a', '192k', '-ac', '2']
    out = prepared_path(vid)
    tmp = out[:-4] + '.part.mp4'
    cmd = [C.ffmpeg, '-hide_banner', '-v', 'error', '-y', '-fflags', '+genpts', '-i', r['path'],
           '-map', '0:v:0', '-map', '0:a:0?', '-sn', '-dn', *v, *a,
           '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', tmp]
    dur = info.get('duration') or 0
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
    err = []
    t = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
    t.start()
    for raw in p.stdout:
        line = raw.decode('utf-8', 'replace').strip()
        if line.startswith('out_time_us=') and dur:
            try:
                with PREP_LOCK:
                    st['progress'] = max(0.0, min(0.99, int(line[12:]) / 1e6 / dur))
            except ValueError:
                pass
    rc = p.wait()
    t.join(5)
    if rc != 0 or not os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
        msg = (err[0] if err else b'').decode('utf-8', 'replace').strip()
        raise RuntimeError(msg or 'ffmpeg завершився з помилкою %s' % rc)
    os.replace(tmp, out)
    trim_cache(keep=out)


def trim_cache(keep=None):
    d = os.path.join(C.data, 'prepared')
    files = []
    for n in os.listdir(d):
        p = os.path.join(d, n)
        if n.endswith('.mp4') and not n.endswith('.part.mp4'):
            try:
                s = os.stat(p)
                files.append((s.st_mtime, s.st_size, p))
            except OSError:
                pass
    total = sum(f[1] for f in files)
    for _, size, p in sorted(files):
        if total <= C.cfg.get('cache_gb', 30) * 1024 ** 3:
            break
        if p == keep:
            continue
        try:
            os.remove(p)
            total -= size
        except OSError:
            pass


# ───────────────────────────── рейтинг ─────────────────────────────
#
# Для кожного відео сесії перегляду склеюються у «перегляди» (якщо продовжив з місця —
# це той самий перегляд). Далі:
#   досмотр     = (сума часток переглянутого + 1) / (кількість переглядів + 2)   ← згладжування
#   популярність = 1 − e^(−E/2.5), де E = Σ (0.15 + 0.85·частка) · ½^(днів_тому / 90)
#   рейтинг     = 100 · (0.45·досмотр + 0.40·популярність + 0.15·(лайк+1)/2)
# Не бачене відео має ~30, добре і часто дивлене — 80+, кинуте на початку — нижче 30.

_stats = {'ver': -1, 'data': {}, 'week_sec': 0.0}


def stats():
    with STATS_LOCK:
        if _stats['ver'] == DB.version:
            return _stats
        ver = DB.version
        vids = {r['id']: r for r in DB.q('SELECT id, duration, vote FROM videos')}
        rows = DB.q('SELECT video_id, started, last, start_pos, watched, duration FROM sessions '
                    'WHERE watched >= 5 ORDER BY video_id, started')
        now = time.time()
        week_ago = now - 7 * 86400
        per, week_total = {}, 0.0
        for s in rows:
            v = vids.get(s['video_id'])
            dur = (v['duration'] if v is not None and v['duration'] else 0) or s['duration'] or 0
            if dur <= 0:
                continue
            frac = min(1.0, s['watched'] / dur)
            d = per.setdefault(s['video_id'], {'views': [], 'last': 0.0, 'week_sec': 0.0})
            vs = d['views']
            resumed = (s['start_pos'] or 0) > 0.05 * dur
            if vs and resumed and s['started'] - vs[-1][0] < 14 * 86400 and vs[-1][1] < 0.98:
                vs[-1][1] = min(1.0, vs[-1][1] + frac)
            else:
                vs.append([s['started'], frac])
            d['last'] = max(d['last'], s['last'] or 0)
            if (s['last'] or 0) >= week_ago:
                d['week_sec'] += s['watched']
                week_total += s['watched']
        out = {}
        for vid, v in vids.items():
            d = per.get(vid)
            vote = v['vote'] or 0
            if d and d['views']:
                views = d['views']
                n = len(views)
                sumf = sum(f for _, f in views)
                eng = sum((0.15 + 0.85 * f) * 0.5 ** (max(0.0, now - t) / 86400 / HALF_LIFE_DAYS)
                          for t, f in views)
                completion = (sumf + 1.0) / (n + 2.0)
                pop = 1 - math.exp(-eng / 2.5)
                avg = sumf / n
            else:
                n, completion, pop, avg = 0, 0.5, 0.0, None
            score = 100 * (0.45 * completion + 0.40 * pop + 0.15 * (vote + 1) / 2)
            out[vid] = {'score': round(score, 1), 'views': n, 'cmp': round(completion, 3),
                        'pop': round(pop, 3), 'avg': round(avg, 3) if avg is not None else None,
                        'last': d['last'] if d else 0, 'week_sec': round(d['week_sec']) if d else 0}
        _stats.update(ver=ver, data=out, week_sec=week_total)
        return _stats


# ───────────────────────────── підбірка тижня ─────────────────────────────

def iso_week(ts=None):
    d = datetime.date.fromtimestamp(ts or time.time())
    y, w, wd = d.isocalendar()[:3]
    start = d - datetime.timedelta(days=wd - 1)
    return '%d-W%02d' % (y, w), start, start + datetime.timedelta(days=6)


def wsample(rng, items, weights, k):
    items, weights, out = list(items), [max(0.0, w) for w in weights], []
    while items and len(out) < k:
        total = sum(weights)
        if total <= 0:
            break
        r, acc, pick = rng.random() * total, 0.0, len(items) - 1
        for i, w in enumerate(weights):
            acc += w
            if acc >= r:
                pick = i
                break
        out.append(items.pop(pick))
        weights.pop(pick)
    return out


WEEK_TEXT = {
    'hits': ('Хіти тижня', 'Що ти найбільше дивився за останні 7 днів'),
    'gems': ('Варто передивитись', 'Високий рейтинг, але давно не вмикав'),
    'unseen': ('Ще не бачив', 'Випадкові відео, до яких ти ще не дійшов'),
}


def build_week(key, start, end, n):
    rng = random.Random('%s#%d' % (key, n))
    st = stats()['data']
    rows = DB.q('SELECT id, added, duration FROM videos WHERE missing=0 AND vote >= 0')
    now = time.time()
    used = set()
    blank = {'score': 30, 'views': 0, 'last': 0, 'week_sec': 0}

    def s(i):
        return st.get(i, blank)

    def take(ids, k):
        res = [i for i in ids if i not in used][:k]
        used.update(res)
        return res

    hits = sorted((r['id'] for r in rows
                   if s(r['id'])['week_sec'] >= min(30, 0.6 * (r['duration'] or 30))),
                  key=lambda i: -s(i)['week_sec'])
    gem_c = [r['id'] for r in rows if s(r['id'])['views'] and s(r['id'])['score'] >= 55
             and now - s(r['id'])['last'] > 21 * 86400]
    gems_pool = wsample(rng, gem_c, [s(i)['score'] ** 2 for i in gem_c], 7)
    un = [r for r in rows if not s(r['id'])['views']]
    un_w = [1 + 3 * math.exp(-max(0.0, now - (r['added'] or now)) / 86400 / 30) for r in un]
    unseen_pool = wsample(rng, [r['id'] for r in un], un_w, 9)

    hero = (hits[:1] or gems_pool[:1] or unseen_pool[:1] or [None])[0]
    if hero:
        used.add(hero)
    sections = []
    for k, ids in (('hits', take(hits, 8)), ('gems', take(gems_pool, 6)), ('unseen', take(unseen_pool, 8))):
        if ids:
            sections.append({'key': k, 'ids': ids})
    return {'week': key, 'start': start.isoformat(), 'end': end.isoformat(), 'n': n,
            'created': now, 'hero': hero, 'sections': sections}


def get_week(force=False):
    key, start, end = iso_week()
    with WEEK_LOCK:
        row = DB.one('SELECT data FROM weekly WHERE week=?', (key,))
        data = json.loads(row['data']) if row else None
        if data is None or force or not data.get('hero'):
            n = data['n'] + 1 if data and force else (data['n'] if data else 0)
            data = build_week(key, start, end, n)
            DB.x('INSERT OR REPLACE INTO weekly(week, created, data) VALUES (?,?,?)',
                 (key, time.time(), json.dumps(data, ensure_ascii=False)))
        for sec in data['sections']:
            sec['title'], sec['sub'] = WEEK_TEXT.get(sec['key'], (sec.get('title', ''), sec.get('sub', '')))
        return data


# ───────────────────────────── API-логіка ─────────────────────────────

def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) and x > 0 else 0.0


def library_json():
    st = stats()
    try:
        ready = {n[:-4] for n in os.listdir(os.path.join(C.data, 'prepared'))
                 if n.endswith('.mp4') and not n.endswith('.part.mp4')}
    except OSError:
        ready = set()
    vids, pending, sprites = [], 0, 0
    for r in DB.q('SELECT * FROM videos WHERE missing=0'):
        s = st['data'].get(r['id'], {})
        if not r['probed'] and (C.ffprobe or C.ffmpeg):
            pending += 1
        if C.ffmpeg and not r['sprite']:
            sprites += 1
        vids.append({
            'id': r['id'], 'title': r['title'], 'folder': r['folder'], 'ext': r['ext'][1:],
            'size': r['size'], 'added': r['added'], 'dur': r['duration'],
            'w': r['width'], 'h': r['height'], 'thumb': r['thumb'],
            'prep': needs_prepare(r), 'ready': r['id'] in ready, 'vote': r['vote'],
            'pos': r['position'], 'posAt': r['position_at'],
            'score': s.get('score', 30), 'views': s.get('views', 0), 'avg': s.get('avg'),
            'cmp': s.get('cmp', 0.5), 'pop': s.get('pop', 0.0),
            'last': s.get('last', 0), 'weekSec': s.get('week_sec', 0),
            'sprite': r['sprite'] or 0, 'file': os.path.basename(r['path']),
            'vc': r['vcodec'], 'ac': r['acodec']})
    folders = sorted({v['folder'] for v in vids}, key=str.lower)
    return {'videos': vids, 'folders': folders, 'ffmpeg': bool(C.ffmpeg), 'pending': pending,
            'spritesPending': sprites if C.cfg.get('sprites', True) else 0, 'spriteN': SPRITE_N,
            'weekSec': round(st['week_sec']),
            'cfg': {k: C.cfg[k] for k in ('autoplay_next', 'next_delay', 'resume', 'ui', 'theme')}}


def on_ping(d):
    vid, sid = str(d.get('id', '')), str(d.get('sid', ''))[:40]
    if not ID_RE.fullmatch(vid) or not sid:
        return {'ok': False}
    pos, dur, watched, start = fnum(d.get('pos')), fnum(d.get('dur')), fnum(d.get('watched')), fnum(d.get('start'))
    ended = 1 if d.get('ended') else 0
    now = time.time()
    with DB.lock:
        r = DB.one('SELECT duration FROM videos WHERE id=?', (vid,))
        if not r:
            return {'ok': False}
        vdur = r['duration'] or dur
        if not r['duration'] and dur > 0:
            DB.x('UPDATE videos SET duration=? WHERE id=?', (dur, vid))
        if DB.one('SELECT 1 FROM sessions WHERE id=?', (sid,)):
            DB.x('''UPDATE sessions SET last=?, max_pos=MAX(max_pos, ?), watched=MAX(watched, ?),
                    ended=MAX(ended, ?) WHERE id=?''', (now, pos, watched, ended, sid))
        else:
            DB.x('''INSERT INTO sessions(id, video_id, started, last, start_pos, max_pos, watched,
                    duration, ended) VALUES (?,?,?,?,?,?,?,?,?)''',
                 (sid, vid, now, now, start, pos, watched, vdur, ended))
        newpos = 0.0 if ended or (vdur and pos >= vdur * 0.95) else pos
        DB.x('UPDATE videos SET position=?, position_at=? WHERE id=?', (newpos, now, vid))
    DB.bump()
    return {'ok': True}


def video_stats(vid):
    s = stats()['data'].get(vid, {})
    return {'score': s.get('score', 30), 'views': s.get('views', 0), 'avg': s.get('avg'),
            'cmp': s.get('cmp', 0.5), 'pop': s.get('pop', 0.0), 'last': s.get('last', 0)}


# ───────────────────────────── налаштування (config.json на ПК) ─────────────────────────────
#
# Усе, що змінюєш на сторінці «Налаштування», одразу записується в config.json у папці даних
# і підхоплюється при наступному запуску.

DEFAULTS = {
    'folders': [], 'port': 8800, 'open_browser': True, 'rescan_min': 10,
    'cache_gb': 30, 'frames_cache_gb': 3, 'sprites': True,
    'autoplay_next': True, 'next_delay': 8, 'resume': True,
    'ui': {'sort': 'score', 'dir': 'desc', 'group': 'all'},
    'theme': 'cinema',
    'password_hash': '', 'secret': '',
}
THEMES = {'cinema', 'nord', 'sweet', 'exodia', 'projector'}
STARTED = time.time()
_ffmpeg_ver = []
SORT_KEYS = {'score', 'added', 'name', 'size', 'dur', 'res', 'views', 'last', 'folder', 'random'}
CFG_LOCK = threading.RLock()


def cfg_path():
    return os.path.join(C.data, 'config.json')


def load_config():
    try:
        with open(cfg_path(), encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}
    cfg = json.loads(json.dumps(DEFAULTS))
    for k, v in raw.items():
        if k == 'ui' and isinstance(v, dict):
            cfg['ui'].update(v)
        elif k in cfg:
            cfg[k] = v
    cfg['secret'] = cfg['secret'] or secrets.token_hex(16)
    return cfg


def save_config():
    with CFG_LOCK:
        tmp = cfg_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(C.cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, cfg_path())


def pw_hash(pw):
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), C.cfg['secret'].encode(), 120000).hex()


def auth_token():
    h = C.cfg.get('password_hash')
    return hmac.new(C.cfg['secret'].encode(), h.encode(), hashlib.sha256).hexdigest() if h else ''


def check_folders(folders):
    """Перевіряє список папок. Повертає (список, None) або (None, текст помилки)."""
    out = []
    for f in folders:
        f = str(f).strip().strip('"')
        if not f:
            continue
        p = os.path.abspath(os.path.expanduser(f))
        if not os.path.isdir(p):
            return None, 'Папку не знайдено: %s' % f
        out.append(p)
    if not out:
        return None, 'Має лишитися хоча б одна папка з відео'
    norm = [os.path.normcase(x).rstrip('\\/') for x in out]
    for i, a in enumerate(norm):
        for j, b in enumerate(norm):
            if i < j and a == b:
                return None, 'Папка «%s» вже додана' % out[i]
            if i != j and a.startswith(b + os.sep):
                return None, 'Папка «%s» вже входить у «%s»' % (out[i], out[j])
    return out, None


def apply_settings(d):
    changed_folders = False
    with CFG_LOCK:
        cfg = C.cfg

        def num(k, lo, hi, cast=float):
            if k in d:
                try:
                    cfg[k] = max(lo, min(hi, cast(d[k])))
                except (TypeError, ValueError):
                    pass
        for k in ('autoplay_next', 'resume', 'sprites', 'open_browser'):
            if k in d:
                cfg[k] = bool(d[k])
        if d.get('theme') in THEMES:
            cfg['theme'] = d['theme']
        num('next_delay', 3, 60, int)
        num('rescan_min', 1, 1440, int)
        num('port', 1024, 65535, int)
        num('cache_gb', 1, 100000)
        num('frames_cache_gb', 0.5, 10000)
        if isinstance(d.get('ui'), dict):
            u = d['ui']
            if u.get('sort') in SORT_KEYS:
                cfg['ui']['sort'] = u['sort']
            if u.get('dir') in ('asc', 'desc'):
                cfg['ui']['dir'] = u['dir']
            if u.get('group') in ('all', 'folders'):
                cfg['ui']['group'] = u['group']
        if 'folders' in d:
            folders, err = check_folders(d['folders'] if isinstance(d['folders'], list) else [])
            if err:
                return {'ok': False, 'error': err}
            if folders != cfg['folders']:
                cfg['folders'] = folders
                C.roots = folders
                changed_folders = True
        save_config()
    if changed_folders:
        threading.Thread(target=scan, daemon=True).start()
    if d.get('sprites'):
        MEDIA_EVENT.set()
    if 'cache_gb' in d:
        threading.Thread(target=trim_cache, daemon=True).start()
    if 'frames_cache_gb' in d:
        threading.Thread(target=trim_frames, daemon=True).start()
    return {'ok': True, 'scanning': changed_folders}


def dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def orphan_ids():
    """Відео, яких більше немає в папках, але їхні обкладинки/нарізки/копії ще лежать у кеші."""
    alive = {r['id'] for r in DB.q('SELECT id FROM videos WHERE missing=0')}
    out = set()
    for sub in ('thumbs', 'sprites', 'prepared', 'frames'):
        try:
            names = os.listdir(os.path.join(C.data, sub))
        except OSError:
            continue
        for n in names:
            vid = n.split('.')[0]
            if ID_RE.fullmatch(vid) and vid not in alive:
                out.add(vid)
    return out


def clear_cache(what):
    if what == 'orphans':
        ids = orphan_ids()
        for vid in ids:
            shutil.rmtree(os.path.join(C.data, 'frames', vid), ignore_errors=True)
            for p in (thumb_path(vid), sprite_path(vid), prepared_path(vid)):
                try:
                    os.remove(p)
                except OSError:
                    pass
        DB.many('UPDATE videos SET thumb=0, sprite=0, probed=0 WHERE id=?', [(v,) for v in ids])
    elif what == 'frames':
        root = os.path.join(C.data, 'frames')
        for n in os.listdir(root):
            shutil.rmtree(os.path.join(root, n), ignore_errors=True)
    elif what == 'prepared':
        root = os.path.join(C.data, 'prepared')
        for n in os.listdir(root):
            if n.endswith('.mp4') and not n.endswith('.part.mp4'):
                try:
                    os.remove(os.path.join(root, n))
                except OSError:
                    pass
        with PREP_LOCK:
            for k in [k for k, v in PREP.items() if v.get('state') == 'ready']:
                del PREP[k]
    else:
        return {'ok': False}
    DB.bump()
    return {'ok': True}


def settings_json():
    cfg = C.cfg
    counts = {os.path.normcase(r['root'] or ''): r['n']
              for r in DB.q('SELECT root, COUNT(*) AS n FROM videos WHERE missing=0 GROUP BY root')}
    out = {k: cfg[k] for k in DEFAULTS if k not in ('password_hash', 'secret', 'folders')}
    out.update(
        folders=[{'path': f, 'count': counts.get(os.path.normcase(f), 0), 'exists': os.path.isdir(f)}
                 for f in cfg['folders']],
        caches={k: dir_size(os.path.join(C.data, k)) for k in ('thumbs', 'sprites', 'frames', 'prepared')},
        orphans=len(orphan_ids()), hasPassword=bool(cfg['password_hash']),
        ffmpeg=C.ffmpeg, data=C.data, version=VERSION, portNow=C.port,
        urls=['http://%s:%d' % (ip, C.port) for ip in lan_ips()])
    # для блоку «Про програму» у стилі neofetch
    t = DB.one('SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS size, COALESCE(SUM(duration), 0) AS dur '
               'FROM videos WHERE missing=0')
    out.update(host=socket.gethostname(), uptime=round(time.time() - STARTED),
               totals={'videos': t['n'], 'size': t['size'], 'dur': t['dur']},
               python=platform.python_version(), os='%s %s' % (platform.system(), platform.release()),
               ffmpegVersion=ffmpeg_version())
    return out


def ffmpeg_version():
    if not _ffmpeg_ver:
        v = ''
        if C.ffmpeg:
            try:
                first = run([C.ffmpeg, '-version'], 10).stdout.decode('utf-8', 'replace').splitlines()[0]
                v = first.split(' version ')[1].split(' ')[0] if ' version ' in first else first
            except Exception:
                v = ''
        _ffmpeg_ver.append(v)
    return _ffmpeg_ver[0]


def list_dirs(path):
    """Огляд папок ПК для вибору папки з відео (показує лише папки, не файли)."""
    if not path:
        if os.name == 'nt':
            drives = os.listdrives() if hasattr(os, 'listdrives') else \
                [d + ':\\' for d in string.ascii_uppercase[2:] if os.path.exists(d + ':\\')]
        else:
            drives = ['/']
        home = os.path.expanduser('~')
        quick = [os.path.join(home, n) for n in ('Videos', 'Відео', 'Desktop', 'Downloads')]
        return {'path': '', 'parent': None,
                'dirs': [{'name': d, 'path': d} for d in drives],
                'quick': [{'name': os.path.basename(q), 'path': q} for q in quick if os.path.isdir(q)]}
    path = os.path.abspath(path)
    dirs, videos = [], 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        attrs = getattr(e.stat(follow_symlinks=False), 'st_file_attributes', 0)
                        if e.name.startswith(('.', '$')) or e.name.lower() in SKIP_DIRS or attrs & 2:
                            continue
                        dirs.append({'name': e.name, 'path': e.path})
                    elif os.path.splitext(e.name)[1].lower() in VIDEO_EXT:
                        videos += 1
                except OSError:
                    continue
    except OSError as e:
        return {'path': path, 'parent': os.path.dirname(path), 'dirs': [], 'videos': 0,
                'error': 'Немає доступу до цієї папки (%s)' % e.strerror}
    dirs.sort(key=lambda x: x['name'].lower())
    parent = os.path.dirname(path)
    return {'path': path, 'parent': '' if parent == path else parent, 'dirs': dirs, 'videos': videos}


# ───────────────────────────── іконки (PNG без бібліотек) ─────────────────────────────

_icons = {}


def icon_png(size):
    if size in _icons:
        return _icons[size]
    tri = [(0.39 * size, 0.29 * size), (0.39 * size, 0.71 * size), (0.75 * size, 0.5 * size)]
    edges = []
    for i in range(3):
        (x1, y1), (x2, y2) = tri[i], tri[(i + 1) % 3]
        ln = math.hypot(x2 - x1, y2 - y1)
        edges.append((x1, y1, (x2 - x1) / ln, (y2 - y1) / ln))
    c1, c2 = (34, 44, 63), (15, 20, 32)
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            k = (x + y) / (2.0 * size)
            r, g, b = (int(c1[j] + (c2[j] - c1[j]) * k) for j in range(3))
            # відстань до найближчого ребра трикутника → м'які (згладжені) краї
            inside = min(dy * (x + 0.5 - ex) - dx * (y + 0.5 - ey) for ex, ey, dx, dy in edges)
            a = max(0.0, min(1.0, inside + 0.5))
            raw += bytes((int(r + (242 - r) * a), int(g + (181 - g) * a), int(b + (68 - b) * a), 255))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))
    _icons[size] = png
    return png


MANIFEST = json.dumps({
    'name': APP, 'short_name': APP, 'start_url': '/', 'scope': '/', 'display': 'standalone',
    'background_color': '#0f1420', 'theme_color': '#0f1420',
    'icons': [{'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any maskable'},
              {'src': '/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'}],
}).encode()


# ───────────────────────────── HTTP ─────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = APP + '/' + VERSION
    sys_version = ''

    def log_message(self, fmt, *a):
        if C.verbose:
            sys.stderr.write('%s  %s\n' % (self.address_string(), fmt % a))

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionError, TimeoutError):
            self.close_connection = True

    def do_GET(self):
        self.route('GET')

    def do_HEAD(self):
        self.route('HEAD')

    def do_POST(self):
        self.route('POST')

    # ── допоміжне ──
    def send_bytes(self, data, ctype, status=200, cache='no-cache', extra=None):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', cache)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not self.is_head:
            self.wfile.write(data)

    def send_json(self, obj, status=200, extra=None):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8', 'replace')
        self.send_bytes(data, 'application/json; charset=utf-8', status, 'no-store', extra)

    def send_web(self, path):
        """Файли сайту з папки web/ (index.html, style.css, app.js, шрифти)."""
        rel = 'index.html' if path in ('/', '/index.html') else path.lstrip('/')
        root = os.path.realpath(C.web)
        full = os.path.realpath(os.path.join(root, rel))
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            return self.send_json({'error': 'not found'}, 404)
        ext = os.path.splitext(full)[1].lower()
        ctype = WEB_TYPES.get(ext, 'application/octet-stream')
        cache = 'max-age=31536000, immutable' if ext in ('.woff', '.woff2') else 'no-cache'
        return self.send_file(full, ctype, cache)

    def redirect(self, to, extra=None):
        h = {'Location': to}
        h.update(extra or {})
        self.send_bytes(b'', 'text/plain', 303, extra=h)

    def body(self, limit=65536):
        n = int(self.headers.get('Content-Length') or 0)
        if n > limit:
            self.close_connection = True
            raise ValueError('body too large')
        return self.rfile.read(n) if n else b''

    def json_body(self):
        try:
            return json.loads(self.body().decode('utf-8') or '{}')
        except ValueError:
            return {}

    def authed(self):
        if not C.cfg.get('password_hash'):
            return True
        try:
            c = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
            tok = c['vb'].value if 'vb' in c else ''
        except http.cookies.CookieError:
            tok = ''
        return hmac.compare_digest(tok, auth_token())

    def send_file(self, path, ctype, cache='no-cache'):
        try:
            f = open(path, 'rb')
        except OSError:
            return self.send_json({'error': 'not found'}, 404)
        with f:
            size = os.fstat(f.fileno()).st_size
            start, end, status = 0, size - 1, 200
            rng = self.headers.get('Range')
            if rng:
                m = re.fullmatch(r'\s*bytes=(\d*)-(\d*)\s*', rng.split(',')[0])
                if m and (m.group(1) or m.group(2)):
                    s, e = m.groups()
                    if s == '':
                        start, end = max(0, size - int(e)), size - 1
                    else:
                        start, end = int(s), (min(int(e), size - 1) if e else size - 1)
                    if start >= size or start > end:
                        return self.send_bytes(b'', 'text/plain', 416,
                                               extra={'Content-Range': 'bytes */%d' % size})
                    status = 206
            length = end - start + 1
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(length))
            if status == 206:
                self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
            self.send_header('Cache-Control', cache)
            self.end_headers()
            if self.is_head:
                return
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def video_row(self, vid):
        if not ID_RE.fullmatch(vid):
            return None
        return DB.one('SELECT * FROM videos WHERE id=?', (vid,))

    # ── маршрути ──
    def route(self, method):
        self.is_head = method == 'HEAD'
        try:
            u = urllib.parse.urlsplit(self.path)
            path, qs = u.path, urllib.parse.parse_qs(u.query)
            if method in ('GET', 'HEAD'):
                if path == '/manifest.json':
                    return self.send_bytes(MANIFEST, 'application/manifest+json', cache='max-age=86400')
                if path in ('/icon-192.png', '/icon-512.png', '/favicon.ico'):
                    size = 512 if '512' in path else 192
                    return self.send_bytes(icon_png(size), 'image/png', cache='max-age=86400')
                if path.startswith('/fonts/'):
                    return self.send_web(path)
                if path == '/login':
                    return self.send_bytes(LOGIN_HTML.replace('{err}', '').encode(), 'text/html; charset=utf-8')
            if method == 'POST' and path == '/login':
                form = urllib.parse.parse_qs(self.body().decode('utf-8', 'replace'))
                if C.cfg.get('password_hash') and hmac.compare_digest(pw_hash(form.get('p', [''])[0]),
                                                                      C.cfg['password_hash']):
                    cookie = 'vb=%s; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax' % auth_token()
                    return self.redirect('/', {'Set-Cookie': cookie})
                html = LOGIN_HTML.replace('{err}', '<p class="err">Неправильний пароль</p>')
                return self.send_bytes(html.encode(), 'text/html; charset=utf-8', 401)
            if not self.authed():
                if path.startswith(('/api/', '/stream/', '/thumb/')):
                    return self.send_json({'error': 'auth'}, 401)
                return self.redirect('/login')

            if method in ('GET', 'HEAD'):
                if path == '/api/library':
                    return self.send_json(library_json())
                if path == '/api/week':
                    return self.send_json(get_week())
                m = re.fullmatch(r'/api/prepare/(\w+)', path)
                if m:
                    return self.send_json(prepare_status(m.group(1)))
                m = re.fullmatch(r'/thumb/(\w+)', path)
                if m and ID_RE.fullmatch(m.group(1)):
                    return self.send_file(thumb_path(m.group(1)), 'image/jpeg', 'max-age=604800')
                m = re.fullmatch(r'/frame/([0-9a-f]{16})/(\d{1,2})', path)
                if m and int(m.group(2)) < SPRITE_N:
                    p = ensure_frame(m.group(1), int(m.group(2)))
                    if not p:
                        return self.send_json({'error': 'no frame'}, 404)
                    return self.send_file(p, 'image/jpeg', 'max-age=604800')
                m = re.fullmatch(r'/sprite/(\w+)', path)
                if m and ID_RE.fullmatch(m.group(1)):
                    return self.send_file(sprite_path(m.group(1)), 'image/jpeg', 'max-age=604800')
                m = re.fullmatch(r'/stream/(\w+)', path)
                if m:
                    r = self.video_row(m.group(1))
                    if not r:
                        return self.send_json({'error': 'not found'}, 404)
                    pp = prepared_path(r['id'])
                    if 'raw' not in qs and os.path.exists(pp):
                        try:
                            os.utime(pp)   # для очищення кешу: свіжі не видаляються
                        except OSError:
                            pass
                        return self.send_file(pp, 'video/mp4')
                    return self.send_file(r['path'], VIDEO_EXT.get(r['ext'], 'application/octet-stream'))
                if path == '/api/settings':
                    return self.send_json(settings_json())
                if path == '/api/fs':
                    return self.send_json(list_dirs(qs.get('path', [''])[0]))
                return self.send_web(path)

            if method == 'POST':
                if path == '/api/settings':
                    return self.send_json(apply_settings(self.json_body()))
                if path == '/api/password':
                    pw = str(self.json_body().get('password') or '')
                    with CFG_LOCK:
                        C.cfg['password_hash'] = pw_hash(pw) if pw else ''
                        save_config()
                    extra = {'Set-Cookie': 'vb=%s; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax'
                             % auth_token()} if pw else None
                    return self.send_json({'ok': True, 'hasPassword': bool(pw)}, extra=extra)
                if path == '/api/cache/clear':
                    return self.send_json(clear_cache(self.json_body().get('what')))
                if path == '/api/ping':
                    return self.send_json(on_ping(self.json_body()))
                if path == '/api/vote':
                    d = self.json_body()
                    vid = str(d.get('id', ''))
                    vote = max(-1, min(1, int(d.get('vote') or 0)))
                    if not ID_RE.fullmatch(vid):
                        return self.send_json({'ok': False}, 400)
                    DB.x('UPDATE videos SET vote=? WHERE id=?', (vote, vid))
                    DB.bump()
                    return self.send_json(dict(ok=True, **video_stats(vid)))
                if path == '/api/week/refresh':
                    return self.send_json(get_week(force=True))
                if path == '/api/rescan':
                    total, new = scan()
                    return self.send_json({'ok': True, 'total': total, 'new': new})
                m = re.fullmatch(r'/api/prepare/(\w+)', path)
                if m:
                    if not self.video_row(m.group(1)):
                        return self.send_json({'error': 'not found'}, 404)
                    return self.send_json(request_prepare(m.group(1)))
                m = re.fullmatch(r'/api/sprite/(\w+)', path)
                if m:   # нарізку просять зараз (відкрили інфо) → робимо без черги
                    if not self.video_row(m.group(1)):
                        return self.send_json({'error': 'not found'}, 404)
                    return self.send_json({'sprite': ensure_sprite(m.group(1), background=False)})
                m = re.fullmatch(r'/api/thumb/(\w+)', path)
                if m:
                    r = self.video_row(m.group(1))
                    data = self.body(3 * 1024 * 1024)
                    if not r or not data.startswith(b'\xff\xd8'):
                        return self.send_json({'ok': False}, 400)
                    if r['thumb']:
                        return self.send_json({'ok': True, 'thumb': r['thumb']})
                    with open(thumb_path(r['id']), 'wb') as f:
                        f.write(data)
                    th = int(time.time())
                    DB.x('UPDATE videos SET thumb=? WHERE id=?', (th, r['id']))
                    DB.bump()
                    return self.send_json({'ok': True, 'thumb': th})
                return self.send_json({'error': 'not found'}, 404)
            return self.send_json({'error': 'method'}, 405)
        except (ConnectionError, TimeoutError):
            self.close_connection = True
        except Exception:
            traceback.print_exc()
            self.close_connection = True
            try:
                self.send_json({'error': 'server'}, 500)
            except Exception:
                pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != 'nt'   # на Windows інакше два сервери «сядуть» на один порт


# ───────────────────────────── запуск ─────────────────────────────

def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_tool(name, hint=None):
    exe = name + ('.exe' if os.name == 'nt' else '')
    cands = []
    if hint:
        cands.append(os.path.join(hint, exe) if os.path.isdir(hint) else os.path.join(os.path.dirname(hint), exe))
    here = app_dir()
    cands += [os.path.join(here, exe), os.path.join(here, 'ffmpeg', exe), os.path.join(here, 'ffmpeg', 'bin', exe)]
    w = shutil.which(name)
    if w:
        cands.append(w)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))   # пакет не відправляється, просто дізнаємось свій IP
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith('127.'):
                ips.append(ip)
    except OSError:
        pass
    return ips


PS_PICK = (
    "Add-Type -AssemblyName System.Windows.Forms;"
    "$f = New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
    "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
    "$d.Description = 'VidBox: обери папку з відео';"
    "if ($d.ShowDialog($f) -eq 'OK') {"
    " [Console]::OutputEncoding = [Text.Encoding]::UTF8; [Console]::Write($d.SelectedPath) }")


def pick_folder():
    print('Обери папку з відео у вікні, що відкрилось…')
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        p = filedialog.askdirectory(title='VidBox — обери папку з відео')
        root.destroy()
        return p or None
    except Exception:
        pass
    if os.name == 'nt':   # портативний Python без tkinter → стандартний діалог Windows
        try:
            out = subprocess.run(['powershell', '-NoProfile', '-STA', '-Command', PS_PICK],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=600)
            p = out.stdout.decode('utf-8', 'replace').strip()
            if p:
                return p
        except Exception:
            pass
    try:
        p = input('Встав шлях до папки з відео: ').strip().strip('"')
    except EOFError:
        return None
    return p or None


def main():
    global DB
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description='VidBox — домашній відеосервер. Усі налаштування є і на сайті.')
    ap.add_argument('folders', nargs='*', help='папки з відео (замінять збережені)')
    ap.add_argument('--port', type=int, help='порт сайту (типово 8800)')
    ap.add_argument('--host', default='0.0.0.0', help='0.0.0.0 = доступ з усієї домашньої мережі')
    ap.add_argument('--password', help='встановити пароль для входу')
    ap.add_argument('--no-password', action='store_true', help='прибрати пароль (якщо забув)')
    ap.add_argument('--ffmpeg', help='шлях до ffmpeg.exe або папки з ним')
    ap.add_argument('--data', help='де зберігати базу, обкладинки й кеш (типово ~/.vidbox)')
    ap.add_argument('--pick', action='store_true', help='вибрати папку з відео заново')
    ap.add_argument('--no-browser', action='store_true', help='цього разу не відкривати браузер на ПК')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    C.data = os.path.abspath(os.path.expanduser(args.data or os.path.join('~', '.vidbox')))
    for sub in ('thumbs', 'prepared', 'sprites', 'frames'):
        os.makedirs(os.path.join(C.data, sub), exist_ok=True)
    C.web = os.path.join(app_dir(), 'web')
    if not os.path.isfile(os.path.join(C.web, 'index.html')):
        print('Не знайдено папку web з файлами сайту поруч з vidbox.py (%s).' % C.web)
        print('Розпакуй архів VidBox повністю: vidbox.py, start.bat і папка web мають лежати разом.')
        sys.exit(1)

    C.cfg = load_config()
    folders = [os.path.abspath(f) for f in args.folders] if args.folders else list(C.cfg['folders'])
    if args.pick or not folders:
        picked = pick_folder()
        folders = [os.path.abspath(picked)] if picked else []
    for f in folders:
        if not os.path.isdir(f):
            print('⚠ Папку не знайдено (пропускаю):', f)
    folders = [f for f in folders if os.path.isdir(f)]
    if not folders:
        print('Не вибрано жодної папки з відео. Запусти так: python vidbox.py "D:\\Videos"')
        sys.exit(1)
    folders, err = check_folders(folders)
    if err:
        print('⚠', err)
        sys.exit(1)
    C.cfg['folders'] = folders
    if args.port:
        C.cfg['port'] = args.port
    if args.password:
        C.cfg['password_hash'] = pw_hash(args.password)
    if args.no_password:
        C.cfg['password_hash'] = ''
    save_config()

    C.roots = folders
    C.port = int(C.cfg['port'])
    C.ffmpeg = find_tool('ffmpeg', args.ffmpeg)
    C.ffprobe = find_tool('ffprobe', args.ffmpeg or C.ffmpeg)
    C.verbose = args.verbose

    DB = Store(os.path.join(C.data, 'vidbox.db'))
    print('Сканую папки…')
    total, new = scan()
    try:
        httpd = Server((args.host, C.port), Handler)
    except OSError as e:
        print('Не вдалося запустити сайт на порту %d (%s).' % (C.port, e))
        print('Можливо, VidBox уже запущений в іншому вікні. Або запусти з іншим портом: --port %d'
              % (C.port + 1))
        sys.exit(1)

    print()
    print('  %s %s запущено' % (APP, VERSION))
    print('  Папки:        ' + '\n                '.join(folders))
    print('  Відео:        %d' % total)
    print('  На цьому ПК:  http://localhost:%d' % C.port)
    for ip in lan_ips():
        print('  На телефоні:  http://%s:%d   (телефон у тому ж Wi-Fi)' % (ip, C.port))
    if C.ffmpeg:
        print('  ffmpeg:       є — обкладинки, нарізки кадрів і конвертація MKV/AVI увімкнені')
    else:
        print('  ffmpeg:       не знайдено — без нарізок кадрів; MKV/AVI не конвертуються.')
        print('                Поклади ffmpeg.exe і ffprobe.exe поруч з vidbox.py, щоб увімкнути.')
    if C.cfg['password_hash']:
        print('  Пароль:       увімкнено (прибрати: на сайті в Налаштуваннях або --no-password)')
    print('  Налаштування: на сайті, вкладка «Налаштування» (зберігаються в %s)' % cfg_path())
    print('  Ctrl+C — зупинити\n')
    for target in (media_worker, prep_worker, rescan_loop):
        threading.Thread(target=target, daemon=True).start()
    if C.cfg.get('open_browser', True) and not args.no_browser:
        try:
            webbrowser.open('http://localhost:%d' % C.port)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('Зупинено.')


# ───────────────────────────── сторінки ─────────────────────────────

LOGIN_HTML = '''<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
<title>VidBox — вхід</title><style>
@font-face{font-family:'VidBox Serif';src:url(/fonts/vidbox-serif.woff) format('woff');font-weight:400 700}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f1420;color:#ede6d8;
font:16px "Segoe UI",system-ui,-apple-system,Roboto,sans-serif}form{display:flex;flex-direction:column;gap:12px;width:280px}
h1{margin:0 0 10px;font:600 30px 'VidBox Serif',Georgia,serif}input,button{font:inherit;padding:12px 14px;border-radius:10px;border:0}
input{background:#1f2839;color:#ede6d8;outline:none}input:focus{box-shadow:0 0 0 2px #f2b544}
button{background:#f2b544;color:#1c1508;font-weight:600;cursor:pointer}.err{color:#ff8a7a;margin:0;font-size:14px}
</style></head><body><form method="post" action="/login"><h1>VidBox</h1>{err}
<input type="password" name="p" placeholder="Пароль" autofocus aria-label="Пароль"><button>Увійти</button></form></body></html>'''

WEB_TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
             '.js': 'text/javascript; charset=utf-8', '.woff': 'font/woff', '.woff2': 'font/woff2',
             '.png': 'image/png', '.svg': 'image/svg+xml', '.jpg': 'image/jpeg', '.ico': 'image/x-icon'}

if __name__ == '__main__':
    main()
