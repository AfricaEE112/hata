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
import collections
import glob
import io
import urllib.request
import zipfile
import datetime
import hashlib
import html
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
import urllib.error
import urllib.parse
import webbrowser
import zlib
import platform
import string
from concurrent.futures import ThreadPoolExecutor

APP = 'VidBox'
VERSION = '0.6'

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
    anime = ''
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
  sprite INTEGER DEFAULT 0, pixfmt TEXT);
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
            if 'pixfmt' not in cols:   # база до версії 0.5
                self.con.execute('ALTER TABLE videos ADD COLUMN pixfmt TEXT')
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
        for root in list(C.roots) + ([C.anime] if C.anime else []):
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
        moved = relink()
        if moved:
            print('Перенесено історію для %d переміщених відео.' % moved)
        DB.bump()
        MEDIA_EVENT.set()
        return len(seen), len([r for r in rows if r[0] not in existing])


# ───────────────────────────── аніме ─────────────────────────────
# Окрема папка: кожна підпапка — тайтл, файли в ній — серії. Повністю окремо від бібліотеки.

def is_anime(r):
    return bool(C.anime) and r['root'] == C.anime


def nat_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def anime_title(top):
    t = clean_title(re.sub(r'\[[^\]]*\]', ' ', top))   # [SubsPlease], [1080p] тощо
    t = re.sub(r'\b(BD|BluRay|WEB-?DL|WEBRip|HEVC|x26[45]|AV1|10 ?bit|Dual Audio|Batch)\b', ' ', t, flags=re.I)
    return re.sub(r'\s{2,}', ' ', t).strip(' -.') or top


def anime_series():
    if not C.anime:
        return {}
    groups = {}
    for r in DB.q('SELECT * FROM videos WHERE missing=0 AND root=?', (C.anime,)):
        parts = os.path.relpath(r['path'], C.anime).split(os.sep)
        groups.setdefault(parts[0] if len(parts) > 1 else '', []).append(r)
    out = {}
    for top, rows in groups.items():
        rows.sort(key=lambda r: nat_key(os.path.relpath(r['path'], C.anime)))
        out[hashlib.sha1(('anime:' + top).encode('utf-8', 'surrogateescape')).hexdigest()[:12]] = (top, rows)
    return out


def ep_name(r, series):
    """«[SubsPlease] Sousou no Frieren - 10 (1080p)» → (10, '') ; «Episode 5 - Назва» → (5, 'Назва')."""
    t = clean_title(re.sub(r'\[[^\]]*\]', ' ', os.path.splitext(os.path.basename(r['path']))[0]))
    if series and t.lower().startswith(series.lower()):
        t = t[len(series):]
    t = t.strip(' -_.')
    m = re.match(r'^(?:(?:episode|ep|e|серія|s\d{1,2}e)\s*)?(\d{1,4})(?:v\d)?(?:\s*[-–—:.]\s*|\s+|$)(.*)$', t, re.I)
    return (int(m.group(1)), m.group(2).strip(' -_.')) if m else (None, t)


def ep_dict(r, s, i, series=''):
    dur, pos = r['duration'] or 0, r['position'] or 0
    num, name = ep_name(r, series)
    num = num if num is not None else i + 1
    title = '%s · Серія %d%s' % (series, num, ' — ' + name if name else '') if series else (name or r['title'])
    return {'id': r['id'], 'title': title, 'etitle': name, 'folder': r['folder'], 'ext': r['ext'][1:], 'size': r['size'],
            'added': r['added'], 'dur': r['duration'], 'w': r['width'], 'h': r['height'], 'thumb': r['thumb'],
            'prep': needs_prepare(r), 'ready': os.path.isfile(prepared_path(r['id'])), 'vote': r['vote'],
            'pos': pos, 'posAt': r['position_at'], 'score': 30, 'views': s.get('views', 0), 'avg': s.get('avg'),
            'cmp': 0.5, 'pop': 0.0, 'last': s.get('last', 0), 'weekSec': 0, 'sprite': r['sprite'] or 0,
            'file': os.path.basename(r['path']), 'vc': r['vcodec'], 'ac': r['acodec'], 'anime': 1, 'ep': num,
            'done': bool(dur and pos >= dur * 0.9) or (s.get('views', 0) > 0 and pos < 5)}


def anime_info(sid, top, rows, st):
    series = anime_title(top) if top else ''
    eps = [ep_dict(r, st.get(r['id'], {}), i, series) for i, r in enumerate(rows)]
    seen = [e for e in eps if e['pos'] > 5 or e['done']]
    last = max(seen, key=lambda e: max(e['posAt'] or 0, e['last'] or 0)) if seen else None
    cont = None
    if last:
        i = eps.index(last)
        cont = last if not last['done'] else (eps[i + 1] if i + 1 < len(eps) else None)
    return {'sid': sid, 'title': anime_title(top) if top else 'Без папки', 'n': len(eps),
            'watched': sum(e['done'] for e in eps), 'cover': '/anime/cover/%s?v=%d' % (sid, anime_cover_version(sid, top)),
            'meta': anime_meta_public(sid),
            'lastAt': max((max(e['posAt'] or 0, e['last'] or 0) for e in eps), default=0),
            'added': max((e['added'] or 0 for e in eps), default=0),
            'cont': cont and {'id': cont['id'], 'ep': cont['ep'], 'pos': cont['pos'], 'dur': cont['dur']}}, eps


def anime_list_json():
    st = stats()['data']
    series = anime_series()
    for sid, (top, _) in series.items():
        anilist_want(sid, top)      # у фоні, по черзі
    out = [anime_info(sid, top, rows, st)[0] for sid, (top, rows) in series.items()]
    out.sort(key=lambda a: nat_key(a['title']))
    return {'folder': C.anime, 'titles': out}


def anime_title_json(key, by_ep=False):
    series = anime_series()
    if by_ep:
        key = next((sid for sid, (_, rows) in series.items() if any(r['id'] == key for r in rows)), None)
    if key not in series:
        return None
    info, eps = anime_info(key, *series[key], stats()['data'])
    info['eps'] = eps
    return info


# ── AniList: обкладинки й метадані тайтлів ──
# Одна черга з паузою між запитами: AniList пропускає лише кілька десятків запитів на хвилину,
# а сітка аніме просить обкладинки всіх тайтлів разом. Результат кешується в data/anime/<sid>.json
# (+ <sid>.jpg). Підказка для неточних назв: файл anilist.txt у теці тайтлу — ID з AniList або точна назва.
ANILIST_V = 2
ANILIST_Q = queue.Queue()
ANILIST_PENDING, ANILIST_FAIL = set(), {}
ANILIST_LOCK = threading.Lock()
ANILIST_FIELDS = ('id siteUrl title{romaji english native} coverImage{extraLarge large color} '
                  'description(asHtml:false) genres seasonYear episodes averageScore format')
SEASON_RE = re.compile(r'\b(s\d{1,2}|season\s*\d+|\d+(st|nd|rd|th)\s*season|part\s*\d+|сезон\s*\d+|\d+\s*сезон|tv|complete)\b', re.I)


def anilist_dir():
    return os.path.join(C.data, 'anime')


def anilist_meta(sid):
    try:
        with open(os.path.join(anilist_dir(), sid + '.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def anilist_hint(top):
    try:
        with open(os.path.join(C.anime, top, 'anilist.txt'), encoding='utf-8-sig') as f:
            return f.read().strip()
    except OSError:
        return ''


def anilist_want(sid, top):
    """Поставити тайтл у чергу, якщо метаданих ще немає (або невдача стара / підказка змінилась)."""
    if not top:
        return
    m = anilist_meta(sid)
    hint = anilist_hint(top)
    if m and m.get('v') == ANILIST_V and m.get('hint', '') == hint and (m.get('id') or time.time() - m.get('at', 0) < 7 * 86400):
        return
    if time.time() - ANILIST_FAIL.get(sid, 0) < 600:
        return
    with ANILIST_LOCK:
        if sid in ANILIST_PENDING:
            return
        ANILIST_PENDING.add(sid)
        start = not getattr(anilist_want, 'worker', None)
        if start:
            anilist_want.worker = threading.Thread(target=anilist_worker, daemon=True)
    ANILIST_Q.put((sid, top))
    if start:
        anilist_want.worker.start()


def anilist_queries(top):
    hint = anilist_hint(top)
    if hint:
        return [hint]
    t = anime_title(top)
    t = re.sub(r'\(\s*\d{4}\s*\)|\b(19|20)\d{2}\b', ' ', t)
    out = [re.sub(r'\s{2,}', ' ', t).strip(' -.')]
    s = re.sub(r'\s{2,}', ' ', SEASON_RE.sub(' ', t)).strip(' -.')
    if s and s not in out:
        out.append(s)
    return [q for q in out if q]


def anilist_post(query, variables):
    body = json.dumps({'query': query, 'variables': variables}).encode()
    for attempt in range(4):
        req = urllib.request.Request('https://graphql.anilist.co', data=body, headers={
            'Content-Type': 'application/json', 'Accept': 'application/json',
            'User-Agent': 'VidBox/%s (+https://github.com/AfricaEE112/hata)' % VERSION})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:      # забагато запитів — чекаємо, скільки просять, і пробуємо ще
                wait = int(e.headers.get('Retry-After') or 60)
                print('AniList: ліміт запитів, чекаю %d с' % wait)
                time.sleep(min(wait, 120) + 1)
                continue
            if e.code == 404:      # «не знайдено» AniList віддає як 404
                return {'data': {'Media': None}}
            raise
    raise RuntimeError('AniList не відповідає (ліміт запитів)')


def anilist_fetch(sid, top):
    d = anilist_dir()
    os.makedirs(d, exist_ok=True)
    media, used = None, ''
    for q in anilist_queries(top):
        used = q
        if q.isdigit():
            res = anilist_post('query($i:Int){Media(id:$i,type:ANIME){%s}}' % ANILIST_FIELDS, {'i': int(q)})
        else:
            res = anilist_post('query($s:String){Media(search:$s,type:ANIME,sort:SEARCH_MATCH){%s}}' % ANILIST_FIELDS, {'s': q})
        media = (res.get('data') or {}).get('Media')
        time.sleep(2.2)
        if media:
            break
    meta = {'v': ANILIST_V, 'at': time.time(), 'q': used, 'hint': anilist_hint(top)}
    if media:
        url = (media.get('coverImage') or {}).get('extraLarge') or (media.get('coverImage') or {}).get('large')
        if url:
            req = urllib.request.Request(url, headers={'User-Agent': 'VidBox/%s' % VERSION})
            with urllib.request.urlopen(req, timeout=30) as r:
                img = r.read()
            with open(os.path.join(d, sid + '.part'), 'wb') as f:
                f.write(img)
            os.replace(os.path.join(d, sid + '.part'), os.path.join(d, sid + '.jpg'))
        desc = re.sub(r'<br\s*/?>', '\n', media.get('description') or '', flags=re.I)
        desc = html.unescape(re.sub(r'<[^>]+>', '', desc))
        desc = re.sub(r'\n{3,}', '\n\n', desc.replace('\r', '')).strip()
        t = media.get('title') or {}
        meta.update(id=media.get('id'), url=media.get('siteUrl'), romaji=t.get('romaji'), english=t.get('english'),
                    native=t.get('native'), year=media.get('seasonYear'), episodes=media.get('episodes'),
                    score=media.get('averageScore'), format=media.get('format'), genres=media.get('genres') or [],
                    desc=desc, color=(media.get('coverImage') or {}).get('color'))
        print('AniList: «%s» → %s' % (anime_title(top), t.get('romaji') or t.get('english')))
    else:
        meta['none'] = True
        print('AniList: «%s» не знайдено (шукав: %s). Підказка: anilist.txt з ID у теці тайтлу' % (anime_title(top), used))
    with open(os.path.join(d, sid + '.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)


def anilist_worker():
    while True:
        sid, top = ANILIST_Q.get()
        try:
            anilist_fetch(sid, top)
        except Exception as e:
            ANILIST_FAIL[sid] = time.time()
            print('AniList: не вдалося для «%s» (%s)' % (anime_title(top), e))
            time.sleep(5)
        finally:
            with ANILIST_LOCK:
                ANILIST_PENDING.discard(sid)


def anime_cover_version(sid, top):
    """Змінюється, коли з'являється обкладинка — щоб браузер і апка взяли нову."""
    if top:
        for name in ('cover', 'poster', 'folder'):
            for ext in ('.jpg', '.jpeg', '.png', '.webp'):
                f = os.path.join(C.anime, top, name + ext)
                if os.path.isfile(f):
                    return int(os.path.getmtime(f))
    f = os.path.join(anilist_dir(), sid + '.jpg')
    return int(os.path.getmtime(f)) if os.path.isfile(f) else 0


def anime_meta_public(sid):
    m = anilist_meta(sid)
    if not m or not m.get('id'):
        return None
    return {k: m.get(k) for k in ('id', 'url', 'romaji', 'english', 'native', 'year', 'episodes', 'score',
                                  'format', 'genres', 'desc', 'color')}


RELINK_COPY = ('vote', 'position', 'position_at', 'added', 'first_seen', 'duration', 'width', 'height',
               'vcodec', 'acodec', 'pixfmt', 'probed')


def relink():
    """Файли переїхали (інший диск чи папка) — id від шляху змінився.
    Зниклий запис з тією ж назвою файлу й розміром, що й новий, вважаємо тим самим відео:
    переносимо історію, оцінку, позицію, дату додавання, обкладинку й спрайт, старий запис видаляємо."""
    old = DB.q('SELECT * FROM videos WHERE missing=1')
    if not old:
        return 0
    new = DB.q('SELECT * FROM videos WHERE missing=0')
    key = lambda r: (os.path.basename(r['path']).lower(), r['size'])
    by_key = {}
    for r in new:
        by_key.setdefault(key(r), []).append(r)
    olds = {}
    for r in old:
        olds.setdefault(key(r), []).append(r)
    busy = {r['video_id'] for r in DB.q('SELECT DISTINCT video_id FROM sessions')}
    pairs = []
    for k, os_ in olds.items():
        cand = [r for r in by_key.get(k, []) if r['id'] not in busy and not r['vote'] and not r['position']]
        if len(os_) == 1 and len(cand) == 1:   # лише однозначні збіги
            pairs.append((os_[0], cand[0]))
    if not pairs:
        return 0
    week = DB.q('SELECT week, data FROM weekly')
    for o, n in pairs:
        oid, nid = o['id'], n['id']
        vals = [o[c] if o[c] is not None else n[c] for c in RELINK_COPY]
        for c, src in (('thumb', thumb_path), ('sprite', sprite_path)):
            have_new = n[c] and os.path.isfile(src(nid))
            if not have_new and o[c] and os.path.isfile(src(oid)):
                try:
                    os.replace(src(oid), src(nid))
                    vals.append(1)
                    continue
                except OSError:
                    pass
            vals.append(n[c])
        for src in (prepared_path,):
            if os.path.isfile(src(oid)) and not os.path.isfile(src(nid)):
                try:
                    os.replace(src(oid), src(nid))
                except OSError:
                    pass
        shutil.rmtree(os.path.join(C.data, 'frames', oid), ignore_errors=True)
        cols = RELINK_COPY + ('thumb', 'sprite')
        with DB.lock:
            DB.con.execute('UPDATE videos SET %s WHERE id=?' % ', '.join(c + '=?' for c in cols), vals + [nid])
            DB.con.execute('UPDATE sessions SET video_id=? WHERE video_id=?', (nid, oid))
            DB.con.execute('DELETE FROM videos WHERE id=?', (oid,))
            DB.con.commit()
        week = [(w, d.replace('"%s"' % oid, '"%s"' % nid)) for w, d in week]
    DB.many('UPDATE weekly SET data=? WHERE week=?', [(d, w) for w, d in week])
    return len(pairs)


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
            info.update(vcodec=s.get('codec_name'), width=s.get('width'), height=s.get('height'),
                        pixfmt=s.get('pix_fmt'))
        elif s.get('codec_type') == 'audio' and 'acodec' not in info:
            info['acodec'] = s.get('codec_name')
    return info


# ───────────────────────────── відеокарта (апаратне прискорення) ─────────────────────────────
#
# Що робить відеокарта:
#   • конвертація для телефону (MKV/AVI/HEVC → H.264 MP4): декодування D3D11VA + кодування AMF.
#     Якщо фільтрів не треба — кадри взагалі не покидають відеокарту (найшвидший шлях);
#     10-біт і зменшення роздільності йдуть через процесор, бо AMF H.264 не приймає 10-біт.
#   • якщо GPU-кодування впало — та сама задача автоматично повторюється процесором.
# Окремі кадри (обкладинки, нарізки) беруться лише з ключових кадрів: це швидше за будь-яку
# відеокарту, бо запуск GPU на один кадр триває довше, ніж сам кадр. Можна ввімкнути й GPU.

HW_KINDS = (('amd', 'h264_amf', 'AMF'), ('nvidia', 'h264_nvenc', 'NVENC'),
            ('intel', 'h264_qsv', 'QSV'), ('vaapi', 'h264_vaapi', 'VA-API'))
ENC_LABEL = {enc: label for _, enc, label in HW_KINDS}
ENC_LABEL['libx264'] = 'CPU'
def vaapi_dev():
    """Вузол відеоядра для VA-API. У ноутбуках з двома відеокартами (Intel + NVIDIA) renderD128 може бути NVIDIA,
    у якої немає VA-API-кодування, — тож беремо Intel, потім AMD, а NVIDIA лише якщо іншого немає."""
    nodes = sorted(glob.glob('/sys/class/drm/renderD*'))
    rank = {'0x8086': 0, '0x1002': 1}
    best = None
    for n in nodes:
        try:
            vendor = open(os.path.join(n, 'device', 'vendor')).read().strip()
        except OSError:
            continue
        r = rank.get(vendor, 9)
        if best is None or r < best[0]:
            best = (r, '/dev/dri/' + os.path.basename(n))
    return best[1] if best else '/dev/dri/renderD128'


VAAPI_DEV = vaapi_dev() if os.name != 'nt' else '/dev/dri/renderD128'
HW = {'checked': False, 'gpu': '', 'encoders': {}, 'decode': None, 'zero_copy': False, 'last': None}
HW_LOCK = threading.Lock()


def gpu_name():
    try:
        if os.name == 'nt':
            out = run(['powershell', '-NoProfile', '-Command',
                       "(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join '; '"], 20)
            return out.stdout.decode('utf-8', 'replace').strip()
        if shutil.which('lspci'):
            out = run(['lspci'], 10).stdout.decode('utf-8', 'replace')
            return '; '.join(l.split(': ', 1)[1] for l in out.splitlines()
                             if ': ' in l and ('VGA' in l or '3D controller' in l or 'Display controller' in l))
    except Exception:
        pass
    return ''


def _ok(cmd, timeout=40):
    try:
        r = run(cmd, timeout)
        return r.returncode == 0, r.stderr.decode('utf-8', 'replace').strip()[-240:]
    except Exception as e:
        return False, str(e)


def detect_hw(verbose=True):
    """Пробує кожен апаратний кодувальник на 10 кадрах, перевіряє D3D11VA/VA-API."""
    if not C.ffmpeg:
        with HW_LOCK:
            HW.update(checked=True)
        return
    try:
        enc_list = run([C.ffmpeg, '-hide_banner', '-encoders'], 20).stdout.decode('utf-8', 'replace')
        accels = run([C.ffmpeg, '-hide_banner', '-hwaccels'], 20).stdout.decode('utf-8', 'replace')
    except Exception:
        enc_list = accels = ''
    src = ['-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=25:d=0.4']
    encs = {}
    for kind, enc, label in HW_KINDS:
        if kind == 'vaapi' and (os.name == 'nt' or not os.path.exists(VAAPI_DEV)):
            continue
        if not re.search(r'\b%s\b' % enc, enc_list):
            encs[kind] = {'enc': enc, 'label': label, 'ok': False, 'err': 'немає в цій збірці ffmpeg'}
            continue
        lp, vbr = False, True
        if kind == 'vaapi':
            cmd = [C.ffmpeg, '-hide_banner', '-v', 'error', '-vaapi_device', VAAPI_DEV, *src,
                   '-vf', 'format=nv12,hwupload', '-c:v', enc, '-f', 'null', '-']
            ok, err = _ok(cmd)
            if not ok:
                # Intel з 11-го покоління (Tiger Lake і новіші) кодує H.264 лише «енергоощадним» блоком VDEnc
                ok2, err2 = _ok(cmd[:-3] + ['-low_power', '1'] + cmd[-3:])
                ok, lp, err = (True, True, '') if ok2 else (False, False, err)
            if ok:   # керування бітрейтом (для перегляду на льоту); без прошивки HuC VDEnc уміє лише сталу якість
                vbr, _ = _ok(cmd[:-3] + (['-low_power', '1'] if lp else []) + ['-b:v', '2000k', '-maxrate', '3000k'] + cmd[-3:])
        else:
            cmd = [C.ffmpeg, '-hide_banner', '-v', 'error', *src, '-pix_fmt', 'nv12', '-c:v', enc, '-f', 'null', '-']
            ok, err = _ok(cmd)
        encs[kind] = {'enc': enc, 'label': label, 'ok': ok, 'err': '' if ok else err, 'lp': lp, 'vbr': vbr}
    decode, zero = None, False
    if os.name == 'nt' and re.search(r'\bd3d11va\b', accels):
        sample = os.path.join(C.data, 'hwtest.mp4')
        maker = 'libx264' if re.search(r'\blibx264\b', enc_list) else 'mpeg4'
        _ok([C.ffmpeg, '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=25:d=1',
             '-c:v', maker, '-pix_fmt', 'yuv420p', sample])
        if os.path.exists(sample):
            ok, _ = _ok([C.ffmpeg, '-hide_banner', '-v', 'error', '-hwaccel', 'd3d11va', '-i', sample, '-f', 'null', '-'])
            decode = 'd3d11va' if ok else None
            if ok and encs.get('amd', {}).get('ok'):
                zero, _ = _ok([C.ffmpeg, '-hide_banner', '-v', 'error', '-hwaccel', 'd3d11va', '-hwaccel_output_format', 'd3d11',
                               '-i', sample, '-c:v', 'h264_amf', '-f', 'null', '-'])
            try:
                os.remove(sample)
            except OSError:
                pass
    elif os.name != 'nt' and re.search(r'\bvaapi\b', accels) and os.path.exists(VAAPI_DEV):
        decode = 'vaapi'
        vdec = vaapi_decoders()
        with HW_LOCK:
            HW['vaapi_dec'] = vdec
        if encs.get('vaapi', {}).get('ok'):
            # Повний шлях на відеоядрі: декодування → масштабування → кодування, кадри не йдуть у процесор
            sample = os.path.join(C.data, 'hwtest.mp4')
            maker = 'libx264' if re.search(r'\blibx264\b', enc_list) else 'mpeg4'
            _ok([C.ffmpeg, '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=25:d=1',
                 '-c:v', maker, '-pix_fmt', 'yuv420p', sample])
            if os.path.exists(sample) and maker == 'libx264':
                zero, _ = _ok([C.ffmpeg, '-hide_banner', '-v', 'error', '-hwaccel', 'vaapi', '-hwaccel_output_format', 'vaapi',
                               '-vaapi_device', VAAPI_DEV, '-i', sample, '-vf', 'scale_vaapi=w=-2:h=240:format=nv12',
                               '-c:v', 'h264_vaapi', *(['-low_power', '1'] if encs['vaapi'].get('lp') else []), '-f', 'null', '-'])
            try:
                os.remove(sample)
            except OSError:
                pass
    gpu = gpu_name()
    with HW_LOCK:
        HW.update(checked=True, gpu=gpu, encoders=encs, decode=decode, zero_copy=zero)
    if verbose:
        enc = pick_encoder()
        print('  Відеокарта:   %s' % (gpu or 'не визначено'))
        print('                кодування: %s%s' % (
            ENC_LABEL.get(enc, enc) + (' (апаратне)' if enc != 'libx264' else ' — апаратного кодувальника не знайдено'),
            ', декодування: %s%s' % (decode.upper(), ' без копіювання кадрів' if zero else '') if decode else ''))


def pick_encoder():
    mode = C.cfg.get('hwaccel', 'auto')
    if mode == 'off' or not C.ffmpeg:
        return 'libx264'
    with HW_LOCK:
        encs = dict(HW.get('encoders') or {})
    for kind in (['amd', 'nvidia', 'intel', 'vaapi'] if mode == 'auto' else [mode]):
        if encs.get(kind, {}).get('ok'):
            return encs[kind]['enc']
    return 'libx264'


def grab_args():
    """Вхідні параметри для взяття окремих кадрів: лише ключові кадри (+ GPU, якщо ввімкнено)."""
    hw = []
    if C.cfg.get('hw_frames') and C.cfg.get('hwaccel', 'auto') != 'off':
        if HW.get('decode') == 'd3d11va':
            hw = ['-hwaccel', 'd3d11va']
        elif HW.get('decode') == 'vaapi':
            hw = ['-hwaccel', 'vaapi', '-vaapi_device', VAAPI_DEV]
    return hw + ['-skip_frame', 'nokey']


def grab(path, t, out, vf, q, flags, timeout=60):
    """Один кадр у JPEG. Спершу швидко (найближчий ключовий кадр), якщо не вийшло — точно."""
    for fast in (True, False):
        pre = grab_args() + ['-noaccurate_seek'] if fast else []
        try:
            subprocess.run([C.ffmpeg, '-v', 'error', '-y', *pre, '-ss', '%.2f' % t, '-i', path,
                            '-frames:v', '1', '-an', '-sn', '-vf', vf, '-q:v', str(q), out],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, creationflags=flags)
        except Exception:
            pass
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return True
    return False


def make_thumb(path, duration, out):
    if not C.ffmpeg:
        return False
    t = max(0.0, min(duration * 0.15, 300.0)) if duration and duration > 3 else 0.0
    tmp = out + '.tmp.jpg'
    for ss in (t, 0.0):
        if grab(path, ss, tmp, 'scale=480:-2', 4, BG_PRIO, 90):
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

    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            ok = list(ex.map(lambda it: grab(path, it[1], fpath(it[0]), vf, 5, flags), enumerate(sprite_times(duration))))
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
        if not grab(r['path'], sprite_times(r['duration'])[i], tmp, "scale=w='min(1280,iw)':h=-2", 4, NOWIN):
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


def queue_prep_all():
    """«Готувати копії заздалегідь»: ставить у чергу несумісні відео, поки є місце в кеші."""
    if not (C.ffmpeg and C.cfg.get('prep_all')):
        return 0
    if dir_size(os.path.join(C.data, 'prepared')) > 0.85 * C.cfg.get('cache_gb', 30) * 1024 ** 3:
        return 0
    with PREP_LOCK:
        busy = {k for k, v in PREP.items() if v.get('state') in ('queued', 'working', 'error')}
    n = 0
    for r in DB.q('SELECT * FROM videos WHERE missing=0 AND probed=1 ORDER BY added DESC'):
        if n >= 2:
            break
        if r['id'] in busy or not needs_prepare(r) or os.path.exists(prepared_path(r['id'])):
            continue
        request_prepare(r['id'])
        n += 1
    return n


def media_worker():
    """У фоні: тривалість, кодеки, обкладинки, потім нарізки кадрів, потім (якщо ввімкнено) копії."""
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
                todo = 0
                if C.ffmpeg and C.cfg.get('sprites', True):
                    todo = DB.one('SELECT COUNT(*) AS n FROM videos WHERE missing=0 AND sprite=0 '
                                  'AND duration > 0')['n']
                if not todo:
                    if announced:
                        print('  ✔ Нарізки кадрів готові для всіх відео')
                        announced = False
                    queue_prep_all()
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
                            width=?, height=?, vcodec=?, acodec=?, pixfmt=?,
                            thumb=CASE WHEN ?>0 THEN ? ELSE thumb END WHERE id=?''',
                         (info.get('duration'), info.get('width'), info.get('height'),
                          info.get('vcodec'), info.get('acodec'), info.get('pixfmt'), th, th, r['id']))
                except Exception:
                    traceback.print_exc()
                    DB.x('UPDATE videos SET probed=1 WHERE id=?', (r['id'],))
            DB.bump()


def odd_pixfmt(pixfmt):
    """H.264 не у звичному 8-біт 4:2:0 (10-біт аніме, 4:4:4): телефони таке не відтворюють."""
    return bool(pixfmt) and pixfmt not in ('yuv420p', 'yuvj420p', 'nv12')


def needs_prepare(r):
    if r['ext'] not in NATIVE_EXT:
        return True
    if r['vcodec'] and r['vcodec'] not in OK_VCODEC:
        return True
    if r['vcodec'] == 'h264' and odd_pixfmt(r['pixfmt']):
        return True
    if r['acodec'] and r['acodec'] not in OK_ACODEC:
        return True
    return False


def prepare_status(vid):
    if os.path.exists(prepared_path(vid)):
        with PREP_LOCK:
            st = dict(PREP.get(vid) or {})
        return {'state': 'ready', 'progress': 1.0, 'enc': st.get('enc'), 'fps': st.get('fps')}
    with PREP_LOCK:
        return dict(PREP.get(vid) or {'state': 'none', 'progress': 0.0})


def request_prepare(vid, force=False):
    """force=True: перекодувати в H.264, навіть якщо формат «мав би» грати (напр. HEVC на Android)."""
    if not C.ffmpeg:
        return {'state': 'error', 'progress': 0.0, 'error': 'ffmpeg не знайдено'}
    with PREP_LOCK:
        st = PREP.get(vid)
        if st and st['state'] in ('queued', 'working'):
            return dict(st)
        if os.path.exists(prepared_path(vid)):
            if not force or (st and st.get('force')):
                return {'state': 'ready', 'progress': 1.0}
            try:
                os.remove(prepared_path(vid))
            except OSError:
                pass
        PREP[vid] = {'state': 'queued', 'progress': 0.0, 'force': force}
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
        if C.cfg.get('prep_all'):
            MEDIA_EVENT.set()


VAAPI_DECODES = {'h264', 'hevc', 'vp9', 'av1', 'mpeg2video', 'vc1', 'vp8'}   # що відеоядро Intel може розпаковувати
VA_PROFILES = {'H264': 'h264', 'HEVC': 'hevc', 'VP9': 'vp9', 'AV1': 'av1', 'MPEG2': 'mpeg2video', 'VC1': 'vc1', 'VP8': 'vp8'}


def vaapi_decoders():
    """Які кодеки це відеоядро справді розпаковує (vainfo: профіль + VAEntrypointVLD). Наприклад, AV1 — лише з 11-го покоління Intel."""
    try:
        out = run(['vainfo', '--display', 'drm', '--device', VAAPI_DEV], 20).stdout.decode('utf-8', 'replace')
    except Exception:
        return None                  # vainfo немає — покладаємося на запасні варіанти при помилці
    found = set()
    for m in re.finditer(r'VAProfile(\w+)\s*:\s*VAEntrypointVLD', out):
        for prefix, codec in VA_PROFILES.items():
            if m.group(1).startswith(prefix):
                found.add(codec)
    return found or None


def encode_args(enc, src_h, odd, target_h=None, kbps=None, gop_n=120, vcodec=None, zero=True):
    """(параметри входу, параметри відео) для кодувальника. Підібрано під RDNA2 (RX 6000) для AMF.
    target_h і kbps — для перекодування на льоту: висота кадру й межа бітрейту."""
    mh = int(target_h or C.cfg.get('max_height') or 0)
    scale = bool(mh and src_h and src_h > mh)
    pre, vf = [], []
    if scale:
        vf.append('scale=-2:%d' % mh)
    gop = ['-g', str(gop_n)]               # ключовий кадр кожні ~5 с: швидке перемотування на телефоні
    rate = ['-b:v', '%dk' % kbps, '-maxrate', '%dk' % (kbps * 3 // 2), '-bufsize', '%dk' % (kbps * 2)] if kbps else []
    if enc == 'h264_amf':
        dec = HW.get('decode')
        if dec == 'd3d11va' and HW.get('zero_copy') and not scale and not odd:
            pre = ['-hwaccel', 'd3d11va', '-hwaccel_output_format', 'd3d11']   # кадри не покидають відеокарту
        else:
            if dec == 'd3d11va':
                pre = ['-hwaccel', 'd3d11va']                                  # декодує GPU, фільтри — процесор
            vf.append('format=nv12')
        v = ['-c:v', 'h264_amf', '-usage', 'transcoding', '-quality', 'balanced',
             *(['-rc', 'vbr_peak', *rate] if kbps else ['-rc', 'cqp', '-qp_i', '20', '-qp_p', '22', '-qp_b', '24']),
             '-profile:v', 'high', *gop]
    elif enc == 'h264_nvenc':
        vf.append('format=yuv420p')
        v = ['-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', *(rate or ['-cq', '22', '-b:v', '0']), '-profile:v', 'high', *gop]
    elif enc == 'h264_qsv':
        vf.append('format=nv12')
        v = ['-c:v', 'h264_qsv', '-preset', 'faster', *(rate or ['-global_quality', '22']), *gop]
    elif enc == 'h264_vaapi':
        va = (HW.get('encoders') or {}).get('vaapi', {})
        lp = ['-low_power', '1'] if va.get('lp') else []
        if rate and va.get('vbr') is False:
            rate = ['-qp', '25' if (target_h or 0) <= 720 else '23']    # бітрейт не підтримується — тримаємо якість
        gpu_dec = HW.get('decode') == 'vaapi' and vcodec in (HW.get('vaapi_dec') or VAAPI_DECODES)
        if HW.get('vaapi_dec') is None and vcodec == 'av1':
            gpu_dec = False          # невідомо, чи вміє відеоядро AV1 (до 11-го покоління Intel — ні): хай розпаковує процесор
        if zero and gpu_dec and HW.get('zero_copy'):
            # усе на відеоядрі: HEVC/AV1/10-біт розпаковує GPU, scale_vaapi зменшує й переводить у 8 біт
            pre = ['-hwaccel', 'vaapi', '-hwaccel_output_format', 'vaapi', '-vaapi_device', VAAPI_DEV]
            vf = ['scale_vaapi=w=-2:h=%d:format=nv12' % mh if scale else 'scale_vaapi=format=nv12']
        else:
            pre = (['-hwaccel', 'vaapi'] if gpu_dec else []) + ['-vaapi_device', VAAPI_DEV]
            vf += ['format=nv12', 'hwupload']
        v = ['-c:v', 'h264_vaapi', *lp, *(rate or ['-qp', '22']), *gop]
    else:
        vf.append('format=yuv420p')
        v = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23' if kbps else '22', *rate[2:], '-profile:v', 'high', *gop]
    if vf:
        v = ['-vf', ','.join(vf)] + v
    return pre, v


def run_convert(cmd, st, dur):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
    err = []
    t = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
    t.start()
    for raw in p.stdout:
        line = raw.decode('utf-8', 'replace').strip()
        k, _, val = line.partition('=')
        try:
            with PREP_LOCK:
                if k == 'out_time_us' and dur:
                    st['progress'] = max(0.0, min(0.99, int(val) / 1e6 / dur))
                elif k == 'fps':
                    st['fps'] = round(float(val))
                elif k == 'speed' and val.endswith('x'):
                    st['speed'] = float(val[:-1])
        except ValueError:
            pass
    rc = p.wait()
    t.join(5)
    return rc == 0, (err[0] if err else b'').decode('utf-8', 'replace').strip()


def convert(vid, st):
    """Робить MP4-копію, яку відкриє будь-який телефон.
    H.264 8-біт і HEVC просто перепаковуються (секунди), решта перекодовується відеокартою."""
    r = DB.one('SELECT * FROM videos WHERE id=?', (vid,))
    if not r:
        raise RuntimeError('відео не знайдено')
    info = probe(r['path']) or {'vcodec': r['vcodec'], 'acodec': r['acodec'], 'duration': r['duration'],
                                'height': r['height'], 'pixfmt': r['pixfmt']}
    vc, ac, odd = info.get('vcodec'), info.get('acodec'), odd_pixfmt(info.get('pixfmt'))
    force = st.get('force')
    copy = (vc == 'h264' and not odd) or (vc == 'hevc' and not force)
    a = ['-c:a', 'copy'] if ac in ('aac', 'mp3') else ['-c:a', 'aac', '-b:a', '192k', '-ac', '2']
    out = prepared_path(vid)
    tmp = out[:-4] + '.part.mp4'
    dur = info.get('duration') or r['duration'] or 0
    if copy:
        plans = [('copy', [], ['-c:v', 'copy'] + (['-tag:v', 'hvc1'] if vc == 'hevc' else []))]
    else:
        enc = pick_encoder()
        plans = [(e, *encode_args(e, info.get('height'), odd, vcodec=vc)) for e in ([enc, 'libx264'] if enc != 'libx264' else ['libx264'])]
        if enc == 'h264_vaapi' and HW.get('zero_copy'):     # якщо повний GPU-шлях не вийде — GPU лише кодує
            plans.insert(1, (enc, *encode_args(enc, info.get('height'), odd, vcodec=vc, zero=False)))
    last_err = ''
    for enc, pre, v in plans:
        with PREP_LOCK:
            st.update(enc=ENC_LABEL.get(enc, 'copy' if enc == 'copy' else enc), progress=0.0, fps=None)
        cmd = [C.ffmpeg, '-hide_banner', '-v', 'error', '-y', '-fflags', '+genpts', *pre, '-i', r['path'],
               '-map', '0:v:0', '-map', '0:a:0?', '-sn', '-dn', *v, *a,
               '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', tmp]
        started = time.time()
        ok, last_err = run_convert(cmd, st, dur)
        if ok and os.path.exists(tmp):
            os.replace(tmp, out)
            with HW_LOCK:
                HW['last'] = {'title': r['title'], 'enc': ENC_LABEL.get(enc, enc), 'fps': st.get('fps'),
                              'speed': st.get('speed'), 'secs': round(time.time() - started), 'at': time.time()}
            trim_cache(keep=out)
            return
        try:
            os.remove(tmp)
        except OSError:
            pass
        if enc not in ('copy', 'libx264'):
            print('  ⚠ %s не впорався з «%s», повторюю процесором: %s' % (ENC_LABEL.get(enc, enc), r['title'], last_err[-160:]))
    raise RuntimeError(last_err or 'ffmpeg завершився з помилкою')


# ── перекодування на льоту: потрібна якість одразу, без очікування копії ──
LIVE_KBPS = {1080: 6000, 720: 3000, 480: 1500}
LIVE_MAX = 2
LIVE = {}                 # адреса клієнта -> процес ffmpeg
LIVE_LOCK = threading.Lock()


def live_cmd(r, h, t, enc):
    pre, v = encode_args(enc, r['height'], odd_pixfmt(r['pixfmt']), target_h=h, kbps=LIVE_KBPS[h], gop_n=48, vcodec=r['vcodec'])
    ss = ['-ss', '%.3f' % t] if t > 0 else []
    return [C.ffmpeg, '-hide_banner', '-v', 'error', '-fflags', '+genpts', *pre, *ss, '-i', r['path'],
            '-map', '0:v:0', '-map', '0:a:0?', '-sn', '-dn', *v, '-c:a', 'aac', '-b:a', '128k', '-ac', '2',
            '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov+default_base_moof', '-frag_duration', '2000000', 'pipe:1']


# ── копії для завантаження на телефон: звичайний MP4 (з перемоткою) потрібної висоти ──
DLV, DLV_LOCK = {}, threading.Lock()


def dl_path(vid, h):
    return os.path.join(C.data, 'dl', '%s_%d.mp4' % (vid, h))


def dlv_status(vid, h, start=False):
    key = (vid, h)
    with DLV_LOCK:
        st = DLV.get(key)
        if st and st['state'] == 'working':
            return dict(st)
        if os.path.isfile(dl_path(vid, h)):
            return {'state': 'ready', 'progress': 1.0, 'size': os.path.getsize(dl_path(vid, h))}
        if not start:
            return dict(st) if st else {'state': 'none', 'progress': 0.0}
        if not C.ffmpeg:
            return {'state': 'error', 'progress': 0.0, 'error': 'ffmpeg не знайдено'}
        DLV[key] = {'state': 'working', 'progress': 0.0}
    threading.Thread(target=dlv_run, args=(vid, h), daemon=True).start()
    return {'state': 'working', 'progress': 0.0}


def dlv_run(vid, h):
    key, out = (vid, h), dl_path(vid, h)
    d = os.path.dirname(out)
    os.makedirs(d, exist_ok=True)
    for n in os.listdir(d):   # копії старші за 2 дні телефон уже забрав
        try:
            if time.time() - os.path.getmtime(os.path.join(d, n)) > 2 * 86400:
                os.remove(os.path.join(d, n))
        except OSError:
            pass
    r = DB.one('SELECT * FROM videos WHERE id=?', (vid,))
    dur = (r['duration'] or 0) if r else 0
    part = out[:-4] + '.part.mp4'
    enc = pick_encoder()
    for e in ([enc, 'libx264'] if enc != 'libx264' else ['libx264']) if r else []:
        cmd = live_cmd(r, h, 0, e)
        cmd = cmd[:cmd.index('-f')] + ['-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', '-y', part]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             creationflags=NOWIN)
        for line in p.stdout:
            if dur and line.startswith((b'out_time_us=', b'out_time_ms=')):
                try:
                    DLV[key]['progress'] = min(0.99, int(line.split(b'=')[1]) / 1e6 / dur)
                except (ValueError, KeyError):
                    pass
        if p.wait() == 0 and os.path.isfile(part):
            os.replace(part, out)
            with DLV_LOCK:
                DLV[key] = {'state': 'ready', 'progress': 1.0}
            print('Копія для телефона готова: %s, %dp' % (r['title'], h))
            return
    with DLV_LOCK:
        DLV[key] = {'state': 'error', 'progress': 0.0, 'error': 'Не вдалося перекодувати'}


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
    rows = [r for r in DB.q('SELECT id, added, duration, root FROM videos WHERE missing=0 AND vote >= 0')
            if not is_anime(r)]
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
    def names(sub):
        try:
            return {n.split('.')[0] for n in os.listdir(os.path.join(C.data, sub)) if n.endswith('.jpg')}
        except OSError:
            return set()
    have_spr, have_th = names('sprites'), names('thumbs')
    lost_spr, lost_th = [], []          # кеш почистили вручну → перегенерувати
    vids, pending, sprites = [], 0, 0
    for r in DB.q('SELECT * FROM videos WHERE missing=0'):
        if is_anime(r):   # аніме — окремий розділ, у бібліотеку не потрапляє
            continue
        if (r['sprite'] or 0) > 0 and r['id'] not in have_spr:
            lost_spr.append(r['id'])
        if r['thumb'] and r['id'] not in have_th:
            lost_th.append(r['id'])
        s = st['data'].get(r['id'], {})
        if not r['probed'] and (C.ffprobe or C.ffmpeg):
            pending += 1
        if C.ffmpeg and not r['sprite']:
            sprites += 1
        vids.append({
            'id': r['id'], 'title': r['title'], 'folder': r['folder'], 'ext': r['ext'][1:],
            'size': r['size'], 'added': r['added'], 'dur': r['duration'],
            'w': r['width'], 'h': r['height'], 'thumb': 0 if r['id'] in lost_th else r['thumb'],
            'prep': needs_prepare(r), 'ready': r['id'] in ready, 'vote': r['vote'],
            'pos': r['position'], 'posAt': r['position_at'],
            'score': s.get('score', 30), 'views': s.get('views', 0), 'avg': s.get('avg'),
            'cmp': s.get('cmp', 0.5), 'pop': s.get('pop', 0.0),
            'last': s.get('last', 0), 'weekSec': s.get('week_sec', 0),
            'sprite': 0 if r['id'] in lost_spr else (r['sprite'] or 0), 'file': os.path.basename(r['path']),
            'vc': r['vcodec'], 'ac': r['acodec']})
    if lost_spr or lost_th:
        DB.many('UPDATE videos SET sprite=0 WHERE id=?', [(i,) for i in lost_spr])
        DB.many('UPDATE videos SET thumb=0, probed=0 WHERE id=?', [(i,) for i in lost_th])
        MEDIA_EVENT.set()
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
    'folders': [], 'anime_folder': '', 'port': 8800, 'open_browser': True, 'rescan_min': 10,
    'cache_gb': 30, 'frames_cache_gb': 3, 'sprites': True,
    'autoplay_next': True, 'next_delay': 8, 'resume': True,
    'ui': {'sort': 'score', 'dir': 'desc', 'group': 'all'},
    'theme': 'arch',
    'hwaccel': 'auto', 'hw_frames': False, 'max_height': 1080, 'prep_all': False,
    'password_hash': '', 'secret': '', 'cfg_version': 5,
}
THEMES = {'arch', 'tokyo', 'catppuccin', 'dracula', 'gruvbox', 'nord', 'sweet', 'exodia', 'cinema', 'projector'}
HWACCEL_MODES = {'auto', 'amd', 'nvidia', 'intel', 'vaapi', 'off'}
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
    if raw and raw.get('cfg_version', 0) < 5 and cfg['theme'] == 'cinema':
        cfg['theme'] = 'arch'          # 0.5: нова тема за замовчуванням
    cfg['cfg_version'] = DEFAULTS['cfg_version']
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
        for k in ('autoplay_next', 'resume', 'sprites', 'open_browser', 'hw_frames', 'prep_all'):
            if k in d:
                cfg[k] = bool(d[k])
        if d.get('hwaccel') in HWACCEL_MODES:
            cfg['hwaccel'] = d['hwaccel']
        if 'max_height' in d and d['max_height'] in (0, 720, 1080, 1440, 2160):
            cfg['max_height'] = d['max_height']
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
            if u.get('group') in ('all', 'folders', 'duration'):
                cfg['ui']['group'] = u['group']
        if 'anime_folder' in d:
            a = str(d['anime_folder'] or '').strip()
            if a:
                a = os.path.abspath(os.path.expanduser(a))
                if not os.path.isdir(a):
                    return {'ok': False, 'error': 'Папку для аніме не знайдено: ' + a}
                na = os.path.normcase(a).rstrip('\\/') + os.sep
                for f in cfg['folders']:
                    nf = os.path.normcase(f).rstrip('\\/') + os.sep
                    if nf.startswith(na) or na.startswith(nf):
                        return {'ok': False, 'error': 'Папка аніме не може бути всередині папки з відео (і навпаки): ' + f}
            if a != cfg.get('anime_folder', ''):
                cfg['anime_folder'] = a
                C.anime = a
                changed_folders = True
        if 'folders' in d:
            folders, err = check_folders(d['folders'] if isinstance(d['folders'], list) else [])
            if err:
                return {'ok': False, 'error': err}
            if folders != cfg['folders']:
                cfg['folders'] = folders
                C.roots = list(folders)
                changed_folders = True
        save_config()
    if changed_folders:
        threading.Thread(target=scan, daemon=True).start()
    if d.get('sprites') or d.get('prep_all'):
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
    out = {k: cfg[k] for k in DEFAULTS if k not in ('password_hash', 'secret', 'folders', 'cfg_version')}
    out.update(
        folders=[{'path': f, 'count': counts.get(os.path.normcase(f), 0), 'exists': os.path.isdir(f)}
                 for f in cfg['folders']],
        caches={k: dir_size(os.path.join(C.data, k)) for k in ('thumbs', 'sprites', 'frames', 'prepared')},
        animeCount=counts.get(os.path.normcase(C.anime), 0) if C.anime else 0,
        animeTitles=len(anime_series()) if C.anime else 0,
        animeExists=bool(cfg.get('anime_folder')) and os.path.isdir(cfg['anime_folder']),
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
    with HW_LOCK:
        hw = json.loads(json.dumps(HW))
    enc = pick_encoder()
    hw.update(current=ENC_LABEL.get(enc, enc), hardware=enc != 'libx264')
    out['hw'] = hw
    return out


def status_json():
    """Дані для верхньої панелі (як модулі polybar/waybar)."""
    with PREP_LOCK:
        work = [(k, dict(v)) for k, v in PREP.items() if v.get('state') == 'working']
        queued = sum(1 for v in PREP.values() if v.get('state') == 'queued')
    conv = None
    if work:
        vid, st = work[0]
        r = DB.one('SELECT title FROM videos WHERE id=?', (vid,))
        conv = {'id': vid, 'title': r['title'] if r else '', 'progress': st.get('progress', 0),
                'fps': st.get('fps'), 'enc': st.get('enc')}
    c = DB.one('SELECT COUNT(*) AS n, COALESCE(SUM(probed=0), 0) AS probe, COALESCE(SUM(sprite=0 AND duration>0), 0) AS spr '
               'FROM videos WHERE missing=0')
    disk = media_disks()
    enc = pick_encoder()
    with HW_LOCK:
        gpu, checked = HW.get('gpu', ''), HW.get('checked')
    return {'videos': c['n'], 'probe': c['probe'] if (C.ffprobe or C.ffmpeg) else 0,
            'sprites': c['spr'] if (C.ffmpeg and C.cfg.get('sprites', True)) else 0,
            'conv': conv, 'queue': queued, 'disk': disk, 'enc': ENC_LABEL.get(enc, enc), 'hardware': enc != 'libx264',
            'gpu': gpu, 'hwChecked': checked, 'host': socket.gethostname(), 'uptime': round(time.time() - STARTED)}


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
    """Значок «▶_»: трикутник «play» як промпт терміналу з курсором. Без бібліотек, зі згладжуванням."""
    if size in _icons:
        return _icons[size]
    tri = [(0.22 * size, 0.27 * size), (0.22 * size, 0.73 * size), (0.59 * size, 0.50 * size)]
    edges = []
    for i in range(3):
        (x1, y1), (x2, y2) = tri[i], tri[(i + 1) % 3]
        ln = math.hypot(x2 - x1, y2 - y1)
        edges.append((x1, y1, (x2 - x1) / ln, (y2 - y1) / ln))
    cur = (0.62 * size, 0.655 * size, 0.81 * size, 0.73 * size)      # курсор «_»
    top, bottom = (21, 27, 37), (9, 12, 17)                         # тло як у темі Arch
    acc, acc2, fg = (23, 147, 209), (86, 197, 242), (225, 230, 239)
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        k = y / size
        bg = [top[j] + (bottom[j] - top[j]) * k for j in range(3)]
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            # світіння навколо трикутника
            d = math.hypot(px - 0.38 * size, py - 0.5 * size) / size
            glow = max(0.0, 0.22 - d) * 0.9
            col = [min(255.0, bg[j] + acc[j] * glow) for j in range(3)]
            a = max(0.0, min(1.0, min(dy * (px - ex) - dx * (py - ey) for ex, ey, dx, dy in edges) + 0.5))
            if a:
                t = (py - tri[0][1]) / (tri[1][1] - tri[0][1])
                c = [acc[j] + (acc2[j] - acc[j]) * (1 - t) * 0.6 for j in range(3)]
                col = [col[j] + (c[j] - col[j]) * a for j in range(3)]
            b = max(0.0, min(1.0, min(px - cur[0], cur[2] - px, py - cur[1], cur[3] - py) + 0.5))
            if b:
                col = [col[j] + (fg[j] - col[j]) * b for j in range(3)]
            raw += bytes((int(col[0]), int(col[1]), int(col[2]), 255))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))
    _icons[size] = png
    return png


MANIFEST = json.dumps({
    'name': APP, 'short_name': APP, 'start_url': '/', 'scope': '/', 'display': 'standalone',
    'background_color': '#0c0f14', 'theme_color': '#0c0f14',
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

    def send_anime_cover(self, sid):
        ser = anime_series().get(sid)
        if not ser:
            return self.send_json({'error': 'not found'}, 404)
        top, rows = ser
        if top:
            folder = os.path.join(C.anime, top)
            for name in ('cover', 'poster', 'folder'):
                for ext in ('.jpg', '.jpeg', '.png', '.webp'):
                    f = os.path.join(folder, name + ext)
                    if os.path.isfile(f):
                        return self.send_file(f, 'image/' + ('jpeg' if ext in ('.jpg', '.jpeg') else ext[1:]))
        cached = os.path.join(C.data, 'anime', sid + '.jpg')
        if os.path.isfile(cached):
            return self.send_file(cached, 'image/jpeg')
        anilist_want(sid, top)
        first = next((r for r in rows if r['thumb'] and os.path.isfile(thumb_path(r['id']))), None)
        if first:
            return self.send_file(thumb_path(first['id']), 'image/jpeg')
        return self.send_json({'error': 'no cover'}, 404)

    def redirect(self, to, extra=None):
        h = {'Location': to}
        h.update(extra or {})
        self.send_bytes(b'', 'text/plain', 303, extra=h)

    def body(self, limit=65536):
        if self._body is not None:
            return self._body
        n = int(self.headers.get('Content-Length') or 0)
        if n > limit:
            self.close_connection = True
            raise ValueError('body too large')
        self._body = self.rfile.read(n) if n else b''
        return self._body

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

    def send_live(self, r, qs, head):
        """Потік fragmented MP4 з перекодуванням на льоту (?h=1080|720|480&t=секунди).
        Довжина невідома, тож відповідь закінчується закриттям з'єднання. Перемотка = новий запит з іншим t."""
        try:
            h = int(qs.get('h', ['720'])[0])
        except ValueError:
            h = 720
        h = h if h in LIVE_KBPS else 720
        try:
            t = max(0.0, float(qs.get('t', ['0'])[0]))
        except ValueError:
            t = 0.0
        if not C.ffmpeg:
            return self.send_json({'error': 'no ffmpeg'}, 503)
        ip = self.client_address[0]
        with LIVE_LOCK:
            old = LIVE.pop(ip, None)          # той самий клієнт перемотав — старий потік більше не потрібен
            if old:
                old.kill()
            if len(LIVE) >= LIVE_MAX:
                return self.send_json({'error': 'busy'}, 503)
        enc = pick_encoder()
        p, first = None, b''
        for e in ([enc, 'libx264'] if enc != 'libx264' else ['libx264']):
            p = subprocess.Popen(live_cmd(r, h, t, e), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, creationflags=NOWIN)
            with LIVE_LOCK:
                LIVE[ip] = p
            first = os.read(p.stdout.fileno(), 1 << 16)
            if first:
                break
            p.wait()
        try:
            if not first:
                return self.send_json({'error': 'ffmpeg'}, 500)
            self.close_connection = True
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.send_header('X-Live-Start', '%.3f' % t)
            self.end_headers()
            if head:
                return
            self.wfile.write(first)
            fd = p.stdout.fileno()
            while True:
                chunk = os.read(fd, 1 << 16)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            if p and p.poll() is None:
                p.kill()
            if p:
                p.wait()
            with LIVE_LOCK:
                if LIVE.get(ip) is p:
                    del LIVE[ip]

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
        self._body = None
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
                if path == '/api/hello':
                    return self.send_json(hello_json())
            if method == 'POST' and path == '/api/login':   # вхід з Android-апки
                pw = str(self.json_body().get('password') or '')
                if not C.cfg.get('password_hash'):
                    return self.send_json({'ok': True, 'token': ''})
                if hmac.compare_digest(pw_hash(pw), C.cfg['password_hash']):
                    return self.send_json({'ok': True, 'token': auth_token()})
                return self.send_json({'ok': False, 'error': 'Неправильний пароль'}, 401)
            if method == 'POST' and path == '/login':
                form = urllib.parse.parse_qs(self.body().decode('utf-8', 'replace'))
                if C.cfg.get('password_hash') and hmac.compare_digest(pw_hash(form.get('p', [''])[0]),
                                                                      C.cfg['password_hash']):
                    cookie = 'vb=%s; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax' % auth_token()
                    return self.redirect('/', {'Set-Cookie': cookie})
                html = LOGIN_HTML.replace('{err}', '<p class="err">Неправильний пароль</p>')
                return self.send_bytes(html.encode(), 'text/html; charset=utf-8', 401)
            if not self.authed():
                if path.startswith(('/api/', '/stream/', '/thumb/', '/live/', '/dlfile/')):
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
                m = re.fullmatch(r'/live/(\w+)', path)
                if m:
                    r = self.video_row(m.group(1))
                    if not r:
                        return self.send_json({'error': 'not found'}, 404)
                    return self.send_live(r, qs, method == 'HEAD')
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
                if path == '/api/status':
                    return self.send_json(status_json())
                if path == '/api/admin':
                    return self.send_json(admin_json())
                m = re.fullmatch(r'/(api/dlprep|dlfile)/(\w+)', path)
                if m:
                    h = int(qs.get('h', ['720'])[0]) if qs.get('h', ['720'])[0].isdigit() else 720
                    if h not in LIVE_KBPS or not self.video_row(m.group(2)):
                        return self.send_json({'error': 'not found'}, 404)
                    if m.group(1) == 'dlfile':
                        return self.send_file(dl_path(m.group(2), h), 'video/mp4')
                    return self.send_json(dlv_status(m.group(2), h))
                if path == '/api/anime':
                    return self.send_json(anime_list_json())
                m = re.fullmatch(r'/api/anime/(ep/)?(\w+)', path)
                if m:
                    d = anime_title_json(m.group(2), by_ep=bool(m.group(1)))
                    return self.send_json(d or {'error': 'not found'}, 200 if d else 404)
                m = re.fullmatch(r'/anime/cover/(\w+)', path)
                if m:
                    return self.send_anime_cover(m.group(1))
                if path == '/api/fs':
                    return self.send_json(list_dirs(qs.get('path', [''])[0]))
                return self.send_web(path)

            if method == 'POST':
                m = re.fullmatch(r'/api/dlprep/(\w+)', path)
                if m:
                    h = int(qs.get('h', ['720'])[0]) if qs.get('h', ['720'])[0].isdigit() else 720
                    if h not in LIVE_KBPS or not self.video_row(m.group(1)):
                        return self.send_json({'error': 'not found'}, 404)
                    return self.send_json(dlv_status(m.group(1), h, start=True))
                if path == '/api/admin/restart':
                    restart_later()
                    return self.send_json({'ok': True})
                if path == '/api/admin/update':
                    r = update_from_github()
                    if r.get('ok') and r.get('changed'):
                        restart_later(1.0)
                        r['restarting'] = True
                    return self.send_json(r)
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
                if path == '/api/hw/detect':
                    threading.Thread(target=detect_hw, daemon=True).start()
                    return self.send_json({'ok': True})
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
                    return self.send_json(request_prepare(m.group(1), force=qs.get('mode', [''])[0] == 'h264'))
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
        finally:
            # тіло запиту, яке маршрут не прочитав, треба дочитати: інакше в з'єднанні keep-alive
            # воно склеїться з наступним запитом і той отримає 501
            if method == 'POST' and self._body is None and not self.close_connection:
                try:
                    self.body(1 << 20)
                except (ValueError, OSError):
                    self.close_connection = True


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


DISCOVERY_PORT = 48800


def hello_json():
    """Коротка візитка сервера: її бачить Android-апка ще до входу (без пароля)."""
    return {'app': APP, 'version': VERSION, 'host': socket.gethostname(), 'port': C.port,
            'auth': bool(C.cfg.get('password_hash'))}


def discovery_loop():
    """Апка шле в мережу UDP-пакет «VIDBOX?» — відповідаємо, де нас шукати."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', DISCOVERY_PORT))
    except OSError as e:
        print('  Автопошук для апки вимкнено: порт %d зайнятий (%s)' % (DISCOVERY_PORT, e))
        return
    while True:
        try:
            data, addr = s.recvfrom(256)
            if data.strip() == b'VIDBOX?':
                s.sendto(json.dumps(hello_json(), ensure_ascii=False).encode('utf-8'), addr)
        except OSError:
            time.sleep(1)


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
    LOG.install()
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
    managed = os.environ.get('VIDBOX_MANAGED') == 'hata'
    wanted = list(folders)
    missing = [f for f in folders if not os.path.isdir(f)]
    for f in missing:
        print('⚠ Папку не знайдено (пропускаю):', f)
    folders = [f for f in folders if os.path.isdir(f)]
    if managed and wanted and not folders:
        # Під Hata диск з відео міг ще не підключитись (USB, док без живлення). Не падаємо по колу,
        # а чекаємо: Hata сама підмонтує диск, щойно він з'явиться.
        print('Чекаю на диск з відео:', ', '.join(wanted), flush=True)
        while not any(os.path.isdir(f) for f in wanted):
            time.sleep(10)
        folders = [f for f in wanted if os.path.isdir(f)]
        missing = [f for f in wanted if f not in folders]
    if not folders:
        print('Не вибрано жодної папки з відео. Запусти так: python vidbox.py "D:\\Videos"')
        sys.exit(1)
    folders, err = check_folders(folders)
    if err:
        print('⚠', err)
        sys.exit(1)
    if managed and missing:
        def wait_missing():   # з'явилась пропущена папка — перезапуск (systemd підніме нас уже з нею)
            while not any(os.path.isdir(f) for f in missing):
                time.sleep(15)
            print('Папка з\'явилась — перезапускаюсь, щоб її підхопити', flush=True)
            os._exit(0)
        threading.Thread(target=wait_missing, daemon=True).start()
    C.cfg['folders'] = wanted if managed else folders   # під Hata не забуваємо диск, якого зараз немає
    if args.port:
        C.cfg['port'] = args.port
    if args.password:
        C.cfg['password_hash'] = pw_hash(args.password)
    if args.no_password:
        C.cfg['password_hash'] = ''
    save_config()

    C.roots = folders
    a = C.cfg.get('anime_folder') or ''
    C.anime = a if a and os.path.isdir(a) else ''
    C.port = int(C.cfg['port'])
    C.ffmpeg = find_tool('ffmpeg', args.ffmpeg)
    C.ffprobe = find_tool('ffprobe', args.ffmpeg or C.ffmpeg)
    C.verbose = args.verbose

    DB = Store(os.path.join(C.data, 'vidbox.db'))
    print('Сканую папки…')
    total, new = scan()
    for attempt in range(40 if os.environ.get('VIDBOX_RESTART') else 1):
        try:
            httpd = Server((args.host, C.port), Handler)
            break
        except OSError as e:
            err = e
            time.sleep(0.25)   # після перезапуску старий процес ще може тримати порт
    else:
        e = err
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
    print('  Ctrl+C — зупинити')
    print('  Android-апка: знайде цей ПК сама, якщо телефон у тій самій Wi-Fi мережі\n')
    for target in (media_worker, prep_worker, rescan_loop, detect_hw, discovery_loop):
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


# ───────────────────────────── віддалене керування ─────────────────────────────

class LogTee:
    """Останні рядки консолі — для сторінки «Сервер» на сайті."""
    def __init__(self, n=400):
        self.lines, self.buf, self.lock = collections.deque(maxlen=n), '', threading.Lock()
        self.out = None

    def install(self):
        self.out = sys.stdout
        sys.stdout = sys.stderr = self

    def write(self, s):
        if self.out:
            try:
                self.out.write(s)
            except Exception:
                pass
        with self.lock:
            self.buf += s
            *done, self.buf = self.buf.split('\n')
            stamp = time.strftime('%H:%M:%S')
            self.lines.extend('%s  %s' % (stamp, l) for l in done if l.strip())
        return len(s)

    def flush(self):
        if self.out:
            try:
                self.out.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    def tail(self, n=200):
        with self.lock:
            return list(self.lines)[-n:]


LOG = LogTee()
REPO_ZIP = 'https://github.com/AfricaEE112/hata/archive/refs/heads/main.zip'
ZIP_DIR = 'apps/vidbox/'   # де VidBox лежить у репозиторії Hata
UPDATE_LOCK = threading.Lock()


def battery():
    if os.name == 'nt':
        import ctypes

        class SPS(ctypes.Structure):
            _fields_ = [('ac', ctypes.c_ubyte), ('flag', ctypes.c_ubyte), ('pct', ctypes.c_ubyte),
                        ('saver', ctypes.c_ubyte), ('life', ctypes.c_ulong), ('full', ctypes.c_ulong)]
        st = SPS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)) and st.pct != 255 and st.flag != 128:
            return {'pct': st.pct, 'ac': st.ac == 1}
        return None
    for b in glob.glob('/sys/class/power_supply/BAT*'):
        try:
            pct = int(open(os.path.join(b, 'capacity')).read())
            ac = any(open(a).read().strip() == '1' for a in glob.glob('/sys/class/power_supply/*/online'))
            return {'pct': pct, 'ac': ac}
        except (OSError, ValueError):
            pass
    return None


def git_info():
    d = app_dir()
    if not shutil.which('git') or run(['git', '-C', d, 'rev-parse', '--git-dir'], 10).returncode:
        return None
    try:
        r = run(['git', '-C', d, 'log', '-1', '--format=%h %cI %s'], 10)
        h, date, msg = r.stdout.decode('utf-8', 'replace').strip().split(' ', 2)
        return {'commit': h, 'date': date, 'msg': msg}
    except Exception:
        return None


def media_disks():
    """Вільне місце на дисках з відео й аніме — кожна файлова система один раз (кілька папок можуть бути на одному диску)."""
    seen, free, total = set(), 0, 0
    for root in list(C.roots) + ([C.anime] if C.anime else []):
        try:
            dev = os.stat(root).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            du = shutil.disk_usage(root)
            free, total = free + du.free, total + du.total
        except OSError:
            continue
    return {'free': free, 'total': total, 'count': len(seen)} if seen else None


def admin_json():
    disks = []
    for root in C.roots:
        try:
            du = shutil.disk_usage(root)
            disks.append({'path': root, 'free': du.free, 'total': du.total, 'ok': True})
        except OSError:
            disks.append({'path': root, 'ok': False})
    return {'version': VERSION, 'git': git_info(), 'battery': battery(), 'disks': disks,
            'host': socket.gethostname(), 'os': platform.platform(terse=True),
            'python': platform.python_version(), 'uptime': round(time.time() - STARTED),
            'log': LOG.tail()}


def restart_later(delay=0.6):
    """Новий процес з тими самими аргументами; він дочекається, поки звільниться порт."""
    def go():
        time.sleep(delay)
        if os.environ.get('INVOCATION_ID'):   # під systemd (Hata): служба з Restart=always підніме нас сама
            print('Перезапуск…')
            os._exit(0)
        args = [a for a in sys.argv[1:] if a != '--pick']
        if '--no-browser' not in args:
            args.append('--no-browser')
        cmd = [sys.executable, os.path.abspath(sys.argv[0])] + args
        env = dict(os.environ, VIDBOX_RESTART='1')
        kw = {'start_new_session': True} if os.name != 'nt' else {}
        print('Перезапуск…')
        for p in list(LIVE.values()):
            try:
                p.kill()
            except Exception:
                pass
        subprocess.Popen(cmd, env=env, cwd=os.getcwd(), **kw)
        os._exit(0)
    threading.Thread(target=go, daemon=True).start()


def update_from_github():
    if os.environ.get('VIDBOX_MANAGED') == 'hata':
        return {'ok': False, 'error': 'VidBox оновлюється разом із Hata — кнопка «Оновити» в панелі Hata'}
    d = app_dir()
    if not UPDATE_LOCK.acquire(blocking=False):
        return {'ok': False, 'error': 'Оновлення вже триває'}
    try:
        if git_info():
            r = run(['git', '-C', d, 'pull', '--ff-only', '--autostash'], 120)
            out = (r.stdout + r.stderr).decode('utf-8', 'replace').strip()
            print(out)
            if r.returncode:
                return {'ok': False, 'error': 'git pull не вдався', 'out': out}
            changed = 'Already up to date' not in out and 'Вже оновлено' not in out
            return {'ok': True, 'changed': changed, 'out': out}
        # встановлено з архіву: беремо свіжий zip з GitHub і замінюємо vidbox.py та web/
        print('Завантажую оновлення з GitHub…')
        data = urllib.request.urlopen(REPO_ZIP, timeout=60).read()
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = [n for n in zf.namelist() if not n.endswith('/')]
        prefix = names[0].split('/', 1)[0] + '/'
        prefix += ZIP_DIR
        files = {n[len(prefix):]: n for n in names if n.startswith(prefix)
                 and (n[len(prefix):] == 'vidbox.py' or n[len(prefix):].startswith('web/'))}
        if 'vidbox.py' not in files:
            return {'ok': False, 'error': 'В архіві немає vidbox.py'}
        compile(zf.read(files['vidbox.py']), 'vidbox.py', 'exec')   # битий файл не ставимо
        shutil.copy2(os.path.join(d, 'vidbox.py'), os.path.join(d, 'vidbox.py.bak'))
        for rel, n in files.items():
            dst = os.path.join(d, *rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst + '.new', 'wb') as f:
                f.write(zf.read(n))
            os.replace(dst + '.new', dst)
        print('Оновлено %d файлів (стара версія — vidbox.py.bak).' % len(files))
        return {'ok': True, 'changed': True, 'out': 'Оновлено %d файлів' % len(files)}
    except Exception as e:
        print('Оновлення не вдалося:', e)
        return {'ok': False, 'error': str(e)}
    finally:
        UPDATE_LOCK.release()


# ───────────────────────────── сторінки ─────────────────────────────

LOGIN_HTML = '''<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
<title>VidBox — вхід</title><style>
@font-face{font-family:'DejaVu Sans Mono';src:url(/fonts/dejavu-sans-mono.woff) format('woff')}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f1420;color:#ede6d8;
font:16px "Segoe UI",system-ui,-apple-system,Roboto,sans-serif}form{display:flex;flex-direction:column;gap:12px;width:280px}
h1{margin:0 0 10px;font:400 28px 'DejaVu Sans Mono',Consolas,monospace}h1 span{color:#1793d1}input,button{font:inherit;padding:12px 14px;border-radius:10px;border:0}
input{background:#1f2839;color:#ede6d8;outline:none}input:focus{box-shadow:0 0 0 2px #f2b544}
button{background:#f2b544;color:#1c1508;font-weight:600;cursor:pointer}.err{color:#ff8a7a;margin:0;font-size:14px}
</style></head><body><form method="post" action="/login"><h1><span>▶_</span> vidbox</h1>{err}
<input type="password" name="p" placeholder="Пароль" autofocus aria-label="Пароль"><button>Увійти</button></form></body></html>'''

WEB_TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
             '.js': 'text/javascript; charset=utf-8', '.woff': 'font/woff', '.woff2': 'font/woff2',
             '.png': 'image/png', '.svg': 'image/svg+xml', '.jpg': 'image/jpeg', '.ico': 'image/x-icon'}

if __name__ == '__main__':
    main()
