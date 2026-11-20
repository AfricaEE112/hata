"""Розділ «Будинок»: заміри від плат ESP (RoomMonitor) — температура, світло, інтернет.

Плата надсилає POST /api/house/ingest з ключем X-Hata-Key (контракт — RoomMonitor/Хата-API.md у проєкті).
Час у пакеті відносний (age_s), бо годинник плати може бути не синхронізований: ts = час_отримання − age_s.
Плата повторює пакет, якщо відповідь загубилась, і досилає накопичене після збою, тож записи
ближчі за 5 с до наявних (той самий пристрій і ключ) пропускаються.

Сирі заміри зберігаються 30 днів, далі — середні по 10 хв (з мінімумом і максимумом) назавжди.
"""
import math
import os
import re
import sqlite3
import threading
import time

DB_PATH = None
LOCK = threading.Lock()
_con = None

RAW_DAYS = 30
AGG = 600                      # крок середніх для старих даних, с
ONLINE_S = 60
DEVICE_RE = re.compile(r'[A-Za-z0-9_.-]{1,32}')
KEY_RE = re.compile(r'[A-Za-z0-9_.-]{1,40}')
EVENT_TYPES = {'boot', 'power_off', 'power_on', 'inet_down', 'inet_up', 'wifi_up', 'wifi_down'}
RANGES = {'1h': (3600, 0), '24h': (86400, 120), '7d': (7 * 86400, 900), '30d': (30 * 86400, 3600),
          '1y': (365 * 86400, 86400)}

SCHEMA = '''
CREATE TABLE IF NOT EXISTS readings(device TEXT, key TEXT, ts INTEGER, value REAL);
CREATE INDEX IF NOT EXISTS ix_readings ON readings(device, key, ts);
CREATE INDEX IF NOT EXISTS ix_readings_ts ON readings(ts);
CREATE TABLE IF NOT EXISTS agg(device TEXT, key TEXT, ts INTEGER, avg REAL, min REAL, max REAL, n INTEGER,
  PRIMARY KEY(device, key, ts));
CREATE TABLE IF NOT EXISTS events(device TEXT, ts INTEGER, type TEXT, duration_s INTEGER);
CREATE INDEX IF NOT EXISTS ix_events ON events(device, ts);
CREATE TABLE IF NOT EXISTS devices(device TEXT PRIMARY KEY, last_seen INTEGER, fw TEXT, uptime_s INTEGER,
  temp_src TEXT, ip TEXT, first_seen INTEGER);
'''


class Bad(Exception):
    pass


def init(data_dir):
    global DB_PATH, _con
    os.makedirs(data_dir, exist_ok=True)
    DB_PATH = os.path.join(data_dir, 'house.db')
    _con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    _con.row_factory = sqlite3.Row
    with LOCK:
        _con.execute('PRAGMA journal_mode=WAL')
        _con.execute('PRAGMA synchronous=NORMAL')
        _con.executescript(SCHEMA)
        _con.commit()
    threading.Thread(target=_housekeeping, daemon=True).start()


def q(sql, a=()):
    with LOCK:
        return _con.execute(sql, a).fetchall()


def _num(v):
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)) and math.isfinite(v):
        return float(v)
    return None


# ───────────────────────── прийом ─────────────────────────

def ingest(d, ip=''):
    """Пакет від плати → база. Повертає, скільки нових записів додано."""
    if not isinstance(d, dict):
        raise Bad('очікую JSON-об’єкт')
    dev = str(d.get('device') or '')
    if not DEVICE_RE.fullmatch(dev):
        raise Bad('device: латинські літери, цифри, _.- (до 32)')
    now = time.time()
    rows, evs = [], []
    for r in (d.get('readings') or [])[:300]:
        if not isinstance(r, dict) or not isinstance(r.get('values'), dict):
            continue
        age = _num(r.get('age_s')) or 0
        ts = int(round(now - max(0, min(age, 30 * 86400))))
        for k, v in list(r['values'].items())[:64]:
            v = _num(v)
            if v is not None and KEY_RE.fullmatch(str(k)):
                rows.append((dev, str(k), ts, v))
    for e in (d.get('events') or [])[:100]:
        if not isinstance(e, dict) or e.get('type') not in EVENT_TYPES:
            continue
        age = _num(e.get('age_s')) or 0
        dur = _num(e.get('duration_s'))
        evs.append((dev, int(round(now - max(0, min(age, 30 * 86400)))), e['type'],
                    int(dur) if dur is not None and dur >= 0 else None))
    added = 0
    with LOCK:
        cur = _con.cursor()
        for row in rows:      # повтор того самого пакета чи досилання — не дублюємо
            if cur.execute('SELECT 1 FROM readings WHERE device=? AND key=? AND ts BETWEEN ? AND ? LIMIT 1',
                           (row[0], row[1], row[2] - 4, row[2] + 4)).fetchone():
                continue
            cur.execute('INSERT INTO readings(device, key, ts, value) VALUES(?,?,?,?)', row)
            added += 1
        for ev in evs:
            if cur.execute('SELECT 1 FROM events WHERE device=? AND type=? AND ts BETWEEN ? AND ? LIMIT 1',
                           (ev[0], ev[2], ev[1] - 10, ev[1] + 10)).fetchone():
                continue
            cur.execute('INSERT INTO events(device, ts, type, duration_s) VALUES(?,?,?,?)', ev)
            added += 1
        up = _num(d.get('uptime_s'))
        cur.execute('''INSERT INTO devices(device, last_seen, fw, uptime_s, temp_src, ip, first_seen) VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(device) DO UPDATE SET last_seen=excluded.last_seen, fw=excluded.fw,
                         uptime_s=excluded.uptime_s, temp_src=excluded.temp_src, ip=excluded.ip''',
                    (dev, int(now), str(d.get('fw') or '')[:40], int(up) if up is not None else None,
                     str(d.get('temp_src') or '')[:16], ip[:45], int(now)))
        _con.commit()
    return added


# ───────────────────────── читання ─────────────────────────

def _midnight(now):
    t = time.localtime(now)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def now_json():
    now = int(time.time())
    out = []
    for dv in q('SELECT * FROM devices ORDER BY device'):
        dev = dv['device']
        vals = {}
        for r in q('''SELECT r.key, r.value, r.ts FROM readings r
                      JOIN (SELECT key, MAX(ts) AS ts FROM readings WHERE device=? AND ts>? GROUP BY key) m
                      ON r.key=m.key AND r.ts=m.ts WHERE r.device=?''', (dev, now - 7 * 86400, dev)):
            vals[r['key']] = {'v': r['value'], 'ts': r['ts']}
        temps = {}
        for k in [k for k in vals if k.startswith('temp.')]:
            day = q('SELECT MIN(value) AS lo, MAX(value) AS hi FROM readings WHERE device=? AND key=? AND ts>=?',
                    (dev, k, _midnight(now)))[0]
            # тренд: середнє за останні 5 хв проти 25–30 хв тому
            a = q('SELECT AVG(value) AS v FROM readings WHERE device=? AND key=? AND ts>?', (dev, k, now - 300))[0]['v']
            b = q('SELECT AVG(value) AS v FROM readings WHERE device=? AND key=? AND ts BETWEEN ? AND ?',
                  (dev, k, now - 1800, now - 1500))[0]['v']
            temps[k] = {'min': day['lo'], 'max': day['hi'],
                        'trend': round(a - b, 2) if a is not None and b is not None else None}
        out.append({'device': dev, 'lastSeen': dv['last_seen'], 'online': now - (dv['last_seen'] or 0) < ONLINE_S,
                    'fw': dv['fw'], 'uptime': dv['uptime_s'], 'tempSrc': dv['temp_src'], 'ip': dv['ip'],
                    'values': vals, 'temps': temps})
    return {'now': now, 'devices': out}


def series(device, key, rng):
    if rng not in RANGES:
        rng = '24h'
    span, step = RANGES[rng]
    now = int(time.time())
    start = now - span
    pts = []
    raw_from = max(start, now - RAW_DAYS * 86400)
    if start < raw_from:     # старіше за 30 днів — лише середні
        b = max(step, AGG)
        for r in q('''SELECT (ts/?)*? AS t, SUM(avg*n)/SUM(n) AS v, MIN(min) AS lo, MAX(max) AS hi FROM agg
                      WHERE device=? AND key=? AND ts>=? AND ts<? GROUP BY t ORDER BY t''',
                   (b, b, device, key, start, raw_from)):
            pts.append([r['t'], round(r['v'], 3), r['lo'], r['hi']])
    if step:
        for r in q('''SELECT (ts/?)*? AS t, AVG(value) AS v, MIN(value) AS lo, MAX(value) AS hi FROM readings
                      WHERE device=? AND key=? AND ts>=? GROUP BY t ORDER BY t''', (step, step, device, key, raw_from)):
            pts.append([r['t'], round(r['v'], 3), r['lo'], r['hi']])
    else:
        for r in q('SELECT ts, value FROM readings WHERE device=? AND key=? AND ts>=? ORDER BY ts', (device, key, raw_from)):
            pts.append([r['ts'], r['value']])
    return {'device': device, 'key': key, 'range': rng, 'from': start, 'to': now, 'step': step, 'points': pts}


def events_json(rng, device=None):
    span = RANGES.get(rng, RANGES['24h'])[0]
    since = int(time.time()) - span
    sql = 'SELECT * FROM events WHERE ts>=?' + (' AND device=?' if device else '') + ' ORDER BY ts'
    rows = q(sql, (since, device) if device else (since,))
    return {'events': [{'device': r['device'], 'ts': r['ts'], 'type': r['type'], 'duration': r['duration_s']} for r in rows],
            'gaps': gaps(rows)}


def gaps(rows):
    """Проміжки без світла й без інтернету для заштрихування на графіку."""
    out, open_ = [], {}
    for r in rows:
        t, typ, dur = r['ts'], r['type'], r['duration_s']
        if typ in ('power_off', 'inet_down', 'wifi_down'):
            open_[(r['device'], typ)] = t
        elif typ in ('power_on', 'inet_up', 'wifi_up'):
            kind = 'inet' if typ == 'inet_up' else 'power'
            start = open_.pop((r['device'], {'power_on': 'power_off', 'inet_up': 'inet_down', 'wifi_up': 'wifi_down'}[typ]), None)
            if start is None and dur:
                start = t - dur
            if start is not None:
                out.append({'device': r['device'], 'kind': kind, 'from': start, 'to': t, 'source': typ})
    now = int(time.time())
    for (dev, typ), start in open_.items():    # ще триває
        out.append({'device': dev, 'kind': 'inet' if typ == 'inet_down' else 'power', 'from': start, 'to': now, 'open': True})
    return out


# ───────────────────────── прибирання ─────────────────────────

def compact(now=None):
    """Сирі заміри, старші за 30 днів → середні по 10 хв."""
    now = now or int(time.time())
    edge = now - RAW_DAYS * 86400
    edge -= edge % AGG
    with LOCK:
        _con.execute('''INSERT OR REPLACE INTO agg(device, key, ts, avg, min, max, n)
                        SELECT device, key, (ts/?)*?, AVG(value), MIN(value), MAX(value), COUNT(*) FROM readings
                        WHERE ts<? GROUP BY device, key, (ts/?)*?''', (AGG, AGG, edge, AGG, AGG))
        n = _con.execute('DELETE FROM readings WHERE ts<?', (edge,)).rowcount
        _con.commit()
    return n


def _housekeeping():
    while True:
        try:
            compact()
        except sqlite3.Error as e:
            print('Будинок: прибирання бази не вдалося:', e, flush=True)
        time.sleep(6 * 3600)
