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
import csv
import glob
import io
import urllib.request
import zipfile
import datetime
import difflib
import hashlib
import html
import html.parser
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
CREATE TABLE IF NOT EXISTS manga_progress(cid TEXT PRIMARY KEY, tid TEXT, page INTEGER, pages INTEGER,
  at REAL, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS manga_seen(cid TEXT PRIMARY KEY, tid TEXT, first REAL);
CREATE TABLE IF NOT EXISTS manga_titles(tid TEXT PRIMARY KEY, mode TEXT, hint TEXT);
CREATE TABLE IF NOT EXISTS anime_titles(sid TEXT PRIMARY KEY, hint TEXT);
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
        manga_scan_bg()
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
    info['hint'] = anilist_hint(series[key][0], key) if series[key][0] else ''
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
                  'description(asHtml:false) genres seasonYear episodes averageScore format isAdult')
SEASON_RE = re.compile(r'\b(s\d{1,2}|season\s*\d+|\d+(st|nd|rd|th)\s*season|part\s*\d+|сезон\s*\d+|\d+\s*сезон|tv|complete)\b', re.I)


def anilist_dir():
    return os.path.join(C.data, 'anime')


def anilist_meta(sid):
    try:
        with open(os.path.join(anilist_dir(), sid + '.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def anilist_hint(top, sid=None):
    """Посилання чи назва, яку вставили на сторінці тайтлу; інакше — anilist.txt у теці."""
    sid = sid or hashlib.sha1(('anime:' + top).encode('utf-8', 'surrogateescape')).hexdigest()[:12]
    r = DB.one('SELECT hint FROM anime_titles WHERE sid=?', (sid,)) if DB else None
    if r and r['hint']:
        return r['hint']
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
    hint = anilist_hint(top, sid)
    if m and m.get('v') == ANILIST_V and m.get('hint', '') == hint and (m.get('id') or time.time() - m.get('at', 0) < 7 * 86400):
        return
    meta_queue(sid, anime_title(top), anilist_fetch, sid, top)


def meta_queue(key, label, fn, *args):
    """Спільна черга AniList для аніме й манги: ліміт запитів один на всіх."""
    if time.time() - ANILIST_FAIL.get(key, 0) < 600:
        return
    with ANILIST_LOCK:
        if key in ANILIST_PENDING:
            return
        ANILIST_PENDING.add(key)
        start = not getattr(meta_queue, 'worker', None)
        if start:
            meta_queue.worker = threading.Thread(target=anilist_worker, daemon=True)
    ANILIST_Q.put((key, label, fn, args))
    if start:
        meta_queue.worker.start()


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


def anime_link(hint):
    """Посилання → як шукати: ('id'|'mal', номер) для AniList, ('web', url) для інших сайтів, None — це назва."""
    h = (hint or '').strip()
    m = re.search(r'anilist\.co/anime/(\d+)', h)
    if m:
        return 'id', int(m.group(1))
    m = re.search(r'myanimelist\.net/anime/(\d+)', h) or re.search(r'shikimori\.[a-z]+/animes/[a-z]*(\d+)', h)
    if m:                                  # у Shikimori ті самі номери, що в MyAnimeList
        return 'mal', int(m.group(1))
    if re.match(r'https?://', h, re.I):
        return 'web', h
    if h.isdigit():
        return 'id', int(h)
    return None


def anilist_fetch(sid, top):
    d = anilist_dir()
    os.makedirs(d, exist_ok=True)
    media, used, web = None, '', None
    hint = anilist_hint(top, sid)
    link = anime_link(hint)
    if link and link[0] == 'web':
        web, used = web_meta(link[1]), link[1]
    for q in ([] if link and link[0] == 'web' else [link] if link else anilist_queries(top)):
        used = q if isinstance(q, str) else '%s:%s' % q
        if isinstance(q, tuple):
            res = anilist_post('query($i:Int){Media(%s:$i,type:ANIME){%s}}' % ('idMal' if q[0] == 'mal' else 'id', ANILIST_FIELDS),
                               {'i': q[1]})
        elif q.isdigit():
            res = anilist_post('query($i:Int){Media(id:$i,type:ANIME){%s}}' % ANILIST_FIELDS, {'i': int(q)})
        else:
            res = anilist_post('query($s:String){Media(search:$s,type:ANIME,sort:SEARCH_MATCH){%s}}' % ANILIST_FIELDS, {'s': q})
        media = (res.get('data') or {}).get('Media')
        time.sleep(2.2)
        if media:
            break
    meta = {'v': ANILIST_V, 'at': time.time(), 'q': used, 'hint': hint}
    cover = os.path.join(d, sid + '.jpg')
    if web:
        img = None
        if web.get('image'):
            try:
                req = urllib.request.Request(web['image'], headers={'User-Agent': 'Mozilla/5.0 (VidBox/%s)' % VERSION,
                                                                    'Referer': web['url']})
                with urllib.request.urlopen(req, timeout=30) as r:
                    img = r.read(20 << 20)
            except (OSError, ValueError) as e:
                print('AniList: постер з %s не завантажив (%s)' % (web['image'], e))
        if img and (img[:3] in (b'\xff\xd8\xff', b'\x89PN', b'RIF', b'GIF') or img[4:12] in (b'ftypavif', b'ftypavis')):
            with open(cover + '.part', 'wb') as f:
                f.write(img)
            os.replace(cover + '.part', cover)
        elif os.path.isfile(cover):
            os.remove(cover)
        meta.update({k: web.get(k) for k in ('src', 'site', 'id', 'url', 'romaji', 'year', 'genres', 'desc')})
        print('Аніме: «%s» → %s (%s)' % (anime_title(top), web.get('romaji'), web.get('site')))
    elif media:
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
                    desc=desc, color=(media.get('coverImage') or {}).get('color'), adult=bool(media.get('isAdult')))
        print('AniList: «%s» → %s' % (anime_title(top), t.get('romaji') or t.get('english')))
    else:
        meta['none'] = True
        print('AniList: «%s» не знайдено (шукав: %s). Встав посилання на сторінці тайтлу' % (anime_title(top), used))
    with open(os.path.join(d, sid + '.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)


def anilist_worker():
    while True:
        key, label, fn, args = ANILIST_Q.get()
        try:
            fn(*args)
        except Exception as e:
            ANILIST_FAIL[key] = time.time()
            print('Метадані: не вдалося для «%s» (%s)' % (label, e))
            time.sleep(5)
        finally:
            with ANILIST_LOCK:
                ANILIST_PENDING.discard(key)


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
                                  'format', 'genres', 'desc', 'color', 'src', 'site')}


# ───────────────────────────── манга ─────────────────────────────
# Окрема папка: кожна підпапка (або .zip/.cbz) — тайтл. Картинки прямо в теці тайтлу — одна «книжка»;
# підтеки й архіви всередині — розділи. Нічого не копіюється: сторінки віддаються прямо з диска.
# Обкладинка: cover.jpg у теці → AniList → MangaUpdates → перша сторінка.

IMG_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
             '.gif': 'image/gif', '.avif': 'image/avif', '.bmp': 'image/bmp', '.jxl': 'image/jxl'}
ARC_EXT = {'.zip', '.cbz'}
COVER_NAMES = ('cover', 'poster', 'folder')
MANGA_MODES = {'rtl', 'ltr', 'strip', 'spread'}
MANGA = {'root': '', 'titles': {}, 'chapters': {}, 'at': 0, 'scanning': False}
MANGA_LOCK = threading.Lock()
MANGA_META_V = 1
ZIPS = collections.OrderedDict()
ZIPS_LOCK = threading.Lock()
THUMB_SEM = threading.Semaphore(2)


def manga_skip(name):
    return name.startswith(('.', '$', '._')) or name.lower() in SKIP_DIRS or name == '__MACOSX'


def manga_id(*parts):
    return hashlib.sha1('\x00'.join(parts).encode('utf-8', 'surrogateescape')).hexdigest()


def manga_title(top):
    stem = os.path.splitext(top)[0] if os.path.splitext(top)[1].lower() in ARC_EXT else top
    t = anime_title(stem)
    t = re.sub(r'\(\s*(digital|raw|eng|jp|jpn|complete|completed|ongoing|(19|20)\d\d)\s*\)', ' ', t, flags=re.I)
    return re.sub(r'\s{2,}', ' ', t).strip(' -.') or stem


CH_RE = re.compile(r'(?:^|[\s_.\-\[(#])(?:ch(?:apter|ap)?|гл(?:ава)?|розділ|раздел|episode|ep|第)\.?\s*_?(\d+(?:[.,]\d+)?)', re.I)
VOL_RE = re.compile(r'(?:^|[\s_.\-\[(])(?:vol(?:ume)?|v|том|т)\.?\s*_?(\d+)', re.I)


def manga_label(name):
    """«Vol.02 Ch.012 - Назва» → ('Том 2 · Глава 12', '12', 'Назва'). Повертає (підпис, номер, підзаголовок)."""
    base = re.sub(r'\.(zip|cbz)$', '', name.strip(), flags=re.I)
    num = lambda s: re.sub(r'^0+(?=\d)', '', s.replace(',', '.'))
    ch, vol = CH_RE.search(base), VOL_RE.search(base)
    if re.fullmatch(r'\s*\d+(?:[.,]\d+)?\s*', base):
        return 'Глава ' + num(base.strip()), num(base.strip()), ''
    if ch:
        rest = re.sub(r'^[話话回]', '', base[ch.end():]).strip(' -_.:—–)]/')
        lab = ('Том %s · ' % num(vol.group(1)) if vol and vol.start() < ch.start() else '') + 'Глава ' + num(ch.group(1))
        return lab, num(ch.group(1)), rest
    if vol:
        rest = base[vol.end():].strip(' -_.:—–)]/')
        return 'Том ' + num(vol.group(1)), num(vol.group(1)), rest
    return clean_title(base), None, ''


def manga_chapter_label(rel, name, prefix=''):
    """Підпис з усього шляху: «Vol 1/Ch 3.cbz» → «Том 1 · Глава 3». prefix — назва теки-тому, коли томи зібрано в один тайтл."""
    full = re.sub(r'\.(zip|cbz)(?=$|[/\\!])', '', rel, flags=re.I).replace('!', '/').replace('\\', '/')
    parts = ([prefix] if prefix else []) + [x for x in full.split('/') if x]
    if not parts:
        return '', None, ''
    label, n, sub = manga_label(' / '.join(parts))
    if not n and name:
        label, n, sub = manga_label(name)
    return label, n, sub


def manga_chapter(top, rel, kind, path, pages, name):
    pages.sort(key=nat_key)
    label, n, sub = manga_chapter_label(rel, name)
    return {'cid': manga_id('manga', top, rel)[:16], 'rel': rel, 'kind': kind, 'path': path, 'pages': pages,
            'label': label, 'num': n, 'sub': sub, 'name': name}


def manga_zip_chapters(zpath, top, rel):
    with zipfile.ZipFile(zpath) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
    groups = {}
    for n in names:
        parts = n.replace('\\', '/').split('/')
        if any(manga_skip(p) for p in parts) or os.path.splitext(n)[1].lower() not in IMG_TYPES:
            continue
        groups.setdefault('/'.join(parts[:-1]), []).append(n)
    if len(groups) > 1 and len(groups.get('', [])) <= 3:
        groups.pop('', None)       # обкладинка поруч із розділами
    stem = os.path.splitext(os.path.basename(zpath))[0]
    out = []
    for g, pages in groups.items():
        name = g.split('/')[-1] if g else (stem if rel else '')
        out.append(manga_chapter(top, rel + ('!' + g if g else ''), 'zip', zpath, pages, name))
    return out


def manga_dir_chapters(tdir, top):
    out = []

    def walk(d, rel, depth):
        imgs, subs, arcs = [], [], []
        with os.scandir(d) as it:
            for e in it:
                if manga_skip(e.name):
                    continue
                try:
                    if e.is_dir():
                        subs.append(e)
                        continue
                except OSError:
                    continue
                ext = os.path.splitext(e.name)[1].lower()
                if ext in IMG_TYPES:
                    imgs.append(e.name)
                elif ext in ARC_EXT:
                    arcs.append(e)
        if rel == '' and imgs:
            if subs or arcs:       # у корені поруч із розділами — обкладинка чи титулка
                imgs = imgs if len(imgs) > 3 else []
            else:
                imgs = [n for n in imgs if os.path.splitext(n)[0].lower() not in COVER_NAMES] or imgs
        if imgs:
            out.append(manga_chapter(top, rel, 'dir', d, imgs, os.path.basename(d) if rel else ''))
        for a in arcs:
            try:
                out.extend(manga_zip_chapters(a.path, top, os.path.join(rel, a.name)))
            except (OSError, zipfile.BadZipFile) as err:
                print('Манга: не вдалося відкрити архів %s (%s)' % (a.path, err))
        if depth < 5:
            for s in subs:
                walk(s.path, os.path.join(rel, s.name), depth + 1)
    walk(tdir, '', 0)
    out.sort(key=lambda c: nat_key(c['rel']))
    return out


SERIES_NUM_RE = re.compile(r'(?:^|(?<=[\s_.\-\[(]))(?:vol(?:ume)?s?|v|tome|том|т|ch(?:apter)?|глава|розділ|part|#)\.?\s*_?\d+(?:[.,]\d+)?(?:\s*-\s*\d+)?\b'
                           r'|第\s*\d+\s*[巻卷話话]', re.I)


def manga_series_key(top):
    """«Yo-Shu Tamagotei Vol. 03 - Spring Strawberry Vol. 1» → «yoshutamagoteispringstrawberry» (і «Berserk» з «Berserk v02»)."""
    t = manga_title(top)
    stripped = SERIES_NUM_RE.sub(' ', t)
    if stripped == t:
        stripped = re.sub(r'(?<=\D)\s+\d{1,3}\s*$', ' ', t)     # «Назва 03»
    return norm_title(stripped)


def manga_series_title(items):
    t = SERIES_NUM_RE.sub(' ', manga_title(items[0][0]))
    t = re.sub(r'(?<=\D)\s+\d{1,3}\s*$', ' ', t)
    t = re.sub(r'\s*[-–—:]\s*(?=[-–—:]|$)', ' ', t)
    return re.sub(r'\s{2,}', ' ', t).strip(' -–—:.,') or manga_title(items[0][0])


def manga_scan():
    """Переглядає папку манги й будує покажчик тайтлів і розділів (у пам'яті, без копіювання)."""
    global MANGA
    root = C.cfg.get('manga_folder') or ''
    if not root or not os.path.isdir(root):
        MANGA = {'root': root, 'titles': {}, 'chapters': {}, 'at': time.time(), 'scanning': False, 'missing': bool(root)}
        return
    with MANGA_LOCK:
        MANGA['scanning'] = True
        t0 = time.time()
        titles, chapters, found = {}, {}, []
        try:
            entries = sorted(os.scandir(root), key=lambda e: nat_key(e.name))
        except OSError as e:
            print('Манга: немає доступу до %s (%s)' % (root, e))
            entries = []
        for e in entries:
            if manga_skip(e.name):
                continue
            try:
                if e.is_dir():
                    chs = manga_dir_chapters(e.path, e.name)
                elif os.path.splitext(e.name)[1].lower() in ARC_EXT:
                    chs = manga_zip_chapters(e.path, e.name, '')
                else:
                    continue
            except (OSError, zipfile.BadZipFile) as err:
                print('Манга: пропускаю «%s» (%s)' % (e.name, err))
                continue
            if not chs:
                continue
            found.append((e.name, e.path, e.is_dir(), chs))
        # теки-томи одного тайтлу («Назва Vol. 03», «Назва Vol. 04») — в один тайтл, томи стають розділами.
        # id розділів не змінюються, тож прогрес читання лишається.
        groups = {}
        for item in found:
            groups.setdefault(manga_series_key(item[0]) or '\x00' + item[0], []).append(item)
        for key, items in groups.items():
            if len(items) > 1:
                tid = manga_id('mangas', key)[:12]
                chs = []
                for name, path, isdir, part in items:
                    for c in part:
                        c['label'], c['num'], c['sub'] = manga_chapter_label(c['rel'], c['name'], prefix=name)
                        c['vol'] = name
                    chs += part
                name, path, isdir = manga_series_title(items), items[0][1], items[0][2]
            else:
                name, path, isdir, chs = items[0]
                tid = manga_id('mangat', name)[:12]
            for c in chs:
                c['tid'] = tid
                chapters[c['cid']] = c
            titles[tid] = {'tid': tid, 'top': name, 'path': path, 'isdir': isdir, 'parts': len(items),
                           'title': manga_title(name) if len(items) == 1 else name, 'chapters': [c['cid'] for c in chs]}
        seen = {r['cid']: r['first'] for r in DB.q('SELECT cid, first FROM manga_seen')}
        known = {r['tid'] for r in DB.q('SELECT DISTINCT tid FROM manga_seen')}
        now, new = time.time(), []
        for cid, c in chapters.items():
            if cid not in seen:
                # перше сканування й нові тайтли — не «нові розділи», інакше нове було б усе
                seen[cid] = now if (seen and c['tid'] in known) else 0
                new.append((cid, c['tid'], seen[cid]))
            c['first'] = seen[cid]
        if new:
            DB.many('INSERT OR IGNORE INTO manga_seen(cid, tid, first) VALUES(?,?,?)', new)
        MANGA = {'root': root, 'titles': titles, 'chapters': chapters, 'at': time.time(), 'scanning': False}
        with ZIPS_LOCK:
            for z in ZIPS.values():
                z.close()
            ZIPS.clear()
        print('Манга: %d тайтлів, %d розділів, %d сторінок (%.1f с)' % (
            len(titles), len(chapters), sum(len(c['pages']) for c in chapters.values()), time.time() - t0))


def manga_scan_bg():
    def go():
        try:
            manga_scan()
        except Exception:
            traceback.print_exc()
    threading.Thread(target=go, daemon=True).start()


def manga_dir():
    return os.path.join(C.data, 'manga')


def manga_settings():
    return {r['tid']: r for r in DB.q('SELECT * FROM manga_titles')}


def manga_set(tid, **kw):
    DB.x('INSERT OR IGNORE INTO manga_titles(tid) VALUES(?)', (tid,))
    for k, v in kw.items():
        DB.x('UPDATE manga_titles SET %s=? WHERE tid=?' % k, (v, tid))


def manga_progress():
    return {r['cid']: r for r in DB.q('SELECT * FROM manga_progress')}


def manga_cover_file(t):
    if t['isdir']:
        for name in COVER_NAMES:
            for ext in ('.jpg', '.jpeg', '.png', '.webp'):
                f = os.path.join(t['path'], name + ext)
                if os.path.isfile(f):
                    return f
    for f in (os.path.join(manga_dir(), t['tid'] + '.jpg'), os.path.join(manga_dir(), 'thumbs', t['tid'] + '.jpg')):
        if os.path.isfile(f):
            return f
    return None


def manga_info(t, idx, prog, sets):
    chs = [idx['chapters'][c] for c in t['chapters']]
    done = lambda c: bool(prog.get(c['cid']) and prog[c['cid']]['done'])
    started = [c for c in chs if c['cid'] in prog]
    last = max(started, key=lambda c: prog[c['cid']]['at']) if started else None
    last_at = prog[last['cid']]['at'] if last else 0
    start_at = min(prog[c['cid']]['at'] for c in started) if started else 0
    cont = None
    if last:
        p = prog[last['cid']]
        if not p['done']:
            cont = (last, max(1, p['page'] or 1))
        else:
            i = chs.index(last)
            nxt = next((c for c in chs[i + 1:] if not done(c)), None)
            cont = (nxt, max(1, prog[nxt['cid']]['page'] or 1) if nxt['cid'] in prog else 1) if nxt else None
    read = sum(done(c) for c in chs)
    f = manga_cover_file(t)
    s = sets.get(t['tid'])
    return {'tid': t['tid'], 'title': t['title'], 'n': len(chs), 'pages': sum(len(c['pages']) for c in chs),
            'single': len(chs) == 1, 'read': read, 'lastAt': last_at, 'vols': t.get('parts', 1) > 1 and len(chs) == t['parts'],
            # нові — ті, що з'явились у папці вже після того, як почав читати, і ще не прочитані
            'new': sum(1 for c in chs if start_at and c['first'] > start_at and not done(c)), 'startAt': start_at,
            'added': max((c['first'] for c in chs), default=0),
            'mode': (s['mode'] if s and s['mode'] in MANGA_MODES else 'rtl'),
            'cover': '/manga/cover/%s?v=%d' % (t['tid'], int(os.path.getmtime(f)) if f else 0),
            'meta': manga_meta_public(t['tid']),
            'cont': cont and {'cid': cont[0]['cid'], 'label': cont[0]['label'], 'page': cont[1],
                              'pages': len(cont[0]['pages'])}}


def manga_list_json():
    idx = MANGA
    prog, sets = manga_progress(), manga_settings()
    for t in idx['titles'].values():
        manga_want(t, sets.get(t['tid']))
    out = [manga_info(t, idx, prog, sets) for t in idx['titles'].values()]
    return {'folder': idx['root'], 'missing': idx.get('missing', False), 'scanning': idx.get('scanning', False),
            'titles': out, 'chapters': len(idx['chapters'])}


def manga_title_json(tid):
    idx = MANGA
    t = idx['titles'].get(tid)
    if not t:
        return None
    prog, sets = manga_progress(), manga_settings()
    info = manga_info(t, idx, prog, sets)
    start_at = info['startAt']
    info['chapters'] = [{'cid': c['cid'], 'label': c['label'] or t['title'], 'sub': c['sub'], 'name': c['name'],
                         'pages': len(c['pages']), 'page': prog[c['cid']]['page'] if c['cid'] in prog else 0,
                         'done': bool(c['cid'] in prog and prog[c['cid']]['done']),
                         'new': bool(start_at and c['first'] > start_at), 'added': c['first']}
                        for c in (idx['chapters'][x] for x in t['chapters'])]
    s = sets.get(tid)
    info['hint'] = (s['hint'] if s else '') or ''
    info['reset'] = info['hint'] == RESET_HINT
    if info['reset']:
        info['hint'] = ''
    info['folder'] = t['top']
    return info


def manga_chapter_json(cid):
    idx = MANGA
    c = idx['chapters'].get(cid)
    if not c:
        return None
    t = idx['titles'][c['tid']]
    i = t['chapters'].index(cid)
    p = DB.one('SELECT * FROM manga_progress WHERE cid=?', (cid,))
    s = DB.one('SELECT mode FROM manga_titles WHERE tid=?', (t['tid'],))
    near = lambda j: (lambda x: {'cid': x['cid'], 'label': x['label'] or t['title'], 'pages': len(x['pages'])})(
        idx['chapters'][t['chapters'][j]]) if 0 <= j < len(t['chapters']) else None
    return {'cid': cid, 'tid': t['tid'], 'title': t['title'], 'label': c['label'] or t['title'], 'sub': c['sub'],
            'pages': len(c['pages']), 'page': (p['page'] if p else 0) or 0, 'done': bool(p and p['done']),
            'mode': s['mode'] if s and s['mode'] in MANGA_MODES else 'rtl',
            'index': i, 'count': len(t['chapters']), 'prev': near(i - 1), 'next': near(i + 1)}


def manga_save_progress(d):
    cid = str(d.get('cid', ''))
    c = MANGA['chapters'].get(cid)
    if not c:
        return {'ok': False}
    n = len(c['pages'])
    try:
        page = max(1, min(n, int(d.get('page') or 1)))
    except (TypeError, ValueError):
        page = 1
    done = 1 if (d.get('done') or page >= n) else 0
    DB.x('''INSERT INTO manga_progress(cid, tid, page, pages, at, done) VALUES(?,?,?,?,?,?)
            ON CONFLICT(cid) DO UPDATE SET page=excluded.page, pages=excluded.pages, at=excluded.at,
              done=MAX(manga_progress.done, excluded.done)''', (cid, c['tid'], page, n, time.time(), done))
    return {'ok': True, 'done': bool(done)}


def manga_mark(d):
    cids = [c for c in (d.get('cids') or []) if isinstance(c, str) and c in MANGA['chapters']]
    if d.get('read'):
        now = time.time()
        DB.many('''INSERT INTO manga_progress(cid, tid, page, pages, at, done) VALUES(?,?,?,?,?,1)
                   ON CONFLICT(cid) DO UPDATE SET page=excluded.page, pages=excluded.pages, done=1''',
                [(c, MANGA['chapters'][c]['tid'], len(MANGA['chapters'][c]['pages']),
                  len(MANGA['chapters'][c]['pages']), now - 1e-3 * i) for i, c in enumerate(reversed(cids))])
    else:
        DB.many('DELETE FROM manga_progress WHERE cid=?', [(c,) for c in cids])
    return {'ok': True}


# ── сторінки ──

def manga_zip_read(path, name):
    """Відкриті архіви тримаємо кілька штук, щоб не читати їхній зміст на кожну сторінку."""
    with ZIPS_LOCK:
        z = ZIPS.pop(path, None)
        if z is None:
            z = zipfile.ZipFile(path)
        ZIPS[path] = z
        while len(ZIPS) > 6:
            ZIPS.popitem(last=False)[1].close()
        return z.read(name)


def manga_page(c, n):
    """(шлях або None, байти або None, тип) для сторінки n (з 1)."""
    name = c['pages'][n - 1]
    ctype = IMG_TYPES.get(os.path.splitext(name)[1].lower(), 'application/octet-stream')
    if c['kind'] == 'dir':
        return os.path.join(c['path'], name), None, ctype
    return None, manga_zip_read(c['path'], name), ctype


def manga_thumb(t):
    """Обкладинка з першої сторінки (якщо немає cover.jpg і метаданих): зменшена копія в кеші."""
    out = os.path.join(manga_dir(), 'thumbs', t['tid'] + '.jpg')
    if os.path.isfile(out):
        return out
    c = MANGA['chapters'].get(t['chapters'][0])
    if not c:
        return None
    os.makedirs(os.path.dirname(out), exist_ok=True)
    path, data, _ = manga_page(c, 1)
    with THUMB_SEM:
        try:
            from PIL import Image   # якщо є Pillow — швидше й без ffmpeg
            im = Image.open(path or io.BytesIO(data))
            im = im.convert('RGB')
            im.thumbnail((480, 720))
            im.save(out + '.part.jpg', 'JPEG', quality=84)
            os.replace(out + '.part.jpg', out)
            return out
        except Exception:
            pass
        if not C.ffmpeg:
            return None
        src = path
        if data is not None:
            src = out + '.src' + os.path.splitext(c['pages'][0])[1].lower()
            with open(src, 'wb') as f:
                f.write(data)
        try:
            r = run([C.ffmpeg, '-v', 'error', '-y', '-i', src, '-vf', 'scale=480:-2', '-frames:v', '1', '-q:v', '4',
                     out + '.part.jpg'], 60)
            if r.returncode == 0 and os.path.isfile(out + '.part.jpg'):
                os.replace(out + '.part.jpg', out)
                return out
        except Exception:
            pass
        finally:
            if data is not None:
                try:
                    os.remove(src)
                except OSError:
                    pass
    return None


# ── метадані: AniList, потім MangaUpdates ──

def manga_meta(tid):
    try:
        with open(os.path.join(manga_dir(), tid + '.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def manga_meta_public(tid):
    m = manga_meta(tid)
    if not m or not m.get('id'):
        return None
    return {k: m.get(k) for k in ('src', 'id', 'url', 'romaji', 'english', 'native', 'alt', 'year', 'chapters',
                                  'volumes', 'score', 'format', 'status', 'genres', 'desc', 'color', 'site',
                                  'artists', 'series', 'characters', 'lang')}


def manga_hint(t, s):
    h = (s['hint'] if s else '') or ''
    if not h and t['isdir']:
        for n in ('anilist.txt', 'mangaupdates.txt'):
            try:
                with open(os.path.join(t['path'], n), encoding='utf-8-sig') as f:
                    h = f.read().strip()
                    if n == 'mangaupdates.txt' and h.isdigit():
                        h = 'mu:' + h
                    break
            except OSError:
                pass
    return h


RESET_HINT = '-'     # дані скинуто вручну: не шукати, обкладинка — перша сторінка


def manga_reset(d):
    """Скинути опис і обкладинку з інтернету: для одного тайтлу ({tid}) або для всіх ({all: true})."""
    tids = list(MANGA['titles']) if d.get('all') else [str(d.get('tid', ''))]
    tids = [t for t in tids if t in MANGA['titles']]
    if not tids:
        return {'ok': False, 'error': 'Тайтл не знайдено'}
    for tid in tids:
        manga_set(tid, hint=RESET_HINT)
        for f in (tid + '.json', tid + '.jpg'):
            try:
                os.remove(os.path.join(manga_dir(), f))
            except OSError:
                pass
        ANILIST_FAIL.pop('m:' + tid, None)
    print('Манга: скинуто дані для %d %s' % (len(tids), 'тайтлів' if len(tids) > 1 else 'тайтлу'))
    return {'ok': True, 'n': len(tids)}


def manga_want(t, s, force=False):
    hint = manga_hint(t, s)
    if hint == RESET_HINT:
        return
    m = manga_meta(t['tid'])
    if not force and m and m.get('v') == MANGA_META_V and m.get('hint', '') == hint and \
            (m.get('id') or time.time() - m.get('at', 0) < 7 * 86400):
        return
    meta_queue('m:' + t['tid'], t['title'], manga_fetch, t['tid'], t['title'], hint)


def html_text(s):
    s = re.sub(r'<br\s*/?>', '\n', s or '', flags=re.I)
    s = html.unescape(re.sub(r'<[^>]+>', '', s))
    return re.sub(r'\n{3,}', '\n\n', s.replace('\r', '')).strip()


def norm_title(s):
    return re.sub(r'[^0-9a-zа-яіїєґ぀-ヿ一-鿿]+', '', (s or '').lower())


def title_close(q, names):
    a = norm_title(q)
    if not a:
        return False
    for n in names:
        b = norm_title(n)
        if b and (a == b or (len(a) > 4 and (a in b or b in a)) or difflib.SequenceMatcher(None, a, b).ratio() >= 0.6):
            return True
    return False


MANGA_AL_FIELDS = ('id siteUrl title{romaji english native} synonyms coverImage{extraLarge large color} '
                   'description(asHtml:false) genres startDate{year} chapters volumes averageScore format status')


def anilist_manga(search=None, mid=None):
    if mid:
        res = anilist_post('query($i:Int){Media(id:$i,type:MANGA){%s}}' % MANGA_AL_FIELDS, {'i': mid})
    else:
        res = anilist_post('query($s:String){Media(search:$s,type:MANGA,format_not:NOVEL,sort:SEARCH_MATCH){%s}}'
                           % MANGA_AL_FIELDS, {'s': search})
    m = (res.get('data') or {}).get('Media')
    if not m:
        return None
    t = m.get('title') or {}
    if search and not title_close(search, [t.get('romaji'), t.get('english'), t.get('native')] + (m.get('synonyms') or [])):
        print('Манга: AniList запропонував «%s» для «%s» — не схоже, шукаю далі' % (t.get('romaji'), search))
        return None
    cov = m.get('coverImage') or {}
    return {'src': 'anilist', 'id': m.get('id'), 'url': m.get('siteUrl'), 'romaji': t.get('romaji'),
            'english': t.get('english'), 'native': t.get('native'), 'alt': (m.get('synonyms') or [])[:4],
            'year': (m.get('startDate') or {}).get('year'), 'chapters': m.get('chapters'), 'volumes': m.get('volumes'),
            'score': m.get('averageScore'), 'format': m.get('format'), 'status': m.get('status'),
            'genres': m.get('genres') or [], 'desc': html_text(m.get('description')), 'color': cov.get('color'),
            'image': cov.get('extraLarge') or cov.get('large')}


def mu_req(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(3):
        req = urllib.request.Request('https://api.mangaupdates.com/v1' + path, data=data, method='POST' if data else 'GET',
                                     headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                                              'User-Agent': 'VidBox/%s (+https://github.com/AfricaEE112/hata)' % VERSION})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(min(int(e.headers.get('Retry-After') or 30), 120) + 1)
                continue
            if e.code == 404:
                return None
            raise
    raise RuntimeError('MangaUpdates не відповідає (ліміт запитів)')


def mu_series(sid):
    r = mu_req('/series/%d' % sid)
    if not r or not r.get('series_id'):
        return None
    alt = [a.get('title') for a in (r.get('associated') or []) if a.get('title')]
    native = next((a for a in alt if re.search(r'[぀-ヿ一-鿿]', a)), None)
    img = ((r.get('image') or {}).get('url') or {})
    try:
        year = int(str(r.get('year') or '')[:4])
    except ValueError:
        year = None
    rating = r.get('bayesian_rating') or 0
    return {'src': 'mangaupdates', 'id': r.get('series_id'), 'url': r.get('url'), 'romaji': r.get('title'),
            'english': None, 'native': native, 'alt': [a for a in alt if a != native][:4], 'year': year,
            'chapters': None, 'volumes': None, 'score': round(rating * 10) if rating else None,
            'format': r.get('type'), 'status': html_text(r.get('status') or '') or None,
            'genres': [g.get('genre') for g in (r.get('genres') or []) if g.get('genre')],
            'desc': html_text(r.get('description')), 'color': None, 'image': img.get('original') or img.get('thumb')}


def mu_search(q):
    r = mu_req('/series/search', {'search': q, 'perpage': 8}) or {}
    for hit in r.get('results') or []:
        rec = hit.get('record') or {}
        if (rec.get('type') or '').lower() in ('novel', 'artbook'):
            continue
        if title_close(q, [rec.get('title'), hit.get('hit_title')]):
            time.sleep(1)
            return mu_series(int(rec['series_id']))
    return None


def hitomi_gallery(gid):
    """Hitomi: дані галереї за номером (той самий файл, що читає сам сайт). Обкладинку не беремо —
    її адреса шифрується скриптом сайту; перша сторінка в теці й так зазвичай обкладинка."""
    req = urllib.request.Request('https://ltn.gold-usergeneratedcontent.net/galleries/%d.js' % gid, headers={
        'Referer': 'https://hitomi.la/', 'User-Agent': 'Mozilla/5.0 (VidBox/%s)' % VERSION})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(4 << 20).decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    g = json.loads(raw[raw.index('{'):].rstrip().rstrip(';'))
    names = lambda key, one: [x.get(one) for x in (g.get(key) or []) if x.get(one)]
    tags = []
    for t in g.get('tags') or []:
        if t.get('tag'):
            tags.append(('♀ ' if t.get('female') in (1, '1', True) else '♂ ' if t.get('male') in (1, '1', True) else '') + t['tag'])
    try:
        year = int(str(g.get('datepublished') or g.get('date') or '')[:4]) or None
    except ValueError:
        year = None
    return {'src': 'hitomi', 'id': gid, 'url': 'https://hitomi.la/galleries/%d.html' % gid, 'romaji': g.get('title'),
            'english': None, 'native': g.get('japanese_title'), 'alt': [], 'year': year, 'chapters': None, 'volumes': None,
            'score': None, 'format': g.get('type'), 'status': None, 'genres': tags[:40], 'desc': '', 'color': None,
            'artists': names('artists', 'artist') + names('groups', 'group'), 'series': names('parodys', 'parody'),
            'characters': names('characters', 'character')[:12], 'lang': g.get('language_localname') or g.get('language'),
            'image': None}


class _MetaParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.title, self._t = {}, '', False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta':
            k = (a.get('property') or a.get('name') or '').lower()
            if k and a.get('content') and k not in self.meta:
                self.meta[k] = a['content']
        elif tag == 'title':
            self._t = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self._t = False

    def handle_data(self, d):
        if self._t:
            self.title += d


def web_meta(url):
    """Будь-який сайт (OpenHentai тощо): назва, картинка, опис і ключові слова з метатегів сторінки."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) VidBox/%s' % VERSION,
                                               'Accept': 'text/html', 'Cookie': 'disclaimer=1; age_verified=1; adult=1'})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read(3 << 20)
        cs = r.headers.get_content_charset() or 'utf-8'
    p = _MetaParser()
    p.feed(body.decode(cs, 'replace'))
    m = p.meta
    title = (m.get('og:title') or m.get('twitter:title') or p.title or '').strip()
    site = (m.get('og:site_name') or '').strip()
    title = re.sub(r'\s*[|\-–—:]\s*%s\s*$' % re.escape(site), '', title, flags=re.I) if site else title
    title = re.sub(r'\s*[|\-–—]\s*(OpenHentai|Hitomi\.la|nhentai|E-Hentai)[^|]*$', '', title, flags=re.I).strip()
    if not title:
        return None
    img = m.get('og:image') or m.get('twitter:image')
    junk = {'manga', 'hentai', 'doujin', 'doujinshi', 'free', 'read', 'online', 'download'}
    kws = [k.strip() for k in (m.get('keywords') or '').split(',') if k.strip() and k.strip().lower() not in junk]
    host = urllib.parse.urlsplit(url).hostname or ''
    return {'src': 'web', 'site': re.sub(r'^www\.', '', host), 'id': url, 'url': url, 'romaji': html.unescape(title),
            'english': None, 'native': None, 'alt': [], 'year': None, 'chapters': None, 'volumes': None, 'score': None,
            'format': None, 'status': None, 'genres': kws[:30], 'desc': html_text(m.get('og:description') or m.get('description') or ''),
            'color': None, 'image': urllib.parse.urljoin(url, img) if img else None, 'referer': url}


def manga_queries(title):
    t = re.sub(r'\(\s*\d{4}\s*\)|\b(19|20)\d{2}\b', ' ', title)
    t = re.sub(r'\b(vol(ume)?s?|v)\.?\s*\d+(\s*-\s*\d+)?\b|\bch(apter)?s?\.?\s*\d+(\s*-\s*\d+)?\b', ' ', t, flags=re.I)
    t = re.sub(r'\s{2,}', ' ', t).strip(' -.')
    out = [t] if t else []
    if title not in out:
        out.append(title)
    head = re.split(r'\s+[-–—:]\s+', t)[0].strip()      # «Yo-Shu Tamagotei - Spring Strawberry» → «Yo-Shu Tamagotei»
    if head and len(head) > 3 and head not in out:
        out.append(head)
    return out


def manga_fetch(tid, title, hint):
    r = DB.one('SELECT hint FROM manga_titles WHERE tid=?', (tid,))
    if r and r['hint'] == RESET_HINT:       # поки чекали в черзі, дані скинули
        return
    d = manga_dir()
    os.makedirs(d, exist_ok=True)
    al = mu = web = None
    queries = []
    h = (hint or '').strip()
    if h:
        m = re.search(r'anilist\.co/manga/(\d+)', h)
        m2 = re.search(r'mangaupdates\.com/series/([0-9a-z]+)', h, re.I)
        m3 = re.fullmatch(r'mu:\s*(\d+)', h, re.I)
        m4 = re.search(r'hitomi\.la/(?:[^?#\s]*?[/-])?(\d+)\.html', h, re.I)
        if m4:
            web = ('hitomi', int(m4.group(1)))
        elif re.match(r'https?://', h, re.I) and not (m or m2):
            web = ('web', h)
        if web:
            pass
        elif m:
            al = int(m.group(1))
        elif m2:
            mu = int(m2.group(1).lower(), 36)
        elif m3:
            mu = int(m3.group(1))
        elif h.isdigit():
            al = int(h)
        else:
            queries = [h]
    else:
        queries = manga_queries(title)
    meta = None
    if web:
        meta = hitomi_gallery(web[1]) if web[0] == 'hitomi' else web_meta(web[1])
    elif al:
        meta = anilist_manga(mid=al)
    elif mu:
        meta = mu_series(mu)
    else:
        for q in queries:
            meta = anilist_manga(search=q)
            time.sleep(2.2)
            if meta:
                break
        if not meta:
            for q in queries:
                meta = mu_search(q)
                time.sleep(1)
                if meta:
                    break
    out = {'v': MANGA_META_V, 'at': time.time(), 'hint': h, 'q': queries}
    if meta:
        url, ref = meta.pop('image', None), meta.pop('referer', None)
        img = None
        if url:
            hdr = {'User-Agent': 'Mozilla/5.0 (VidBox/%s)' % VERSION}
            if ref:
                hdr['Referer'] = ref
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=30) as r:
                    img = r.read(20 << 20)
            except (OSError, ValueError) as e:
                print('Манга: обкладинку з %s не завантажив (%s)' % (url, e))
        if img and img[:3] in (b'\xff\xd8\xff', b'\x89PN', b'RIF', b'GIF') or (img and img[4:12] in (b'ftypavif', b'ftypavis')):
            with open(os.path.join(d, tid + '.part'), 'wb') as f:
                f.write(img)
            os.replace(os.path.join(d, tid + '.part'), os.path.join(d, tid + '.jpg'))
        else:      # джерело без обкладинки (Hitomi) — лишається своя: cover.jpg або перша сторінка
            try:
                os.remove(os.path.join(d, tid + '.jpg'))
            except OSError:
                pass
        out.update(meta)
        print('Манга: «%s» → %s (%s)' % (title, meta.get('romaji') or meta.get('english'), meta['src']))
    else:
        out['none'] = True
        try:
            os.remove(os.path.join(d, tid + '.jpg'))
        except OSError:
            pass
        print('Манга: «%s» не знайдено ні на AniList, ні на MangaUpdates — обкладинка з першої сторінки' % title)
    with open(os.path.join(d, tid + '.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)


def manga_link(d):
    tid = str(d.get('tid', ''))
    t = MANGA['titles'].get(tid)
    if not t:
        return {'ok': False, 'error': 'Тайтл не знайдено'}
    link = str(d.get('link') or '').strip()[:300]
    manga_set(tid, hint=link)
    ANILIST_FAIL.pop('m:' + tid, None)
    manga_want(t, {'hint': link}, force=True)
    return {'ok': True}


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


# ───────────────────────────── субтитри для сайту ─────────────────────────────
# Вбудовані текстові доріжки (SRT/ASS/…) і файли поруч із відео («Фільм.srt», «Фільм.ukr.ass», теки Subs/)
# віддаємо як WebVTT; сайт малює їх сам — так вони збігаються з часом і під час перекодування на льоту.
# Картинкові (PGS/VobSub з Blu-ray/DVD) у текст не перетворюються — їх пропускаємо.

SUB_TEXT = {'subrip', 'srt', 'ass', 'ssa', 'webvtt', 'mov_text', 'text', 'microdvd', 'subviewer', 'subviewer1'}
SUB_EXT = ('.srt', '.ass', '.ssa', '.vtt')
LANG2 = {'eng': 'en', 'ukr': 'uk', 'rus': 'ru', 'jpn': 'ja', 'ger': 'de', 'deu': 'de', 'fre': 'fr', 'fra': 'fr',
         'spa': 'es', 'ita': 'it', 'pol': 'pl', 'chi': 'zh', 'zho': 'zh', 'kor': 'ko', 'por': 'pt', 'cze': 'cs',
         'ces': 'cs', 'bel': 'be', 'tur': 'tr', 'ara': 'ar', 'hin': 'hi', 'tha': 'th', 'vie': 'vi', 'ind': 'id'}
SUBS_CACHE = {}       # id відео → (mtime, список)


def sub_lang(x):
    x = (x or '').lower()
    return LANG2.get(x, x if len(x) == 2 else '')


def subs_list(r):
    """[{n, lang, label, src}] — src: ('s', номер доріжки) або ('f', шлях до файлу)."""
    try:
        mt = os.path.getmtime(r['path'])
    except OSError:
        return []
    hit = SUBS_CACHE.get(r['id'])
    if hit and hit[0] == mt:
        return hit[1]
    out = []
    if C.ffprobe:
        try:
            j = json.loads(run([C.ffprobe, '-v', 'error', '-print_format', 'json', '-show_streams', '-select_streams', 's',
                                r['path']], 60).stdout.decode('utf-8', 'replace') or '{}')
        except Exception:
            j = {}
        for i, st in enumerate(j.get('streams', [])):
            if st.get('codec_name') not in SUB_TEXT:
                continue
            tg = {k.lower(): v for k, v in (st.get('tags') or {}).items()}
            out.append({'lang': sub_lang(tg.get('language')), 'label': (tg.get('title') or '').strip(), 'src': ('s', i),
                        'def': bool((st.get('disposition') or {}).get('default')),
                        'forced': bool((st.get('disposition') or {}).get('forced'))})
    d, stem = os.path.dirname(r['path']), os.path.splitext(os.path.basename(r['path']))[0]
    for folder in (d, os.path.join(d, 'Subs'), os.path.join(d, 'subs'), os.path.join(d, 'Subtitles'), os.path.join(d, stem)):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for f in names:
            low = f.lower()
            if not low.endswith(SUB_EXT) or not (f.startswith(stem) or folder != d and os.path.basename(folder) == stem):
                continue
            mid = os.path.splitext(f[len(stem):] if f.startswith(stem) else '')[0].strip('._- ')
            lang = sub_lang(mid.split('.')[-1]) if mid else ''
            out.append({'lang': lang, 'label': mid if mid and not lang else '', 'src': ('f', os.path.join(folder, f)),
                        'def': False, 'forced': 'forced' in low})
    ad = os.path.join(C.data, 'aisubs', r['id'])
    try:
        for f in sorted(os.listdir(ad), key=lambda x: (x != 'uk.srt', x)):
            if f.endswith('.srt'):
                out.append({'lang': sub_lang(f[:-4]), 'label': 'ШІ', 'src': ('f', os.path.join(ad, f)), 'def': False,
                            'forced': False, 'ai': True})
    except OSError:
        pass
    for n, t in enumerate(out):
        t['n'] = n
    SUBS_CACHE[r['id']] = (mt, out)
    return out


def subs_vtt(r, n):
    """WebVTT n-ї доріжки (кешується в data/subs)."""
    lst = subs_list(r)
    if not 0 <= n < len(lst) or not C.ffmpeg:
        return None
    kind, src = lst[n]['src']
    stamp = os.path.getmtime(src if kind == 'f' else r['path'])
    cache = os.path.join(C.data, 'subs', '%s-%d-%d.vtt' % (r['id'], n, int(stamp)))
    if os.path.exists(cache):
        with open(cache, 'rb') as f:
            return f.read()
    if kind == 'f':
        with open(src, 'rb') as f:
            raw = f.read()
        enc = []
        try:
            raw.decode('utf-8')
        except UnicodeDecodeError:
            enc = ['-sub_charenc', 'CP1251']          # старі SRT з кирилицею
        cmd = [C.ffmpeg, '-v', 'error', *enc, '-i', src, '-f', 'webvtt', '-']
    else:
        cmd = [C.ffmpeg, '-v', 'error', '-i', r['path'], '-map', '0:s:%d' % src, '-f', 'webvtt', '-']
    try:
        res = run(cmd, 300)
    except Exception:
        return None
    if res.returncode or not res.stdout.startswith(b'WEBVTT'):
        return None
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    for old in glob.glob(os.path.join(C.data, 'subs', '%s-%d-*.vtt' % (r['id'], n))):
        try:
            os.remove(old)
        except OSError:
            pass
    with open(cache, 'wb') as f:
        f.write(res.stdout)
    return res.stdout


# ───────────────────────────── субтитри ШІ (Whisper + DeepL) ─────────────────────────────
# Whisper (faster-whisper) живе у власному середовищі Python у data/whisper: його ставить uv разом з окремим
# Python 3.12 — не залежить від системного Python і не потребує root. Розпізнавання — у whisper_worker.py
# з низьким пріоритетом; українською перекладає DeepL (ключ у налаштуваннях). Результат — data/aisubs/<id>/<мова>.srt.

AI = {'install': None, 'log': '', 'cur': None, 'proc': None}       # install: None | 'run' | 'error'
AI_LOCK = threading.Lock()
AI_WAKE = threading.Event()
AI_MODELS = ('large-v3-turbo', 'small')
DEEPL_SRC = {'ar', 'bg', 'cs', 'da', 'de', 'el', 'en', 'es', 'et', 'fi', 'fr', 'he', 'hu', 'id', 'it', 'ja', 'ko', 'lt',
             'lv', 'nb', 'nl', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'sv', 'th', 'tr', 'uk', 'vi', 'zh'}


def ai_dir(*a):
    return os.path.join(C.data, 'whisper', *a)


def ai_py():
    return ai_dir('venv', 'bin', 'python')


def ai_ready():
    return os.path.exists(ai_py()) and os.path.exists(ai_dir('venv', '.ok'))


def ai_env():
    e = dict(os.environ, HF_HOME=ai_dir('hf'), UV_CACHE_DIR=ai_dir('uv-cache'), UV_PYTHON_INSTALL_DIR=ai_dir('python'),
             XDG_CACHE_HOME=ai_dir('cache'), HOME=ai_dir())
    e.pop('PYTHONPATH', None)
    return e


def ai_install():
    """Завантажити uv, поставити Python 3.12 і faster-whisper. Кілька хвилин; ~400 МБ."""
    import platform
    import tarfile
    arch = {'x86_64': 'x86_64', 'amd64': 'x86_64', 'aarch64': 'aarch64', 'arm64': 'aarch64'}.get(platform.machine().lower())
    if not sys.platform.startswith('linux') or not arch:
        AI.update(install='error', log='Субтитри ШІ поки працюють лише на Linux (на Хаті).')
        return
    os.makedirs(ai_dir(), exist_ok=True)

    def say(x):
        AI['log'] = x

    try:
        uv = ai_dir('uv')
        if not os.path.exists(uv):
            say('Завантажую uv…')
            url = 'https://github.com/astral-sh/uv/releases/latest/download/uv-%s-unknown-linux-gnu.tar.gz' % arch
            with urllib.request.urlopen(url, timeout=120) as r, tarfile.open(fileobj=io.BytesIO(r.read()), mode='r:gz') as t:
                m = next(x for x in t.getmembers() if x.name.endswith('/uv'))
                with open(uv + '.tmp', 'wb') as f:
                    f.write(t.extractfile(m).read())
            os.chmod(uv + '.tmp', 0o755)
            os.replace(uv + '.tmp', uv)
        say('Ставлю Python 3.12…')
        r = subprocess.run([uv, 'venv', '--python', '3.12', '--clear', ai_dir('venv')], env=ai_env(),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
        if r.returncode:
            raise RuntimeError(r.stdout.decode('utf-8', 'replace')[-400:])
        say('Ставлю faster-whisper (≈ 300 МБ)…')
        r = subprocess.run([uv, 'pip', 'install', '--python', ai_py(), 'faster-whisper>=1.1'], env=ai_env(),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800)
        if r.returncode:
            raise RuntimeError(r.stdout.decode('utf-8', 'replace')[-400:])
        open(ai_dir('venv', '.ok'), 'w').close()
        AI.update(install=None, log='')
        AI_WAKE.set()
    except Exception as e:
        AI.update(install='error', log='Не вдалося встановити: %s' % str(e)[-400:])


def ai_queue():
    try:
        with open(os.path.join(C.data, 'aisubs', 'queue.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def ai_save_queue(q):
    d = os.path.join(C.data, 'aisubs')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'queue.json.tmp'), 'w', encoding='utf-8') as f:
        json.dump(q, f, ensure_ascii=False)
    os.replace(os.path.join(d, 'queue.json.tmp'), os.path.join(d, 'queue.json'))


def ai_set(vid, **kw):
    with AI_LOCK:
        q = ai_queue()
        for it in q:
            if it['id'] == vid:
                it.update(kw)
        ai_save_queue(q)


def srt_time(t):
    ms = int(round(t * 1000))
    return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def write_srt(path, segs, texts=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        for i, sg in enumerate(segs):
            f.write('%d\n%s --> %s\n%s\n\n' % (i + 1, srt_time(sg['s']), srt_time(sg['e']), (texts[i] if texts else sg['t']).strip()))
    os.replace(path + '.tmp', path)


def read_srt(path):
    def t(x):
        h, m, rest = x.strip().replace('.', ',').split(':')
        sec, ms = rest.split(',')
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000
    segs = []
    with open(path, encoding='utf-8') as f:
        for block in re.split(r'\n\s*\n', f.read().replace('\r', '')):
            lines = block.strip().split('\n')
            i = next((k for k, l in enumerate(lines) if '-->' in l), -1)
            if i >= 0 and lines[i + 1:]:
                a, b = lines[i].split('-->')
                segs.append({'s': t(a), 'e': t(b), 't': '\n'.join(lines[i + 1:])})
    return segs


ASS_DRAW_RE = re.compile(r'^\s*m\s+-?[\d.]+\s+-?[\d.]+(\s+[lbmnspc](\s+-?[\d.]+)+)+\s*$', re.I)


def read_vtt(data):
    """WebVTT (як його віддає ffmpeg) → [{s, e, t}] без розмітки; однакові репліки, що йдуть впритул, зливаємо
    (караоке в опенінгах і ефекти фансабів часто розбиті на десятки однакових подій)."""
    def t(x):
        p = x.strip().split(':')
        return (int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])) if len(p) == 3 else int(p[0]) * 60 + float(p[1])
    segs = []
    for block in re.split(r'\n\s*\n', data.decode('utf-8', 'replace').replace('\r', '')):
        lines = block.strip().split('\n')
        i = next((k for k, l in enumerate(lines) if '-->' in l), -1)
        if i < 0:
            continue
        a, b = lines[i].split('-->')
        txt = re.sub(r'<[^>]+>|\{[^}]*\}', '', '\n'.join(lines[i + 1:])).replace('\\N', '\n')
        txt = html.unescape(re.sub(r'[ \t]+', ' ', txt)).strip()
        if ASS_DRAW_RE.match(txt):        # векторні рамки табличок ASS («m 894 325 l 1206 325…») — не текст
            continue
        txt = '\n'.join(x for x in (re.sub(r'^_+|_+$', '', l).strip() for l in txt.split('\n')) if x)   # «______Студент»
        if not txt:
            continue
        sg = {'s': t(a), 'e': t(b.strip().split()[0]), 't': txt}
        if segs and segs[-1]['t'] == txt and sg['s'] - segs[-1]['e'] < 0.3:
            segs[-1]['e'] = max(segs[-1]['e'], sg['e'])
        else:
            segs.append(sg)
    return sorted(segs, key=lambda x: x['s'])


def ai_text_source(r):
    """Номер англійської текстової доріжки, з якої краще перекладати (повна, не «лише написи»), або None."""
    if C.cfg.get('ai_source') == 'audio':
        return None
    cand = [t for t in subs_list(r) if t['lang'] == 'en' and not t.get('ai') and not t['forced']]
    if not cand:
        return None
    def score(t):
        lab = (t['label'] or '').lower()
        return (not re.search(r'sign|song|title|надпис', lab), bool(re.search(r'full|dialog|subs', lab)), t['def'])
    return max(cand, key=score)['n']


def deepl_call(key, path, data=None):
    host = 'api-free.deepl.com' if key.strip().endswith(':fx') else 'api.deepl.com'
    req = urllib.request.Request('https://%s/v2/%s' % (host, path), data=json.dumps(data).encode() if data else None,
                                 headers={'Authorization': 'DeepL-Auth-Key ' + key.strip(), 'Content-Type': 'application/json',
                                          'User-Agent': 'VidBox'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise RuntimeError({403: 'DeepL не прийняв ключ', 456: 'ліміт DeepL на цей місяць вичерпано',
                            429: 'DeepL просить почекати — забагато запитів'}.get(e.code, 'DeepL: помилка %d' % e.code))


def deepl_translate(key, lines, src, progress=None):
    """Переклад реплік українською шматками по 40 — у вигляді XML, щоб DeepL бачив контекст, а репліки не злипались."""
    out = list(lines)
    for i in range(0, len(lines), 40):
        part = lines[i:i + 40]
        xml = '<r>' + ''.join('<s i="%d">%s</s>' % (i + k, html.escape(t, quote=False)) for k, t in enumerate(part)) + '</r>'
        body = {'text': [xml], 'target_lang': 'UK', 'tag_handling': 'xml', 'tag_handling_version': 'v2',
                'splitting_tags': ['s'], 'outline_detection': False}
        if src in DEEPL_SRC:
            body['source_lang'] = src.upper()
        for n in range(3):
            try:
                res = deepl_call(key, 'translate', body)
                break
            except RuntimeError as e:
                if 'почекати' not in str(e) or n == 2:
                    raise
                time.sleep(5 * (n + 1))
        txt = res['translations'][0]['text']
        for m in re.finditer(r'<s i="(\d+)">(.*?)</s>', txt, re.S):
            k = int(m.group(1))
            if 0 <= k < len(out):
                out[k] = html.unescape(m.group(2)).strip() or out[k]
        if progress:
            progress(min(1.0, (i + 40) / max(1, len(lines))))
    return out


# ── Інші перекладачі. Помилка з quota=True — «ліміт/ключ», тоді переходимо до наступного перекладача.
TR_NAMES = {'local': 'Локальна модель', 'gemini': 'Gemini', 'deepl': 'DeepL', 'azure': 'Azure'}
LANG_EN = {'ja': 'Japanese', 'en': 'English', 'ko': 'Korean', 'zh': 'Chinese', 'ru': 'Russian', 'de': 'German',
           'fr': 'French', 'es': 'Spanish', 'it': 'Italian', 'pl': 'Polish', 'pt': 'Portuguese'}


class TrError(RuntimeError):
    def __init__(self, msg, quota=False):
        super().__init__(msg)
        self.quota = quota


def http_json(url, data=None, headers=None, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers=dict({'Content-Type': 'application/json', 'User-Agent': 'VidBox'}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8', 'replace')
        except Exception:
            body = ''
        e.body = body
        raise


def gemini_pick_model(key):
    """Найкраща доступна легка модель Gemini для цього ключа (назви моделей у Google часто міняються)."""
    try:
        j = http_json('https://generativelanguage.googleapis.com/v1beta/models?pageSize=200', headers={'x-goog-api-key': key})
    except urllib.error.HTTPError as e:
        raise TrError('Gemini не прийняв ключ' if e.code in (400, 401, 403) else 'ліміт Gemini вичерпано' if e.code == 429
                      else 'Gemini: помилка %d' % e.code, quota=True)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise TrError('Gemini недоступний: %s' % getattr(e, 'reason', e), quota=True)
    names = [m['name'].split('/', 1)[-1] for m in j.get('models', []) if 'generateContent' in (m.get('supportedGenerationMethods') or [])]
    def score(n):
        v = [int(x) for x in re.findall(r'\d+', n.split('-')[1] if n.count('-') else '0')] or [0]
        return (('flash-lite' in n) * 2 + ('flash' in n), 'preview' not in n and 'exp' not in n, v, -len(n))
    good = [n for n in names if n.startswith('gemini-') and 'flash' in n and not re.search(r'tts|image|audio|live|embedding|thinking', n)]
    if not good:
        raise TrError('Для цього ключа немає моделі Gemini Flash', quota=True)
    return max(good, key=score)


# ── Глосарій: загальний ('_') і для кожного тайтлу аніме (sid). Таблиця термінів [термін, переклад, регістр, примітка]
# плюс вільні правила («звертання -san не перекладати»). Заливається файлом (.csv з srt_glossary.py, .md-таблиця, .txt)
# або редагується в інтерфейсі. У запит до перекладача йдуть правила і лише ті терміни, що є в поточному шматку.
GLOSS_MAX = 3000
GLOSS_COLS = {'t': ('термін', 'term', 'оригінал', 'source', 'en', 'english'),
              'tr': ('переклад', 'translation', 'uk', 'українською', 'target'),
              'reg': ('регістр', 'register', 'reg', 'тип', 'type'),
              'note': ('примітка', 'пояснення', 'note', 'notes', 'коментар', 'comment')}


def gloss_load():
    try:
        with open(os.path.join(C.data, 'aisubs', 'glossary.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def gloss_clean(items):
    """Нормалізує й прибирає дублікати (пізніший запис того самого терміна перемагає)."""
    seen = {}
    for it in items or []:
        if isinstance(it, dict):
            it = [it.get('t'), it.get('tr'), it.get('reg'), it.get('note')]
        if not isinstance(it, (list, tuple)):
            continue
        it = [re.sub(r'\s+', ' ', str(x or '')).strip() for x in (list(it) + ['', '', '', ''])[:4]]
        t, tr, reg, note = it[0][:80], it[1][:160], it[2][:24], it[3][:240]
        if t and tr:
            seen.pop(t.lower(), None)
            seen[t.lower()] = [t, tr, reg, note]
    return list(seen.values())[-GLOSS_MAX:]


def gloss_parse_lines(text):
    """Вільний текст «a = b», «a — b — регістр — примітка», «a → b». Рядки без розділювача — правила."""
    items, notes = [], []
    for line in str(text or '').splitlines():
        line = line.strip().lstrip('\ufeff')
        if not line:
            continue
        m = re.match(r'^(.+?)\s*(?:=|→|->|\s[—–]\s)\s*(.+)$', line)
        if not m or len(m.group(1)) > 80:
            notes.append(line)
            continue
        rest = [x.strip() for x in re.split(r'\s+[—–]\s+', m.group(2))]
        items.append([m.group(1).strip(' «»"'), rest[0].strip(' «»"')] + rest[1:3])
    return items, notes


def gloss_parse_file(name, text):
    """→ (items, notes). CSV/TSV з заголовком (як у srt_glossary.py), Markdown-таблиця або вільний текст."""
    text = str(text or '').lstrip('\ufeff')
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return [], []
    rows = None
    if any(re.fullmatch(r'\s*\|[\s|:\-]+', l) for l in lines):  # Markdown-таблиця (є рядок |---|---|)
        rows = [[c.strip() for c in l.strip().strip('|').split('|')] for l in lines if l.lstrip().startswith('|')
                and not re.fullmatch(r'[\s|:\-]+', l)]
        notes = [l.strip() for l in lines if not l.lstrip().startswith('|') and not l.startswith('#')]
    elif name.lower().endswith(('.csv', '.tsv')) or re.match(r'^\W*(%s)\W*[;\t,]' % '|'.join(sum(GLOSS_COLS.values(), ())), lines[0], re.I):
        delim = max(';\t,', key=lambda c: lines[0].count(c))
        rows = list(csv.reader(lines, delimiter=delim))
        notes = []
    if rows is None:
        return gloss_parse_lines(text)
    head = [h.strip().lower() for h in rows[0]]
    idx = {k: next((i for i, h in enumerate(head) if h in names), None) for k, names in GLOSS_COLS.items()}
    if idx['t'] is None or idx['tr'] is None:                 # без заголовка — по порядку колонок
        idx = {'t': 0, 'tr': 1, 'reg': 2, 'note': 3}
    else:
        rows = rows[1:]
    get = lambda r, k: r[idx[k]] if idx[k] is not None and idx[k] < len(r) else ''
    return [[get(r, 't'), get(r, 'tr'), get(r, 'reg'), get(r, 'note')] for r in rows], notes


def gloss_get(sid):
    """{'notes': str, 'items': [[t, tr, reg, note]]}; старий формат (рядок) розбирається на льоту."""
    v = gloss_load().get(sid)
    if isinstance(v, str):
        items, notes = gloss_parse_lines(v)
        return {'notes': '\n'.join(notes), 'items': gloss_clean(items)}
    if isinstance(v, dict):
        return {'notes': str(v.get('notes') or ''), 'items': gloss_clean(v.get('items'))}
    return {'notes': '', 'items': []}


def gloss_put(sid, notes, items):
    g = gloss_load()
    notes, items = str(notes or '').strip()[:4000], gloss_clean(items)
    old = g.get(sid) if isinstance(g.get(sid), dict) else {}
    keep = {k: old[k] for k in ('sets',) if k in old}          # вибір наборів для тайтлу не губимо
    if notes or items or keep:
        g[sid] = dict(keep, notes=notes, items=items)
    else:
        g.pop(sid, None)
    os.makedirs(os.path.join(C.data, 'aisubs'), exist_ok=True)
    with open(os.path.join(C.data, 'aisubs', 'glossary.json.tmp'), 'w', encoding='utf-8') as f:
        json.dump(g, f, ensure_ascii=False, indent=1)
    os.replace(os.path.join(C.data, 'aisubs', 'glossary.json.tmp'), os.path.join(C.data, 'aisubs', 'glossary.json'))
    return {'notes': notes, 'items': items}


# ── Набори глосаріїв (apps/vidbox/glossaries/*.json): «Аніме», «Хентай 18+»… Ідуть разом із VidBox, вмикаються
# для кожного тайтлу окремо — щоб відверта лексика не потрапляла в звичайне аніме. Без явного вибору: «Аніме» для всіх
# тайтлів аніме + «Хентай 18+», якщо AniList позначає тайтл як 18+ (isAdult) або жанр Hentai. Набір із adult=true
# вмикає переклад без цензури. Пріоритет: авто-терміни < набори < загальний глосарій < глосарій тайтлу.
GLOSS_SETS = {}


def gloss_sets():
    if not GLOSS_SETS:
        d = os.path.join(app_dir(), 'glossaries')
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if fn.endswith('.json'):
                try:
                    with open(os.path.join(d, fn), encoding='utf-8') as f:
                        j = json.load(f)
                    GLOSS_SETS[fn[:-5]] = {'name': str(j.get('name') or fn[:-5]), 'adult': bool(j.get('adult')),
                                           'desc': str(j.get('desc') or ''), 'notes': str(j.get('notes') or ''),
                                           'items': gloss_clean(j.get('items'))}
                except (OSError, ValueError):
                    pass
    return GLOSS_SETS


def title_adult(sid):
    """AniList (або сайт за посиланням) каже, що тайтл 18+? → True/False/None (невідомо)."""
    try:
        with open(os.path.join(C.data, 'anime', sid + '.json'), encoding='utf-8') as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    if m.get('none'):
        return None
    return bool(m.get('adult') or any(str(g).lower() == 'hentai' for g in m.get('genres') or []))


def gloss_title_sets(sid):
    """→ (набори, auto). Явний вибір користувача або автоматичний."""
    if not sid or sid == '_':
        return [], False
    v = gloss_load().get(sid)
    if isinstance(v, dict) and isinstance(v.get('sets'), list):
        return [x for x in v['sets'] if x in gloss_sets()], False
    auto = [x for x in ('anime',) if x in gloss_sets()]
    if title_adult(sid) and 'hentai' in gloss_sets():
        auto.append('hentai')
    return auto, True


def gloss_set_sets(sid, sets):
    g = gloss_load()
    v = g.get(sid) if isinstance(g.get(sid), dict) else gloss_get(sid)
    v = dict(v)
    if sets is None:
        v.pop('sets', None)              # назад до автоматичного вибору
    else:
        v['sets'] = [x for x in sets if x in gloss_sets()]
    g[sid] = v
    os.makedirs(os.path.join(C.data, 'aisubs'), exist_ok=True)
    with open(os.path.join(C.data, 'aisubs', 'glossary.json.tmp'), 'w', encoding='utf-8') as f:
        json.dump(g, f, ensure_ascii=False, indent=1)
    os.replace(os.path.join(C.data, 'aisubs', 'glossary.json.tmp'), os.path.join(C.data, 'aisubs', 'glossary.json'))


def gloss_sets_info(sid):
    sets, auto = gloss_title_sets(sid)
    return {'sets': sets, 'setsAuto': auto, 'adultAuto': title_adult(sid) if sid and sid != '_' else None,
            'setsAvail': [{'id': k, 'name': v['name'], 'adult': v['adult'], 'desc': v['desc'], 'n': len(v['items'])}
                          for k, v in gloss_sets().items()]}


def gloss_counts():
    return {sid: len(gloss_get(sid)['items']) for sid in gloss_load()}


def gloss_prompt(text, src, limit=150):
    """Глосарій для одного запиту: правила + терміни, що трапляються в text (для англ. джерела);
    для інших мов (Whisper японською тощо) збіг не перевіриш — тоді імена/запозичення першими, до limit."""
    sids = getattr(TR_CTX, 'gloss_sids', None) or []
    notes, items = [], {it[0].lower(): it for it in getattr(TR_CTX, 'auto_items', None) or []}
    for k in getattr(TR_CTX, 'sets', None) or []:
        st = gloss_sets().get(k)
        if st:
            if st['notes']:
                notes.append(st['notes'])
            for it in st['items']:
                items[it[0].lower()] = it
    for sid in sids:                     # тайтл після загального — його переклади перекривають загальні
        g = gloss_get(sid)
        if g['notes']:
            notes.append(g['notes'])
        for it in g['items']:
            items[it[0].lower()] = it
    low = str(text or '').lower()
    if src == 'en':
        hit = [it for k, it in items.items()
               if (re.search(r'(?<![\w])' + re.escape(k) + r'(?![\w])', low) if re.match(r'^[\w\s\'-]+$', k) else k in low)]
    else:
        hit = sorted(items.values(), key=lambda it: it[2] not in ("ім'я", 'імʼя', 'name', 'запозичення'))
    hit = hit[:limit]
    out = '\n'.join(notes)
    if hit:
        out += ('\n' if out else '') + '\n'.join(
            '%s = %s%s' % (t, tr, ' (%s)' % '; '.join(x for x in (reg, note) if x) if reg or note else '') for t, tr, reg, note in hit)
    return out


def video_sid(r):
    """id тайтлу аніме для відео (як в anime_series), або ''."""
    if not C.anime or r['root'] != C.anime:
        return ''
    parts = os.path.relpath(r['path'], C.anime).split(os.sep)
    return hashlib.sha1(('anime:' + (parts[0] if len(parts) > 1 else '')).encode('utf-8', 'surrogateescape')).hexdigest()[:12]


TR_CTX = threading.local()             # глосарій поточного завдання (перекладач — у тому ж потоці)


def gemini_translate(key, lines, src, progress=None):
    model = C.cfg.get('gemini_model')
    if not model:
        model = gemini_pick_model(key)
        with CFG_LOCK:
            C.cfg['gemini_model'] = model
        save_config()
    srcname = LANG_EN.get(src, 'the original language')
    out = list(lines)
    step = 50
    for i in range(0, len(lines), step):
        part = lines[i:i + step]
        ctx = lines[max(0, i - 6):i]
        gloss = gloss_prompt('\n'.join(ctx + part), src)
        prompt = ('You translate subtitles of anime and films from %s into Ukrainian.\n'
                  'Translate every line of "lines" into natural, spoken Ukrainian that fits the scene; keep names, '
                  'keep the tone (casual, rude, polite), do not add explanations. Lines may be broken mid-sentence — '
                  'translate them so they still read well in order. Return JSON {"lines": [...]} with exactly %d '
                  'strings in the same order.\n"context" holds the previous lines for reference only — do not translate them.\n%s\n%s\n%s'
                  % (srcname, len(part), SPEAKER_HINT, (('\n' + TR_CTX.ctx + '\n') if getattr(TR_CTX, 'ctx', '') else '') + ('\nGlossary and notes from the viewer — follow them strictly (names, terms, '
                                          'how characters address each other):\n' + gloss + '\n') if gloss else '',
                     json.dumps({'context': ctx, 'lines': part}, ensure_ascii=False)))
        body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0.3, 'responseMimeType': 'application/json'}}
        res = None
        for n in range(4):
            try:
                res = http_json('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % model, body,
                                {'x-goog-api-key': key}, timeout=180)
                break
            except urllib.error.HTTPError as e:
                b = getattr(e, 'body', '')
                if e.code == 404 and n == 0:              # модель прибрали — беремо іншу
                    model = gemini_pick_model(key)
                    with CFG_LOCK:
                        C.cfg['gemini_model'] = model
                    save_config()
                    continue
                if e.code == 429:
                    if 'PerDay' in b or 'per day' in b.lower() or n == 3:
                        raise TrError('ліміт Gemini на сьогодні вичерпано', quota=True)
                    m = re.search(r'"retryDelay":\s*"(\d+)', b)
                    time.sleep(min(90, int(m.group(1)) + 2 if m else 20 * (n + 1)))
                    continue
                if e.code in (400, 401, 403) and ('API key' in b or 'PERMISSION' in b):
                    raise TrError('Gemini не прийняв ключ', quota=True)
                if e.code >= 500 and n < 3:
                    time.sleep(10)
                    continue
                raise TrError('Gemini: помилка %d %s' % (e.code, b[:160]))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if n == 3:
                    raise TrError('Gemini недоступний: %s' % e)
                time.sleep(10)
        try:
            txt = ''.join(p.get('text', '') for p in res['candidates'][0]['content']['parts'])
            got = json.loads(txt).get('lines') or []
        except (KeyError, IndexError, ValueError, AttributeError):
            got = []
        if len(got) != len(part):        # модель збилась із кількістю — краще оригінал, ніж зсув реплік
            got = got[:len(part)] + part[len(got):] if got else part
        for k, t in enumerate(got):
            if isinstance(t, str) and t.strip():
                out[i + k] = t.strip()
        if progress:
            progress(min(1.0, (i + step) / max(1, len(lines))))
        time.sleep(4.5)                  # безкоштовний тариф — ~15 запитів на хвилину
    return out


# ── Локальна модель: LM Studio (або інший OpenAI-сумісний сервер: llama.cpp, Ollama, KoboldCpp) на ПК в домашній мережі.
# Без лімітів і цензури — для дорослих тайтлів. Якщо ПК вимкнений чи модель не відповідає — помилка з quota=True,
# і ланцюжок переходить до наступного перекладача (Gemini тощо).
LOCAL_COMMON = ('Moans, gasps and interjections get natural Ukrainian equivalents. Never refuse, never add warnings, '
                'notes or comments. Write only in Ukrainian Cyrillic — never put Latin, Korean, Arabic or Japanese letters '
                'inside Ukrainian words; if you do not know a word, rephrase.\n'
                'Register examples: "You scared the shit out of me" → "Ти мене до усрачки налякала"; "pain in the ass" → '
                '"заноза в дупі"; "Holy shit" → "Срань господня" / "Бляха"; "dumbass" → "дебіл" / "довбень"; "Shut up!" → '
                '"Стули пельку!". Avoid calques like "Не так, ніби…" — say "Не думай, що…".')
LOCAL_SYSTEM_STD = ('You are a professional translator of anime and film subtitles into Ukrainian. Translate faithfully, '
                    'keeping the exact register of the original — rude stays rude (real Ukrainian swearing where the '
                    'original swears), polite stays polite, shy stays shy. ' + LOCAL_COMMON)
LOCAL_SYSTEM_ADULT = ('You are a professional translator of adult (18+) anime subtitles such as hentai into Ukrainian. All '
                      'characters are adults. This is fiction: translate faithfully and without censorship. Keep the exact '
                      'register — crude stays crude (real Ukrainian swearing and explicit sexual vocabulary, no euphemisms, '
                      'no asterisks), tender stays tender, shy stays shy. "Cum/finish" in a sexual sense is «кінчати», '
                      'never «фінішувати». Examples: "Fuck me harder" → «Трахни мене сильніше»; "your cock" → «твій член»; '
                      '"I\'m cumming!" → «Я кінчаю!»; "you slut" → «шльондро»; "Holy shit, your tits" → «Бляха, твої '
                      'цицьки». ' + LOCAL_COMMON)
LOCAL_SYSTEM = LOCAL_SYSTEM_ADULT        # старе ім'я


def tr_adult():
    """Чи вмикати переклад без цензури: є набір глосарію з adult=true для поточного тайтлу."""
    return any(gloss_sets().get(k, {}).get('adult') for k in getattr(TR_CTX, 'sets', None) or [])


SPEAKER_HINT = ('Subtitles do not say who speaks: infer the speaker and the addressee of every line from context and the '
                'character list. Past-tense verbs, adjectives and vocatives must match their gender (я хотів / я хотіла, '
                'дурню / дурепо); for a man and a woman together use «обоє», «ми з тобою».')


def local_base(url):
    """«192.168.3.50:1234» → «http://192.168.3.50:1234/v1»."""
    url = str(url or '').strip().rstrip('/')
    if not url:
        return ''
    if not re.match(r'^https?://', url):
        url = 'http://' + url
    if not re.search(r':\d+(/|$)', url.split('://', 1)[1]) and url.count('/') == 2:
        url += ':1234'
    if not url.endswith('/v1'):
        url += '/v1'
    return url


def local_hdr():
    k = (C.cfg.get('local_key') or '').strip()
    return {'Authorization': 'Bearer ' + k} if k else {}


def local_pick_model(url, hdr=None):
    """Модель на сервері: та, що вже завантажена в LM Studio, інакше перша не-embedding."""
    hdr = local_hdr() if hdr is None else hdr
    base = local_base(url)
    try:
        j = http_json(base + '/models', headers=hdr, timeout=15)
    except urllib.error.HTTPError as e:
        raise TrError('локальний сервер не прийняв токен' if e.code in (401, 403) else 'локальний сервер: помилка %d' % e.code, quota=True)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise TrError('ПК з моделлю недоступний (%s) — увімкни ПК і сервер у LM Studio' % getattr(e, 'reason', e), quota=True)
    ids = [m.get('id') for m in j.get('data', []) if m.get('id') and not re.search(r'embed', m['id'], re.I)]
    if not ids:
        raise TrError('на локальному сервері немає жодної моделі', quota=True)
    loaded = []                            # рідний API LM Studio знає, яка модель уже в пам'яті відеокарти
    for path in ('/api/v1/models', '/api/v0/models'):     # 0.4+ — v1, старші — v0
        try:
            j = http_json(base[:-3] + path, headers=hdr, timeout=10)
        except Exception:
            continue
        for m in (j.get('models') or j.get('data') or []) if isinstance(j, dict) else []:
            mid = m.get('id') or m.get('key') or m.get('model_key')
            if mid and (m.get('state') == 'loaded' or m.get('loaded_instances')) and m.get('type') not in ('embedding', 'embeddings'):
                loaded.append(mid)
        if loaded:
            break
    for m in loaded:
        if m in ids:
            return m
    return ids[0]


def local_translate(url, lines, src, progress=None):
    base = local_base(url)
    hdr = local_hdr()
    model = local_pick_model(url, hdr)      # щоразу перевіряємо: модель на ПК могли змінити
    if model != C.cfg.get('local_model'):
        with CFG_LOCK:
            C.cfg['local_model'] = model
        save_config()
    srcname = LANG_EN.get(src, 'the original language')
    out = list(lines)
    step = 30
    use_schema = True
    for i in range(0, len(lines), step):
        part = lines[i:i + step]
        ctx = lines[max(0, i - 6):i]
        gloss = gloss_prompt('\n'.join(ctx + part), src)
        prompt = ('Translate every line of "lines" from %s into natural, spoken Ukrainian that fits the scene; keep names '
                  'and the tone. Lines may be broken mid-sentence — translate them so they still read well in order. '
                  'Return JSON {"lines": [...]} with exactly %d strings in the same order.\n'
                  '"context" holds the previous lines for reference only — do not translate them.\n%s\n%s\n%s'
                  % (srcname, len(part), SPEAKER_HINT, (('\n' + TR_CTX.ctx + '\n') if getattr(TR_CTX, 'ctx', '') else '') + ('\nGlossary and notes from the viewer — follow them strictly (names, terms, '
                                          'how characters address each other):\n' + gloss + '\n') if gloss else '',
                     json.dumps({'context': ctx, 'lines': part}, ensure_ascii=False)))
        body = {'model': model, 'temperature': 0.3, 'chat_template_kwargs': {'enable_thinking': False},
                'messages': [{'role': 'system', 'content': LOCAL_SYSTEM_ADULT if tr_adult() else LOCAL_SYSTEM_STD},
                             {'role': 'user', 'content': prompt}]}
        got = []
        for n in range(3):
            if use_schema:                  # LM Studio вміє примусово тримати формат — тоді репліки не зсуваються
                body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'subs', 'strict': True, 'schema': {
                    'type': 'object', 'required': ['lines'], 'properties': {'lines': {
                        'type': 'array', 'items': {'type': 'string'}, 'minItems': len(part), 'maxItems': len(part)}}}}}
            else:
                body.pop('response_format', None)
            try:
                res = http_json(base + '/chat/completions', body, hdr, timeout=900)
            except urllib.error.HTTPError as e:
                if e.code == 400 and use_schema:        # сервер без structured output — пробуємо без нього
                    use_schema = False
                    continue
                if e.code in (401, 403):
                    raise TrError('локальний сервер не прийняв токен', quota=True)
                if n == 2:
                    raise TrError('локальна модель: помилка %d %s' % (e.code, getattr(e, 'body', '')[:160]), quota=True)
                time.sleep(5)
                continue
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise TrError('ПК з моделлю недоступний: %s' % getattr(e, 'reason', e), quota=True)
            try:
                txt = res['choices'][0]['message'].get('content') or ''
                txt = re.sub(r'<think>.*?</think>', '', txt, flags=re.S).strip()
                m = re.search(r'\{.*\}', txt, re.S)
                got = json.loads(m.group(0) if m else txt).get('lines') or []
            except (KeyError, IndexError, ValueError, AttributeError, TypeError):
                got = []
            if len(got) == len(part):
                break
        if len(got) != len(part):        # модель збилась із кількістю — краще оригінал, ніж зсув реплік
            got = got[:len(part)] + part[len(got):] if got else part
        for k, t in enumerate(got):
            if isinstance(t, str) and t.strip():
                out[i + k] = t.strip()
        if progress:
            progress(min(1.0, (i + step) / max(1, len(lines))))
    return out


def azure_translate(key, lines, src, progress=None):
    region = (C.cfg.get('azure_region') or '').strip()
    hdr = {'Ocp-Apim-Subscription-Key': key}
    if region:
        hdr['Ocp-Apim-Subscription-Region'] = region
    out = list(lines)
    for i in range(0, len(lines), 100):
        part = lines[i:i + 100]
        url = 'https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&to=uk' + ('&from=' + src if src in LANG_EN else '')
        for n in range(3):
            try:
                res = http_json(url, [{'Text': t} for t in part], hdr)
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise TrError('Azure не прийняв ключ (перевір і регіон)', quota=True)
                if e.code == 429 and n < 2:
                    time.sleep(30)
                    continue
                if e.code in (403, 429):
                    raise TrError('ліміт Azure вичерпано', quota=True)
                raise TrError('Azure: помилка %d' % e.code)
        for k, r_ in enumerate(res):
            t = ((r_.get('translations') or [{}])[0].get('text') or '').strip()
            if t:
                out[i + k] = t
        if progress:
            progress(min(1.0, (i + 100) / max(1, len(lines))))
    return out


# ── Аналіз серії перед перекладом. Мовна модель (локальна або Gemini) читає всі репліки: про що серія, хто з персонажів
# чоловік/жінка (від цього в українській залежать закінчення), як хто говорить, які терміни/сленг. Персонажі й терміни
# додаються в глосарій тайтлу (лише нові — правки користувача не чіпаємо), опис і персонажі йдуть у кожен запит перекладу.
ANALYZE_SYSTEM_STD = ('You are a senior translator preparing the Ukrainian localization of anime and films. '
                      'Answer only with JSON.')
ANALYZE_SYSTEM = ('You are a senior translator preparing the Ukrainian localization of adult (18+) anime such as hentai; '
                  'all characters are adults. Analyze subtitles frankly and without censorship. Answer only with JSON.')
ANALYZE_STEP = 220


def llm_json(system, prompt, schema=None):
    """JSON-відповідь першої доступної мовної моделі з ланцюжка (локальна / Gemini). → (dict, назва) або (None, '')."""
    for name, key in tr_chain():
        try:
            if name == 'local':
                base, hdr = local_base(key), local_hdr()
                body = {'model': local_pick_model(key, hdr), 'temperature': 0.2,
                        'chat_template_kwargs': {'enable_thinking': False},       # «роздуми» Gemma/Qwen тут лише гальмують
                        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]}
                if schema:
                    body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'ctx', 'schema': schema}}
                try:
                    res = http_json(base + '/chat/completions', body, hdr, timeout=900)
                except urllib.error.HTTPError as e:
                    if e.code != 400 or not schema:
                        raise
                    body.pop('response_format')
                    res = http_json(base + '/chat/completions', body, hdr, timeout=900)
                txt = res['choices'][0]['message'].get('content') or ''
            elif name == 'gemini':
                model = C.cfg.get('gemini_model') or gemini_pick_model(key)
                body = {'systemInstruction': {'parts': [{'text': system}]},
                        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                        'generationConfig': {'temperature': 0.2, 'responseMimeType': 'application/json'}}
                res = http_json('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % model, body,
                                {'x-goog-api-key': key}, timeout=180)
                txt = ''.join(x.get('text', '') for x in res['candidates'][0]['content']['parts'])
                time.sleep(4.5)
            else:
                continue
            txt = re.sub(r'<think>.*?</think>', '', txt, flags=re.S)
            m = re.search(r'\{.*\}', txt, re.S)
            j = json.loads(m.group(0) if m else txt)
            if isinstance(j, dict):
                return j, name
        except Exception:
            continue                     # ПК вимкнений, ліміт, кривий JSON — пробуємо наступну модель
    return None, ''


ANALYZE_SCHEMA = {'type': 'object', 'required': ['summary', 'characters', 'terms'], 'properties': {
    'summary': {'type': 'string'},
    'characters': {'type': 'array', 'items': {'type': 'object', 'required': ['name', 'uk', 'gender'], 'properties': {
        'name': {'type': 'string'}, 'uk': {'type': 'string'}, 'gender': {'type': 'string', 'enum': ['f', 'm', '?']},
        'speech': {'type': 'string'}}}},
    'terms': {'type': 'array', 'items': {'type': 'object', 'required': ['t', 'tr'], 'properties': {
        't': {'type': 'string'}, 'tr': {'type': 'string'}, 'reg': {'type': 'string'}, 'note': {'type': 'string'}}}}}}


def ai_analyze(lines, src, progress=None):
    """→ {'summary', 'characters': [{name, uk, gender, speech}], 'terms': [[t, tr, reg, note]], 'via'} або None."""
    srcname = LANG_EN.get(src, 'the original language')
    summary, chars, terms, via = [], {}, {}, ''
    for i in range(0, len(lines), ANALYZE_STEP):
        part = lines[i:i + ANALYZE_STEP]
        known = ''
        if chars:
            known += 'Characters found so far: ' + '; '.join('%s (%s, %s)' % (c['name'], c['uk'], c['gender']) for c in chars.values()) + '\n'
        if summary:
            known += 'Story so far: ' + ' '.join(summary)[-600:] + '\n'
        prompt = ('These are %s subtitles of one episode (part %d of %d), to be translated into Ukrainian.\n%s'
                  'Return JSON with:\n'
                  '"summary": 2-3 sentences in Ukrainian — what happens in this part, relationships, tone;\n'
                  '"characters": every named character — "name" as in the subtitles, "uk" Ukrainian spelling '
                  '(Japanese names by the Kovalenko system: Сакура, Сьота, Тідзуру), "gender" f/m/? (deduce from context — '
                  'Ukrainian verb endings depend on it), "speech" in Ukrainian — how they talk (shy, rude, formal, calls X "senpai"…);\n'
                  '"terms": up to 40 items worth a glossary — slang, swearing, sexual vocabulary, moans/interjections, Japanese '
                  'loanwords and honorifics, idioms, recurring catchphrases; "t" exactly as in the subtitles, "tr" natural '
                  'spoken Ukrainian in the same register (crude stays crude, no euphemisms), "reg" one of: вульгарне, розмовне, '
                  'нейтральне, ніжне, вигук, запозичення, ім\'я; "note" short Ukrainian hint. Skip ordinary words.\n\n'
                  'Subtitles:\n%s' % (srcname, i // ANALYZE_STEP + 1, (len(lines) - 1) // ANALYZE_STEP + 1, known, '\n'.join(part)))
        j, name = llm_json(ANALYZE_SYSTEM if tr_adult() else ANALYZE_SYSTEM_STD, prompt, ANALYZE_SCHEMA)
        if j is None:
            if not via:
                return None              # жодна мовна модель не відповіла — перекладаємо без аналізу
            continue
        via = via or name
        if isinstance(j.get('summary'), str) and j['summary'].strip():
            summary.append(j['summary'].strip()[:500])
        for c in j.get('characters') or []:
            if isinstance(c, dict) and str(c.get('name') or '').strip():
                k = c['name'].strip().lower()
                old = chars.get(k, {})
                chars[k] = {'name': c['name'].strip()[:60], 'uk': str(c.get('uk') or old.get('uk') or c['name']).strip()[:60],
                            'gender': c.get('gender') if c.get('gender') in ('f', 'm') else old.get('gender', '?'),
                            'speech': str(c.get('speech') or old.get('speech') or '').strip()[:160]}
        for t in j.get('terms') or []:
            if isinstance(t, dict) and str(t.get('t') or '').strip() and str(t.get('tr') or '').strip():
                terms.setdefault(t['t'].strip().lower(), [t['t'].strip(), str(t['tr']).strip(), str(t.get('reg') or '').strip(),
                                                          str(t.get('note') or '').strip()])
        if progress:
            progress(min(1.0, (i + ANALYZE_STEP) / max(1, len(lines))))
    if not via:
        return None
    return {'summary': ' '.join(summary)[:1500], 'characters': list(chars.values())[:40],
            'terms': gloss_clean(terms.values()), 'via': via}


GENDER_UK = {'f': 'жін.', 'm': 'чол.'}


def ai_context(vid, r, lines, src, set_state):
    """Аналіз (з кешем data/aisubs/<id>/context.json) → TR_CTX.ctx і авто-терміни; нові — в глосарій тайтлу."""
    TR_CTX.ctx, TR_CTX.auto_items = '', []
    if not C.cfg.get('ai_context', True):
        return
    path = os.path.join(C.data, 'aisubs', vid, 'context.json')
    try:
        with open(path, encoding='utf-8') as f:
            ctx = json.load(f)
    except (OSError, ValueError):
        set_state(state='context', p=0)
        ctx = ai_analyze(lines, src, lambda f: set_state(p=f))
        if not ctx:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(ctx, f, ensure_ascii=False, indent=1)
    chars = ctx.get('characters') or []
    auto = [[c['name'], c['uk'], "ім'я", ' · '.join(x for x in (GENDER_UK.get(c.get('gender'), ''), c.get('speech', '')) if x)]
            for c in chars] + (ctx.get('terms') or [])
    TR_CTX.auto_items = gloss_clean(auto)
    sid = video_sid(r)
    if sid:                              # у глосарій тайтлу — тільки те, чого там ще нема (і нема в загальному)
        g = gloss_get(sid)
        have = {it[0].lower() for it in g['items'] + gloss_get('_')['items']}
        have |= {it[0].lower() for k in getattr(TR_CTX, 'sets', None) or [] for it in gloss_sets().get(k, {}).get('items', [])}
        new = [it for it in TR_CTX.auto_items if it[0].lower() not in have]
        if new:
            gloss_put(sid, g['notes'], g['items'] + new)
    lines_ = []
    if ctx.get('summary'):
        lines_.append('About this episode: ' + ctx['summary'])
    if chars:
        lines_.append('Characters (use correct Ukrainian gender endings for speakers and addressees): ' + '; '.join(
            '%s → %s (%s%s)' % (c['name'], c['uk'], {'f': 'female', 'm': 'male'}.get(c.get('gender'), 'gender unknown'),
                                ', ' + c['speech'] if c.get('speech') else '') for c in chars))
    TR_CTX.ctx = '\n'.join(lines_)


def tr_chain():
    """[(назва, ключ)] у порядку: основний, далі решта з ключами."""
    keys = {'local': C.cfg.get('local_url'), 'gemini': C.cfg.get('gemini_key'), 'deepl': C.cfg.get('deepl_key'),
            'azure': C.cfg.get('azure_key')}
    first = C.cfg.get('tr_main') if C.cfg.get('tr_main') in keys else 'gemini'
    order = [first] + [k for k in ('local', 'gemini', 'deepl', 'azure') if k != first]
    return [(k, keys[k].strip()) for k in order if (keys[k] or '').strip()]


def tr_foreign(src, out):
    """Слова перекладу з не-кириличними літерами, яких нема в оригіналі: «розglів», «비교є», «заваangيتي».
    Латинське слово, що є в оригіналі (OK, Wi-Fi, ім'я латиницею), — не помилка."""
    bad, low = [], src.lower()
    for w in re.findall(r"[^\W\d_]+(?:['’ʼ-][^\W\d_]+)*", out or ''):
        letters = [ch for ch in w if ch.isalpha()]
        if all('Ѐ' <= ch <= 'ӿ' for ch in letters):
            continue
        if not any('Ѐ' <= ch <= 'ӿ' for ch in letters) and w.lower() in low:
            continue
        bad.append(w)
    return bad


def tr_fix_foreign(fn, key, lines, out, src):
    """Рядки з «кашею» з інших абеток — перекласти ще раз, кожен окремо з двома попередніми репліками як контекстом."""
    bad = [i for i, (a, b) in enumerate(zip(lines, out)) if b != a and tr_foreign(a, b)]
    for i in bad[:40]:
        for _ in range(2):
            try:
                got = fn(key, lines[max(0, i - 2):i + 1], src)
            except Exception:
                return out
            if got and not tr_foreign(lines[i], got[-1]) and got[-1] != lines[i]:
                out[i] = got[-1]
                break
    return out


# ── «Жорсткіше» для 18+: модель після «розблокування» вже не відмовляє, але за звичкою пом'якшує («до біса» замість
# «до усрачки», «бовдур» замість «дебіл»). Окремий прохід бере репліки, де в оригіналі є груба чи відверта лексика,
# разом із перекладом і просить переписати переклад рівно з тією ж силою. Лише для тайтлів з набором 18+.
CRUDE_RE = re.compile(r"\b(fuck\w*|shit\w*|bitch\w*|cunt\w*|cock\w*|dick\w*|puss(y|ies)|cum\w*|jizz|slut\w*|whore\w*|"
                      r"tits?|titties|boobs?|ass(hole)?|asses|damn\w*|hell|bastard\w*|piss\w*|horny|lewd|pervert\w*|"
                      r"semen|sperm|creampie\w*|blowjob\w*|suck\w*|lick\w*|nipples?|clit\w*|orgasm\w*|moan\w*|"
                      r"pregnant|impregnat\w*|breed\w*|womb|cervix|finish(ing|ed)?|coming|inside me|sex\w*|naked|"
                      r"dumbass\w*|idiot\w*|moron\w*|stupid|shut up)\b", re.I)
HARDEN_SYSTEM = ('You are the editor of an uncensored Ukrainian translation of adult (18+) anime; all characters are adults. '
                 'Your only job: make each Ukrainian line exactly as crude, vulgar and explicit as its English original. '
                 'The translator tends to soften — undo that. Swearing → real Ukrainian swearing (бляха, блядь, сука, '
                 'хуй, пизда, дебіл, срань), sexual words → explicit spoken Ukrainian (член, кицька/пизда, цицьки, '
                 'трахати, кінчати, сперма), never euphemisms, medical terms or «до біса» where the original says «shit». '
                 'Keep meaning, speaker gender and length; do not add anything that is not in the original; if a line is '
                 'already equally strong, return it unchanged. Ukrainian Cyrillic only. Answer only with JSON.')


def crude_terms():
    """Вульгарні терміни з увімкнених наборів — теж ознака репліки, яку варто перевірити."""
    out = set()
    for k in getattr(TR_CTX, 'sets', None) or []:
        for it in gloss_sets().get(k, {}).get('items', []):
            if it[2] == 'вульгарне' and len(it[0]) > 2:
                out.add(it[0].lower())
    return out


def tr_harden(lines, out, batch=40):
    if not tr_adult() or not C.cfg.get('ai_harden', True):
        return out
    extra = crude_terms()
    idx = [i for i, l in enumerate(lines) if out[i] != l and (CRUDE_RE.search(l) or any(t in l.lower() for t in extra))]
    for b in range(0, len(idx), batch):
        part = idx[b:b + batch]
        pairs = [{'en': lines[i], 'uk': out[i]} for i in part]
        schema = {'type': 'object', 'required': ['lines'], 'properties': {'lines': {
            'type': 'array', 'items': {'type': 'string'}, 'minItems': len(part), 'maxItems': len(part)}}}
        gloss = gloss_prompt('\n'.join(lines[i] for i in part), 'en')
        prompt = ('Rewrite the "uk" of every pair so it matches the "en" in crudeness and explicitness. Return JSON '
                  '{"lines": [...]} with exactly %d Ukrainian strings in the same order.\n%s\n%s'
                  % (len(part), ('Glossary (follow it):\n' + gloss + '\n') if gloss else '',
                     json.dumps({'pairs': pairs}, ensure_ascii=False)))
        j, _ = llm_json(HARDEN_SYSTEM, prompt, schema)
        got = (j or {}).get('lines') or []
        if len(got) != len(part):
            continue
        for i, t in zip(part, got):
            t = t.strip() if isinstance(t, str) else ''
            if t and t != lines[i] and not tr_foreign(lines[i], t) and len(t) < len(out[i]) * 2 + 20:
                out[i] = t
    return out


def translate_uk(lines, src, progress=None):
    """Переклад українською першим перекладачем, у якого не скінчився ліміт. → (тексти, назва перекладача)."""
    errs = []
    for name, key in tr_chain():
        try:
            fn = {'local': local_translate, 'gemini': gemini_translate, 'deepl': deepl_translate,
                  'azure': azure_translate}[name]
            out = fn(key, lines, src, progress)
            if name in ('local', 'gemini'):  # DeepL/Azure такого не роблять — у мовних моделей буває
                out = tr_fix_foreign(fn, key, lines, out, src)
                if src == 'en':
                    out = tr_harden(lines, out)
            return out, name
        except TrError as e:
            errs.append(str(e) if TR_NAMES[name] in str(e) else '%s: %s' % (TR_NAMES[name], e))
            if not e.quota:
                raise RuntimeError('; '.join(errs))
        except RuntimeError as e:        # DeepL кидає RuntimeError: ліміт/ключ — пробуємо наступного
            errs.append(str(e) if TR_NAMES[name] in str(e) else '%s: %s' % (TR_NAMES[name], e))
    raise RuntimeError('; '.join(errs) or 'немає ключа перекладача')


def ai_audio_stream(path):
    """Номер звукової доріжки: «за замовчуванням», інакше перша."""
    try:
        j = json.loads(run([C.ffprobe, '-v', 'error', '-print_format', 'json', '-show_streams', '-select_streams', 'a', path],
                           60).stdout.decode('utf-8', 'replace') or '{}')
        st = j.get('streams') or []
        for i, a in enumerate(st):
            if (a.get('disposition') or {}).get('default'):
                return i
    except Exception:
        pass
    return 0


def ai_job(it):
    vid = it['id']
    r = DB.one('SELECT * FROM videos WHERE id=?', (vid,))
    if not r or not os.path.exists(r['path']):
        return ai_set(vid, state='error', err='Файл не знайдено')
    out = os.path.join(C.data, 'aisubs', vid)
    wav = os.path.join(C.data, 'aisubs', 'tmp-%s.wav' % vid)
    key = bool(tr_chain())
    TR_CTX.gloss_sids = [x for x in ('_', video_sid(r)) if x]
    TR_CTX.sets = gloss_title_sets(video_sid(r))[0]
    TR_CTX.ctx, TR_CTX.auto_items = '', []
    st = lambda **kw: ai_set(vid, **kw)
    have = [f for f in (os.listdir(out) if os.path.isdir(out) else []) if f.endswith('.srt') and f != 'uk.srt']
    if have and key and not os.path.exists(os.path.join(out, 'uk.srt')):
        try:                             # розпізнане вже є (раніше не було ключа) — лише перекласти
            segs = read_srt(os.path.join(out, have[0]))
            ai_context(vid, r, [x['t'] for x in segs], have[0][:-4], st)
            ai_set(vid, state='translate', p=0)
            uk, via = translate_uk([x['t'] for x in segs], have[0][:-4], lambda f: ai_set(vid, p=f))
            write_srt(os.path.join(out, 'uk.srt'), segs, uk)
            SUBS_CACHE.pop(vid, None)
            return ai_set(vid, state='done', p=1, err='', via=via)
        except Exception as e:
            SUBS_CACHE.pop(vid, None)
            return ai_set(vid, state='error', err=str(e)[-300:])
    src_n = ai_text_source(r) if key else None
    if src_n is not None:                # є англійські субтитри — перекладаємо їх: текст від людей, час точний, без Whisper
        try:
            ai_set(vid, state='translate', p=0, lang='en', src='subs')
            segs = read_vtt(subs_vtt(r, src_n) or b'')
            if len(segs) < 5:
                raise ValueError('замало реплік')
            ai_context(vid, r, [x['t'] for x in segs], 'en', st)
            ai_set(vid, state='translate', p=0)
            uk, via = translate_uk([x['t'] for x in segs], 'en', lambda f: ai_set(vid, p=f))
            write_srt(os.path.join(out, 'uk.srt'), segs, uk)
            SUBS_CACHE.pop(vid, None)
            return ai_set(vid, state='done', p=1, err='', via=via)
        except ValueError:
            pass                         # субтитри порожні чи картинкові — розпізнаємо звук, як звичайно
        except Exception as e:
            SUBS_CACHE.pop(vid, None)
            return ai_set(vid, state='error', err=str(e)[-300:])
    os.makedirs(os.path.dirname(wav), exist_ok=True)
    try:
        ai_set(vid, state='audio', p=0, src='audio')
        a = ai_audio_stream(r['path'])
        res = subprocess.run(['nice', '-n', '15', C.ffmpeg, '-v', 'error', '-y', '-i', r['path'], '-map', '0:a:%d' % a,
                              '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600)
        if res.returncode or not os.path.exists(wav):
            raise RuntimeError('не вдалося дістати звук: ' + res.stderr.decode('utf-8', 'replace')[-200:])
        ai_set(vid, state='model' if not os.path.isdir(ai_dir('models')) else 'recog', p=0)
        model = C.cfg.get('ai_model') if C.cfg.get('ai_model') in AI_MODELS else AI_MODELS[0]
        fast = C.cfg.get('ai_speed') == 'max'
        # звичайна: потік на ядро, найнижчий пріоритет; максимальна: усі потоки процесора, пріоритет вищий,
        # а Хата (gazda) на цей час вмикає режим продуктивності. Якість та сама — модель і пошук ті самі.
        threads = (os.cpu_count() or 4) if fast else max(1, min(4, (os.cpu_count() or 4) // 2 or 1))
        proc = subprocess.Popen(['nice', '-n', '5' if fast else '15', ai_py(), os.path.join(app_dir(), 'whisper_worker.py'), wav, model,
                                 ai_dir('models'), str(threads)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=ai_env(), text=True, encoding='utf-8')
        AI['proc'] = proc
        if fast:
            try:
                with open(ai_dir('boost'), 'w') as f:
                    f.write(str(proc.pid))
            except OSError:
                pass
        segs, lang, last = [], '', 0
        for line in proc.stdout:
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if 'lang' in j:
                lang = j['lang'] or ''
                ai_set(vid, state='recog', lang=lang, p=0)
            elif 't' in j:
                segs.append(j)
                if time.time() - last > 3:
                    last = time.time()
                    ai_set(vid, p=j['p'])
        err = proc.stderr.read()
        proc.wait()
        AI['proc'] = None
        if it.get('cancel') or any(x['id'] == vid and x.get('cancel') for x in ai_queue()):
            return
        if proc.returncode:
            raise RuntimeError('розпізнавання впало: ' + (err or '').strip()[-300:])
        if not segs:
            raise RuntimeError('мови не почуто')
        write_srt(os.path.join(out, '%s.srt' % (lang or 'xx')), segs)
        if lang != 'uk':
            if not key:
                SUBS_CACHE.pop(vid, None)
                return ai_set(vid, state='done', p=1, err='Без перекладу: немає ключа перекладача — є субтитри мовою оригіналу')
            ai_context(vid, r, [x['t'] for x in segs], lang, st)
            ai_set(vid, state='translate', p=0)
            uk, via = translate_uk([x['t'] for x in segs], lang, lambda f: ai_set(vid, p=f))
            write_srt(os.path.join(out, 'uk.srt'), segs, uk)
            SUBS_CACHE.pop(vid, None)
            return ai_set(vid, state='done', p=1, err='', via=via)
        SUBS_CACHE.pop(vid, None)
        ai_set(vid, state='done', p=1, err='')
    except Exception as e:
        SUBS_CACHE.pop(vid, None)
        ai_set(vid, state='error', err=str(e)[-300:])
    finally:
        AI['proc'] = None
        for f in (wav, ai_dir('boost')):
            try:
                os.remove(f)
            except OSError:
                pass


def ai_loop():
    with AI_LOCK:                    # після перезапуску незавершене — знову в чергу
        q = ai_queue()
        for it in q:
            if it['state'] in ('audio', 'model', 'recog', 'context', 'translate'):
                it.update(state='queued', p=0)
        ai_save_queue(q)
    while True:
        AI_WAKE.wait(60)
        AI_WAKE.clear()
        while ai_ready():
            it = next((x for x in ai_queue() if x['state'] == 'queued'), None)
            if not it:
                break
            AI['cur'] = it['id']
            ai_job(it)
            AI['cur'] = None
            with AI_LOCK:
                ai_save_queue([x for x in ai_queue() if not x.get('cancel')])


def ai_status():
    q = ai_queue()
    for it in q:
        r = DB.one('SELECT title, folder FROM videos WHERE id=?', (it['id'],))
        it['title'] = r['title'] if r else '(файл зник)'
    return {'ready': ai_ready(), 'install': AI['install'], 'log': AI['log'], 'model': C.cfg.get('ai_model') or AI_MODELS[0], 'speed': C.cfg.get('ai_speed') or 'normal', 'source': C.cfg.get('ai_source') or 'subs', 'context': C.cfg.get('ai_context', True), 'harden': C.cfg.get('ai_harden', True),
            'deepl': bool((C.cfg.get('deepl_key') or '').strip()), 'gemini': bool((C.cfg.get('gemini_key') or '').strip()),
            'azure': bool((C.cfg.get('azure_key') or '').strip()), 'azureRegion': C.cfg.get('azure_region') or '',
            'geminiModel': C.cfg.get('gemini_model') or '', 'local': bool((C.cfg.get('local_url') or '').strip()),
            'localUrl': C.cfg.get('local_url') or '', 'localModel': C.cfg.get('local_model') or '',
            'localToken': bool((C.cfg.get('local_key') or '').strip()), 'gloss': len(gloss_get('_')['items']), 'trMain': C.cfg.get('tr_main') or 'gemini', 'linux': sys.platform.startswith('linux'), 'queue': q}


def ai_post(d):
    op = d.get('op')
    if op == 'install':
        if AI['install'] != 'run' and not ai_ready():
            AI.update(install='run', log='Починаю…')
            threading.Thread(target=ai_install, daemon=True).start()
    elif op == 'add':
        ids = [x for x in d.get('ids') or [] if isinstance(x, str) and ID_RE.fullmatch(x)]
        with AI_LOCK:
            q = ai_queue()
            have = {it['id']: it for it in q}
            for vid in ids:
                if vid in have:
                    if have[vid]['state'] in ('error', 'done'):
                        have[vid].update(state='queued', p=0, err='', cancel=False)
                else:
                    q.append({'id': vid, 'state': 'queued', 'p': 0, 'at': time.time()})
            ai_save_queue(q)
        AI_WAKE.set()
    elif op == 'remove':                # прибрати з черги; якщо саме обробляється — зупинити
        vid = d.get('id')
        with AI_LOCK:
            q = ai_queue()
            for it in q:
                if it['id'] == vid:
                    it['cancel'] = True
            ai_save_queue([it for it in q if it['id'] != vid or AI['cur'] == vid])
        if AI['cur'] == vid and AI['proc']:
            try:
                AI['proc'].kill()
            except OSError:
                pass
    elif op == 'delete':                # прибрати готові субтитри ШІ відео (або всього тайтлу аніме)
        ids = [x for x in d.get('ids') or [] if isinstance(x, str) and ID_RE.fullmatch(x)]
        if d.get('sid'):
            ser = anime_series().get(str(d['sid']))
            ids += [r['id'] for r in (ser[1] if ser else [])]
        for vid in ids:
            if AI['cur'] == vid:
                continue
            shutil.rmtree(os.path.join(C.data, 'aisubs', vid), ignore_errors=True)
            SUBS_CACHE.pop(vid, None)
        with AI_LOCK:
            ai_save_queue([it for it in ai_queue() if it['id'] not in ids or it['id'] == AI['cur']])
    elif op == 'gloss_get':
        sid = str(d.get('sid') or '_')
        return dict(gloss_get(sid), ok=True, **gloss_sets_info(sid))
    elif op == 'gloss_sets':            # набори для тайтлу: список id або null — автоматично
        sid = str(d.get('sid') or '')
        if sid not in anime_series():
            return {'ok': False, 'error': 'Тайтл не знайдено'}
        sets = d.get('sets')
        gloss_set_sets(sid, None if sets is None else [str(x) for x in sets if isinstance(x, str)])
        return dict(gloss_get(sid), ok=True, **gloss_sets_info(sid))
    elif op == 'gloss_set_view':        # вміст набору — подивитись
        st = gloss_sets().get(str(d.get('id') or ''))
        return dict(st, ok=True) if st else {'ok': False, 'error': 'Набір не знайдено'}
    elif op in ('gloss', 'gloss_import'):
        sid = str(d.get('sid') or '_')
        if sid != '_' and sid not in anime_series():
            return {'ok': False, 'error': 'Тайтл не знайдено'}
        if op == 'gloss_import':        # файл: додати до наявного (ті самі терміни замінюються) або замінити все
            items, notes = gloss_parse_file(str(d.get('name') or ''), str(d.get('text') or '')[:900000])
            items = gloss_clean(items)
            if not items and not notes:
                return {'ok': False, 'error': 'У файлі не знайшов жодного терміна (потрібні колонки «Термін» і «Переклад»)'}
            old = gloss_get(sid)
            if d.get('mode') != 'replace':
                items = old['items'] + items
                notes = [x for x in [old['notes']] + notes if x]
            g = gloss_put(sid, '\n'.join(notes), items)
            return dict(g, ok=True, added=len(gloss_clean(items)) - (0 if d.get('mode') == 'replace' else len(old['items'])))
        if 'items' not in d:            # старі клієнти шлють вільний текст
            items, notes = gloss_parse_lines(d.get('text'))
            return dict(gloss_put(sid, '\n'.join(notes), items), ok=True)
        return dict(gloss_put(sid, d.get('notes'), d.get('items')), ok=True)
    elif op == 'clear':
        with AI_LOCK:
            ai_save_queue([it for it in ai_queue() if it['state'] not in ('done', 'error')])
    elif op == 'save':
        if str(d.get('gemini') or '').strip():          # новий ключ Gemini — одразу перевіряємо й вибираємо модель
            try:
                model = gemini_pick_model(str(d['gemini']).strip())
            except TrError as e:
                return {'ok': False, 'error': str(e)}
            with CFG_LOCK:
                C.cfg['gemini_key'], C.cfg['gemini_model'] = str(d['gemini']).strip()[:200], model
        if str(d.get('local') or '').strip():           # адреса ПК з моделлю — перевіряємо, що сервер відповідає
            url = local_base(d['local'])[:200]
            tok = str(d.get('localKey') or C.cfg.get('local_key') or '').strip()[:200]
            try:
                model = local_pick_model(url, {'Authorization': 'Bearer ' + tok} if tok else {})
            except TrError as e:
                return {'ok': False, 'error': str(e)}
            with CFG_LOCK:
                C.cfg['local_url'], C.cfg['local_key'], C.cfg['local_model'] = url, tok, model
        with CFG_LOCK:
            if 'key' in d:
                C.cfg['deepl_key'] = str(d.get('key') or '').strip()[:200]
            if 'azure' in d:
                C.cfg['azure_key'] = str(d.get('azure') or '').strip()[:200]
            if 'region' in d:
                C.cfg['azure_region'] = re.sub(r'[^a-z0-9]', '', str(d.get('region') or '').lower())[:40]
            if d.get('main') in TR_NAMES:
                C.cfg['tr_main'] = d['main']
            for k in d.get('forget') or []:
                if k in ('deepl_key', 'gemini_key', 'azure_key'):
                    C.cfg.pop(k, None)
                if k == 'local_key':                     # «Забути» локальну модель — адреса, токен і модель
                    for x in ('local_url', 'local_key', 'local_model'):
                        C.cfg.pop(x, None)
            if d.get('model') in AI_MODELS:
                C.cfg['ai_model'] = d['model']
            if d.get('speed') in ('normal', 'max'):
                C.cfg['ai_speed'] = d['speed']
            if isinstance(d.get('context'), bool):
                C.cfg['ai_context'] = d['context']
            if isinstance(d.get('harden'), bool):
                C.cfg['ai_harden'] = d['harden']
            if d.get('source') in ('subs', 'audio'):
                C.cfg['ai_source'] = d['source']
        save_config()
    elif op == 'usage':
        key = (C.cfg.get('deepl_key') or '').strip()
        if not key:
            return {'ok': False, 'error': 'Немає ключа'}
        try:
            u = deepl_call(key, 'usage')
            return {'ok': True, 'used': u.get('character_count'), 'limit': u.get('character_limit')}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
    else:
        return {'ok': False, 'error': 'невідома дія'}
    return dict(ai_status(), ok=True)


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
            HW['vaapi_dec'] = sorted(vdec) if vdec else None    # список, не множина: HW віддається в JSON налаштувань
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
            'cfg': dict({k: C.cfg[k] for k in ('autoplay_next', 'next_delay', 'resume', 'ui', 'theme')},
                        hataTheme=hata_theme())}


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
    'folders': [], 'anime_folder': '', 'manga_folder': '', 'port': 8800, 'open_browser': True, 'rescan_min': 10,
    # субтитри ШІ: ключі перекладачів і вибір (без них у DEFAULTS load_config їх відкидав — ключі зникали після перезапуску)
    'deepl_key': '', 'gemini_key': '', 'gemini_model': '', 'azure_key': '', 'azure_region': '', 'tr_main': 'gemini',
    'local_url': '', 'local_key': '', 'local_model': '',
    'ai_model': 'large-v3-turbo', 'ai_speed': 'normal', 'ai_source': 'subs', 'ai_context': True, 'ai_harden': True,
    'cache_gb': 30, 'frames_cache_gb': 3, 'sprites': True,
    'autoplay_next': True, 'next_delay': 8, 'resume': True,
    'ui': {'sort': 'score', 'dir': 'desc', 'group': 'all'},
    'theme': 'arch',
    'hwaccel': 'auto', 'hw_frames': False, 'max_height': 1080, 'prep_all': False,
    'password_hash': '', 'secret': '', 'cfg_version': 5,
}
THEMES = {'arch', 'tokyo', 'catppuccin', 'dracula', 'gruvbox', 'nord', 'sweet', 'exodia', 'cinema', 'projector',
          'chai', 'nich', 'lain', 'yahoda', 'nothing', 'papir', 'hata'}
# схеми панелі Хати → теми VidBox; «hata» = брати ту, що зараз вибрана в Хаті
HATA_SCHEMES = {'чай': 'chai', 'ніч': 'nich', 'lain': 'lain', 'ягода': 'yahoda', 'nothing': 'nothing', 'папір': 'papir'}


def hata_theme():
    """Яка схема зараз у панелі Хати (VidBox під Хатою читає її налаштування). None — Хати немає."""
    p = os.environ.get('HATA_CONFIG') or os.path.join(os.path.dirname(os.path.abspath(C.data)), 'hata.json')
    try:
        with open(p, encoding='utf-8') as f:
            return HATA_SCHEMES.get(json.load(f).get('scheme') or 'чай', 'chai')
    except (OSError, ValueError):
        return None
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
        if 'manga_folder' in d:
            a = str(d['manga_folder'] or '').strip()
            if a:
                a = os.path.abspath(os.path.expanduser(a))
                if not os.path.isdir(a):
                    return {'ok': False, 'error': 'Папку з мангою не знайдено: ' + a}
            if a != cfg.get('manga_folder', ''):
                cfg['manga_folder'] = a
                manga_scan_bg()
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
    out = {k: cfg[k] for k in DEFAULTS if k not in ('password_hash', 'secret', 'folders', 'cfg_version',
                                                    'deepl_key', 'gemini_key', 'azure_key', 'local_key')}   # ключі назовні не віддаємо
    out.update(
        folders=[{'path': f, 'count': counts.get(os.path.normcase(f), 0), 'exists': os.path.isdir(f)}
                 for f in cfg['folders']],
        caches={k: dir_size(os.path.join(C.data, k)) for k in ('thumbs', 'sprites', 'frames', 'prepared')},
        animeCount=counts.get(os.path.normcase(C.anime), 0) if C.anime else 0,
        animeTitles=len(anime_series()) if C.anime else 0,
        animeExists=bool(cfg.get('anime_folder')) and os.path.isdir(cfg['anime_folder']),
        mangaTitles=len(MANGA['titles']), mangaChapters=len(MANGA['chapters']),
        mangaExists=bool(cfg.get('manga_folder')) and os.path.isdir(cfg['manga_folder']),
        mangaSuggest=manga_suggest() if not cfg.get('manga_folder') else [],
        orphans=len(orphan_ids()), hasPassword=bool(cfg['password_hash']),
        ffmpeg=C.ffmpeg, data=C.data, version=VERSION, portNow=C.port,
        urls=['http://%s:%d' % (ip, C.port) for ip in lan_ips()])
    # для блоку «Про програму» у стилі neofetch
    t = DB.one('SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS size, COALESCE(SUM(duration), 0) AS dur '
               'FROM videos WHERE missing=0')
    out.update(host=socket.gethostname(), uptime=round(time.time() - STARTED), hataTheme=hata_theme(),
               totals={'videos': t['n'], 'size': t['size'], 'dur': t['dur']},
               python=platform.python_version(), os='%s %s' % (platform.system(), platform.release()),
               ffmpegVersion=ffmpeg_version())
    with HW_LOCK:
        hw = json.loads(json.dumps(HW, default=list))
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


def manga_suggest():
    """Теки зі словом «манга» поруч із відео або на дисках Hata — щоб додати одним натиском."""
    bases = ['/srv/disks'] if os.path.isdir('/srv/disks') else []
    for f in list(C.cfg.get('folders') or []) + [C.cfg.get('anime_folder') or '']:
        if f:
            bases.append(os.path.dirname(os.path.normpath(f)))
    out, seen = [], set()

    def look(d, depth):
        try:
            with os.scandir(d) as it:
                subs = [e for e in it if e.is_dir() and not manga_skip(e.name)]
        except OSError:
            return
        for e in subs:
            if re.search(r'manga|манга|манґа|manhwa|комікс|comics', e.name, re.I) and e.path not in seen:
                seen.add(e.path)
                out.append(e.path)
            elif depth < 2:
                look(e.path, depth + 1)
    for b in dict.fromkeys(x for x in bases if x):
        look(b, 0)
        if len(out) >= 5:
            break
    return out[:5]


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
        if os.path.isdir('/srv/disks'):    # під Hata диски підключені тут
            quick = [e.path for e in os.scandir('/srv/disks') if e.is_dir()] + quick
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

    def send_manga_cover(self, tid):
        t = MANGA['titles'].get(tid)
        if not t:
            return self.send_json({'error': 'not found'}, 404)
        f = manga_cover_file(t) or manga_thumb(t)
        if f:
            ext = os.path.splitext(f)[1].lower()
            return self.send_file(f, IMG_TYPES.get(ext, 'image/jpeg'), 'private, max-age=86400')
        fp, data, ctype = manga_page(MANGA['chapters'][t['chapters'][0]], 1)   # без ffmpeg і Pillow — як є
        if fp:
            return self.send_file(fp, ctype)
        return self.send_bytes(data, ctype)

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
                if path.startswith(('/api/', '/stream/', '/thumb/', '/live/', '/dlfile/', '/manga/', '/anime/', '/subs/')):
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
                m = re.fullmatch(r'/api/subs/(\w+)', path)
                if m:
                    r = self.video_row(m.group(1))
                    if not r:
                        return self.send_json({'error': 'not found'}, 404)
                    return self.send_json({'subs': [dict({k: t[k] for k in ('n', 'lang', 'label', 'def', 'forced')}, ai=bool(t.get('ai')), ext=t['src'][0] == 'f') for t in subs_list(r)],
                                           'ai': next(({'state': it['state'], 'p': it.get('p', 0), 'err': it.get('err', '')} for it in ai_queue() if it['id'] == r['id']), None),
                                           'aiReady': ai_ready()})
                m = re.fullmatch(r'/subs/(\w+)/(\d{1,3})\.vtt', path)
                if m:
                    r = self.video_row(m.group(1))
                    if not r:
                        return self.send_json({'error': 'not found'}, 404)
                    data = subs_vtt(r, int(m.group(2)))
                    # не вдалося перетворити — порожній WebVTT, щоб плеєр в апці не падав через субтитри
                    return self.send_bytes(data or b'WEBVTT\n\n', 'text/vtt; charset=utf-8',
                                           cache='no-store')   # субтитри ШІ можна переробити під тим самим номером
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
                if path == '/api/aisubs':
                    return self.send_json(ai_status())
                if path == '/api/manga':
                    return self.send_json(manga_list_json())
                m = re.fullmatch(r'/api/manga/(t|ch)/(\w+)', path)
                if m:
                    d = (manga_title_json if m.group(1) == 't' else manga_chapter_json)(m.group(2))
                    return self.send_json(d or {'error': 'not found'}, 200 if d else 404)
                m = re.fullmatch(r'/manga/cover/(\w+)', path)
                if m:
                    return self.send_manga_cover(m.group(1))
                m = re.fullmatch(r'/manga/page/(\w+)/(\d{1,5})', path)
                if m:
                    c = MANGA['chapters'].get(m.group(1))
                    n = int(m.group(2))
                    if not c or not 1 <= n <= len(c['pages']):
                        return self.send_json({'error': 'not found'}, 404)
                    fp, data, ctype = manga_page(c, n)
                    if fp:
                        return self.send_file(fp, ctype, 'private, max-age=604800')
                    return self.send_bytes(data, ctype, cache='private, max-age=604800')
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
                if path == '/api/manga/progress':
                    return self.send_json(manga_save_progress(self.json_body()))
                if path == '/api/manga/mark':
                    return self.send_json(manga_mark(self.json_body()))
                if path == '/api/manga/mode':
                    d = self.json_body()
                    if d.get('mode') not in MANGA_MODES or d.get('tid') not in MANGA['titles']:
                        return self.send_json({'ok': False}, 400)
                    manga_set(d['tid'], mode=d['mode'])
                    return self.send_json({'ok': True})
                if path == '/api/anime/link':
                    d = self.json_body()
                    ser = anime_series().get(str(d.get('sid', '')))
                    if not ser or not ser[0]:
                        return self.send_json({'ok': False, 'error': 'Тайтл не знайдено'}, 404)
                    sid = str(d['sid'])
                    DB.x('INSERT INTO anime_titles(sid, hint) VALUES(?,?) ON CONFLICT(sid) DO UPDATE SET hint=excluded.hint',
                         (sid, str(d.get('link') or '').strip()[:300]))
                    ANILIST_FAIL.pop(sid, None)
                    meta_queue(sid, anime_title(ser[0]), anilist_fetch, sid, ser[0])
                    return self.send_json({'ok': True})
                if path == '/api/manga/reset':
                    return self.send_json(manga_reset(self.json_body()))
                if path == '/api/aisubs':
                    self.body(1 << 20)          # імпорт глосарію файлом — більше за звичайні 64 КБ
                    return self.send_json(ai_post(self.json_body()))
                if path == '/api/manga/link':
                    return self.send_json(manga_link(self.json_body()))
                if path == '/api/manga/rescan':
                    manga_scan()
                    return self.send_json({'ok': True, 'titles': len(MANGA['titles'])})
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
    for target in (media_worker, prep_worker, rescan_loop, detect_hw, discovery_loop, ai_loop):
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
