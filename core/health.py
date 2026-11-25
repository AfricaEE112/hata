"""ТО — техобслуговування Хати: щохвилинні заміри всього сервера, події й тренди.

Працює всередині gazda (root): лише так читаються лічильники енергії процесора, введення-виведення чужих
процесів і SMART. Панель питає дані через gazda ({"do": "health", "op": ...}).

Що збирається (раз на хвилину; повільні показники — раз на 10 хв):
  процесор (завантаження, частота, температура, споживання, тротлінг), усі датчики температури й кулери,
  пам'ять, батарея (заряд, знос, цикли, споживання), мережа (трафік, сигнал Wi-Fi, доступність інтернету),
  диски (температура, сон, навантаження, заповненість, лічильники SMART), служби, режим продуктивності,
  черга субтитрів ШІ.
Події: сон і пробудження дисків (і хто розбудив), відвали й помилки USB/дисків із журналу ядра, увімкнення
й раптові вимкнення сервера, відключення світла (живлення від батареї), інтернету, падіння служб, перегрів,
зміни SMART, копії, субтитри ШІ.

Зберігання — SQLite на системному SSD (/var/lib/hata/health.db; запис на зовнішні диски будив би їх):
сирі заміри — 8 днів, далі годинні мін/сер/макс — 400 днів, далі доби — назавжди. У базу пишемо пачками
раз на 10 хв (і перед кожним запитом панелі), щоб не смикати SSD щохвилини.
"""
import json
import os
import re
import socket
import sqlite3
import subprocess
import threading
import time

DB_PATH = '/var/lib/hata/health.db'
RAW_DAYS = 8
HOUR_DAYS = 400
TOUCH_DAYS = 90
EVENT_DAYS = 800
FLUSH_EVERY = 600
SLOW_EVERY = 600
LOCK = threading.RLock()

# Лічильники (ростуть самі): у графіках показуємо приріст за проміжок, у таблиці — початок, кінець і різницю.
COUNTER_RE = re.compile(r'\.(load_cycles|cycles|hours|crc|realloc|pending|uncorrect|media_errors|throttle|spinups)$|^bat\.cycles$')
SLOW_RE = re.compile(r'\.(load_cycles|cycles|hours|crc|realloc|pending|uncorrect|media_errors|life|used|spare)$|^(bat\.(health|cycles|design)|svc\..*)$')

DEFAULT_LIMITS = {'disk_temp': 50, 'cpu_temp': 90, 'cpu_hot_min': 15, 'parks_day': 300, 'wakes_day': 24,
                  'bat_drop': 3, 'backup_days': 2}
LIMIT_RANGE = {'disk_temp': (35, 70), 'cpu_temp': (60, 105), 'cpu_hot_min': (1, 600), 'parks_day': (10, 100000),
               'wakes_day': (2, 1000), 'bat_drop': (1, 50), 'backup_days': (1, 30)}

SCHEMA = '''
CREATE TABLE IF NOT EXISTS samples(ts INTEGER, key TEXT, v REAL);
CREATE INDEX IF NOT EXISTS ix_samples ON samples(key, ts);
CREATE INDEX IF NOT EXISTS ix_samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS hourly(ts INTEGER, key TEXT, avg REAL, min REAL, max REAL, last REAL, n INTEGER, PRIMARY KEY(key, ts));
CREATE TABLE IF NOT EXISTS daily(ts INTEGER, key TEXT, avg REAL, min REAL, max REAL, last REAL, n INTEGER, PRIMARY KEY(key, ts));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts INTEGER, kind TEXT, subj TEXT, lvl TEXT, text TEXT, dur INTEGER, data TEXT);
CREATE INDEX IF NOT EXISTS ix_events ON events(ts);
CREATE INDEX IF NOT EXISTS ix_events_kind ON events(kind, ts);
CREATE TABLE IF NOT EXISTS touch(ts INTEGER, disk TEXT, who TEXT, bytes INTEGER);
CREATE INDEX IF NOT EXISTS ix_touch ON touch(disk, ts);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
'''


def fread(path, default=''):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return default


def fint(path):
    v = fread(path)
    try:
        return int(v)
    except ValueError:
        return None


def local_day(ts):
    t = time.localtime(ts)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def dur_text(s):
    s = int(s or 0)
    if s < 90:
        return '%d с' % s
    if s < 5400:
        return '%d хв' % round(s / 60)
    if s < 86400 * 2:
        return '%d год %d хв' % (s // 3600, s % 3600 // 60)
    return '%d дн %d год' % (s // 86400, s % 86400 // 3600)


# ───────────────────────── сховище ─────────────────────────

class Store:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False, timeout=20)
        self.con.row_factory = sqlite3.Row
        with LOCK:
            self.con.execute('PRAGMA journal_mode=WAL')
            self.con.execute('PRAGMA synchronous=NORMAL')
            self.con.executescript(SCHEMA)
            self.con.commit()
        if os.geteuid() == 0:     # власник — hata: так нічні копії панелі (від hata) можуть зробити знімок бази
            try:
                import pwd
                pw = pwd.getpwnam('hata')
                for f in (path, path + '-wal', path + '-shm'):
                    if os.path.exists(f):
                        os.chown(f, pw.pw_uid, pw.pw_gid)
            except (KeyError, OSError):
                pass
        self.buf, self.evbuf, self.touchbuf = [], [], []
        self.flushed = time.time()

    def q(self, sql, a=()):
        with LOCK:
            return self.con.execute(sql, a).fetchall()

    def meta(self, k, default=None):
        r = self.q('SELECT v FROM meta WHERE k=?', (k,))
        if not r:
            return default
        try:
            return json.loads(r[0]['v'])
        except ValueError:
            return default

    def set_meta(self, k, v):
        with LOCK:
            self.con.execute('INSERT OR REPLACE INTO meta(k, v) VALUES(?,?)', (k, json.dumps(v, ensure_ascii=False)))
            self.con.commit()

    def add(self, ts, key, v):
        if v is None:
            return
        try:
            v = float(v)
        except (TypeError, ValueError):
            return
        if v != v:          # NaN
            return
        with LOCK:
            self.buf.append((int(ts), key, round(v, 3)))

    def event(self, ts, kind, subj='', lvl='dim', text='', dur=None, data=None):
        with LOCK:
            self.evbuf.append((int(ts), kind, subj or '', lvl, text, int(dur) if dur is not None else None,
                               json.dumps(data, ensure_ascii=False) if data else None))

    def touched(self, ts, disk, who, nbytes):
        with LOCK:
            self.touchbuf.append((int(ts), disk, who, int(nbytes)))

    def flush(self, force=False):
        with LOCK:
            if not (self.buf or self.evbuf or self.touchbuf) and not force:
                return
            cur = self.con.cursor()
            cur.executemany('INSERT INTO samples(ts, key, v) VALUES(?,?,?)', self.buf)
            cur.executemany('INSERT INTO events(ts, kind, subj, lvl, text, dur, data) VALUES(?,?,?,?,?,?,?)', self.evbuf)
            cur.executemany('INSERT INTO touch(ts, disk, who, bytes) VALUES(?,?,?,?)', self.touchbuf)
            self.buf, self.evbuf, self.touchbuf = [], [], []
            self.con.commit()
            self.flushed = time.time()
            self.rollup()

    def rollup(self, now=None):
        """Завершені години → hourly, завершені доби → daily; старе прибираємо."""
        now = int(now or time.time())
        hour_now = now - now % 3600
        with LOCK:
            done = self.meta('rolled_hour')
            if done is None:
                r = self.con.execute('SELECT MIN(ts) AS t FROM samples').fetchone()
                done = (r['t'] - r['t'] % 3600) if r and r['t'] is not None else hour_now
            for h in range(done, hour_now, 3600):
                self._bucket('samples', 'hourly', h, h + 3600)
            if hour_now > done:
                self.set_meta('rolled_hour', hour_now)
            day_now = local_day(now)
            dd = self.meta('rolled_day')
            if dd is None:
                r = self.con.execute('SELECT MIN(ts) AS t FROM hourly').fetchone()
                dd = local_day(r['t']) if r and r['t'] is not None else day_now
            d = dd
            while d < day_now:
                nd = local_day(d + 86400 + 7200)            # +2 год — через перехід на літній/зимовий час
                self._bucket('hourly', 'daily', d, nd)
                d = nd
            if day_now > dd:
                self.set_meta('rolled_day', day_now)
            self.con.execute('DELETE FROM samples WHERE ts<?', (now - RAW_DAYS * 86400,))
            self.con.execute('DELETE FROM hourly WHERE ts<?', (now - HOUR_DAYS * 86400,))
            self.con.execute('DELETE FROM touch WHERE ts<?', (now - TOUCH_DAYS * 86400,))
            self.con.execute('DELETE FROM events WHERE ts<?', (now - EVENT_DAYS * 86400,))
            self.con.commit()

    def _bucket(self, src, dst, a, b):
        acc = {}
        if src == 'samples':
            for r in self.con.execute('SELECT ts, key, v FROM samples WHERE ts>=? AND ts<? ORDER BY ts', (a, b)):
                x = acc.setdefault(r['key'], [0.0, r['v'], r['v'], r['v'], 0])
                x[0] += r['v']; x[1] = min(x[1], r['v']); x[2] = max(x[2], r['v']); x[3] = r['v']; x[4] += 1
        else:
            for r in self.con.execute('SELECT ts, key, avg, min, max, last, n FROM hourly WHERE ts>=? AND ts<? ORDER BY ts', (a, b)):
                x = acc.setdefault(r['key'], [0.0, r['min'], r['max'], r['last'], 0])
                x[0] += r['avg'] * r['n']; x[1] = min(x[1], r['min']); x[2] = max(x[2], r['max']); x[3] = r['last']; x[4] += r['n']
        self.con.executemany('INSERT OR REPLACE INTO %s(ts, key, avg, min, max, last, n) VALUES(?,?,?,?,?,?,?)' % dst,
                             [(a, k, round(x[0] / x[4], 3), x[1], x[2], x[3], x[4]) for k, x in acc.items() if x[4]])

    # ── читання ──

    def value_at(self, key, t, after=False):
        """Останнє відоме значення не пізніше t (after=True — перше не раніше t)."""
        op, order = ('>=', 'ASC') if after else ('<=', 'DESC')
        for sql in ('SELECT v FROM samples WHERE key=? AND ts%s? ORDER BY ts %s LIMIT 1',
                    'SELECT last AS v FROM hourly WHERE key=? AND ts%s? ORDER BY ts %s LIMIT 1',
                    'SELECT last AS v FROM daily WHERE key=? AND ts%s? ORDER BY ts %s LIMIT 1'):
            r = self.q(sql % (op, order), (key, t))
            if r:
                return r[0]['v']
        return None

    def rows(self, key, a, b):
        """[(t, avg, min, max, last)] з найдетальнішого джерела, що покриває [a, b)."""
        now = time.time()
        if a >= now - RAW_DAYS * 86400 + 3600:
            return [(r['ts'], r['v'], r['v'], r['v'], r['v']) for r in
                    self.q('SELECT ts, v FROM samples WHERE key=? AND ts>=? AND ts<? ORDER BY ts', (key, a, b))]
        src = 'hourly' if a >= now - HOUR_DAYS * 86400 + 86400 else 'daily'
        out = [(r['ts'], r['avg'], r['min'], r['max'], r['last']) for r in
               self.q('SELECT ts, avg, min, max, last FROM %s WHERE key=? AND ts>=? AND ts<? ORDER BY ts' % src, (key, a, b))]
        if src == 'hourly':       # поточна незавершена година — із сирих
            last_h = out[-1][0] + 3600 if out else a
            out += [(r['ts'], r['v'], r['v'], r['v'], r['v']) for r in
                    self.q('SELECT ts, v FROM samples WHERE key=? AND ts>=? AND ts<? ORDER BY ts', (key, max(a, last_h), b))]
        return out

    def keys(self, since):
        ks = {r['key'] for r in self.q('SELECT DISTINCT key FROM samples WHERE ts>=?', (since,))}
        ks |= {r['key'] for r in self.q('SELECT DISTINCT key FROM hourly WHERE ts>=?', (since,))}
        return sorted(ks)


# ───────────────────────── датчики ─────────────────────────

def hwmon_sensors():
    """{ключ: значення} — температури й кулери з hwmon (усе, що віддає ноутбук)."""
    out = {}
    for h in sorted(os.listdir('/sys/class/hwmon')) if os.path.isdir('/sys/class/hwmon') else []:
        p = '/sys/class/hwmon/' + h
        chip = fread(p + '/name') or h
        if chip == 'coretemp':          # процесор окремо — як cpu.temp
            continue
        short = {'acpitz': 'acpi', 'iwlwifi_1': 'wifi', 'iwlwifi': 'wifi', 'nvme': 'nvme', 'pch_tigerlake': 'pch',
                 'BAT0': 'bat', 'BAT1': 'bat', 'drivetemp': 'drive', 'amdgpu': 'gpu', 'nouveau': 'gpu', 'k10temp': 'cpu'}.get(chip, re.sub(r'[^a-z0-9]', '', chip.lower())[:10] or 'hw')
        temps = sorted(f for f in os.listdir(p) if re.fullmatch(r'temp\d+_input', f)) if os.path.isdir(p) else []
        for f in temps[:4]:
            v = fint(p + '/' + f)
            if v is None or v <= 0 or v > 150000:
                continue
            lab = re.sub(r'[^a-z0-9]', '', fread(p + '/' + f.replace('_input', '_label')).lower())[:10]
            key = 't.%s%s' % (short, ('.' + lab) if len(temps) > 1 and lab else ('.%s' % f[4:-6] if len(temps) > 1 else ''))
            if key not in out and len([k for k in out if k.startswith('t.')]) < 14:
                out[key] = round(v / 1000, 1)
        for f in sorted(x for x in os.listdir(p) if re.fullmatch(r'fan\d+_input', x)) if os.path.isdir(p) else []:
            v = fint(p + '/' + f)
            if v is not None and 0 <= v < 20000:
                out['fan.%s%s' % (short, f[3:-6])] = v
    return out


def cpu_temp():
    best = None
    for z in sorted(os.listdir('/sys/class/thermal')) if os.path.isdir('/sys/class/thermal') else []:
        t, kind = fint('/sys/class/thermal/%s/temp' % z), fread('/sys/class/thermal/%s/type' % z)
        if t is not None and (kind.startswith(('x86_pkg', 'acpitz', 'cpu')) or best is None):
            best = t / 1000
            if kind.startswith('x86_pkg'):
                break
    if best is None:
        for h in os.listdir('/sys/class/hwmon') if os.path.isdir('/sys/class/hwmon') else []:
            if fread('/sys/class/hwmon/%s/name' % h) in ('coretemp', 'k10temp'):
                v = fint('/sys/class/hwmon/%s/temp1_input' % h)
                if v:
                    best = v / 1000
    return round(best, 1) if best is not None else None


def battery():
    base = '/sys/class/power_supply'
    if not os.path.isdir(base):
        return None
    ac = None
    for a in os.listdir(base):
        if fread('%s/%s/type' % (base, a)) == 'Mains':
            ac = fread('%s/%s/online' % (base, a)) == '1'
    for b in sorted(os.listdir(base)):
        p = '%s/%s' % (base, b)
        if fread(p + '/type') != 'Battery':
            continue
        full, design = fint(p + '/energy_full') or fint(p + '/charge_full'), fint(p + '/energy_full_design') or fint(p + '/charge_full_design')
        w = fint(p + '/power_now')
        if w is None and fint(p + '/current_now') is not None and fint(p + '/voltage_now') is not None:
            w = fint(p + '/current_now') * fint(p + '/voltage_now') / 1e6
        return {'pct': fint(p + '/capacity'), 'ac': ac if ac is not None else fread(p + '/status') != 'Discharging',
                'health': round(full / design * 100, 1) if full and design else None, 'cycles': fint(p + '/cycle_count') or None,
                'w': round(w / 1e6, 2) if w else None, 'status': fread(p + '/status')}
    return None


def prev_boot_end():
    try:
        out = subprocess.run(['journalctl', '-b', '-1', '-n', '1', '-o', 'json', '--no-pager'], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, timeout=20).stdout
        return int(json.loads(out.splitlines()[-1]).get('__REALTIME_TIMESTAMP', 0)) // 1000000 or None
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def proc_stat():
    try:
        v = [int(x) for x in fread('/proc/stat').splitlines()[0].split()[1:]]
        return v[3] + (v[4] if len(v) > 4 else 0), sum(v)
    except (IndexError, ValueError):
        return None


def rapl_uj():
    tot = None
    for p in ('/sys/class/powercap/intel-rapl:0/energy_uj', '/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj'):
        v = fint(p)
        if v is not None:
            return v, fint(os.path.dirname(p) + '/max_energy_range_uj') or 2 ** 32
    return tot


def throttle_total():
    tot, seen = 0, False
    for p in os.listdir('/sys/devices/system/cpu') if os.path.isdir('/sys/devices/system/cpu') else []:
        if not re.fullmatch(r'cpu\d+', p):
            continue
        for f in ('core_throttle_count', 'package_throttle_count'):
            v = fint('/sys/devices/system/cpu/%s/thermal_throttle/%s' % (p, f))
            if v is not None:
                tot += v
                seen = True
    return tot if seen else None


def cpu_freq():
    fs = [fint(p) for p in __import__('glob').glob('/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq')]
    fs = [f for f in fs if f]
    return round(sum(fs) / len(fs) / 1000) if fs else None


def mem():
    info = {}
    for line in fread('/proc/meminfo').splitlines():
        k, _, v = line.partition(':')
        if v.split():
            info[k] = int(v.split()[0]) * 1024
    t, a = info.get('MemTotal', 0), info.get('MemAvailable', 0)
    st, sf = info.get('SwapTotal', 0), info.get('SwapFree', 0)
    return (round((t - a) / t * 100, 1) if t else None), (round((st - sf) / st * 100, 1) if st else None), t - a


def net_bytes():
    rx = tx = 0
    for line in fread('/proc/net/dev').splitlines()[2:]:
        name, _, v = line.partition(':')
        name, v = name.strip(), v.split()
        if name != 'lo' and not name.startswith(('docker', 'veth', 'br-', 'tailscale')) and len(v) > 8:
            rx += int(v[0]); tx += int(v[8])
    return rx, tx


def wifi_signal():
    for line in fread('/proc/net/wireless').splitlines()[2:]:
        p = line.split()
        if len(p) > 3:
            try:
                v = float(p[3].rstrip('.'))
                return v if v < 0 else v - 256 if v > 63 else None
            except ValueError:
                pass
    return None


def inet_ping():
    """(мс до 1.1.1.1/8.8.8.8 або None, якщо інтернету немає) — TCP-з'єднання, без сторонніх програм."""
    for host, port in (('1.1.1.1', 443), ('8.8.8.8', 53)):
        t = time.monotonic()
        try:
            s = socket.create_connection((host, port), 3)
            s.close()
            return round((time.monotonic() - t) * 1000, 1)
        except OSError:
            continue
    return None


def route_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ''


def diskstats():
    out = {}
    for line in fread('/proc/diskstats').splitlines():
        p = line.split()
        if len(p) > 12:
            out[p[2]] = (int(p[5]), int(p[9]), int(p[12]))    # прочитано, записано секторів; мс зайнятості
    return out


def usb_info(kname):
    """Через який USB-міст підключено диск: (порт, швидкість Мбіт/с, назва мосту)."""
    p = os.path.realpath('/sys/block/%s/device' % kname)
    while p and p != '/' and '/usb' in p:
        if os.path.exists(p + '/speed') and os.path.exists(p + '/idVendor'):
            prod = (fread(p + '/manufacturer') + ' ' + fread(p + '/product')).strip()
            return os.path.basename(p), fint(p + '/speed') or None, prod or '%s:%s' % (fread(p + '/idVendor'), fread(p + '/idProduct'))
        p = os.path.dirname(p)
    return None


def usb_names():
    out = {}
    for d in os.listdir('/sys/bus/usb/devices') if os.path.isdir('/sys/bus/usb/devices') else []:
        if re.fullmatch(r'\d+-[\d.]+', d):
            p = '/sys/bus/usb/devices/' + d
            out[d] = (fread(p + '/manufacturer') + ' ' + fread(p + '/product')).strip()
    return out


# ───────────────────────── хто торкається дисків ─────────────────────────

def proc_io():
    out = {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        txt = fread('/proc/%s/io' % pid)
        rb = wb = 0
        for line in txt.splitlines():
            if line.startswith('read_bytes:'):
                rb = int(line.split()[1])
            elif line.startswith('write_bytes:'):
                wb = int(line.split()[1])
        if txt:
            out[int(pid)] = rb + wb
    return out


def proc_label(pid):
    """Зрозуміла назва: служба systemd (і програма, якщо це не вона сама), термінал або потік ядра."""
    cg = fread('/proc/%d/cgroup' % pid)
    comm = fread('/proc/%d/comm' % pid)
    m = re.search(r'system\.slice/([\w@.-]+)\.service', cg)
    if m:
        unit = m.group(1)
        return unit if comm in ('', unit, unit[:15], 'python3', 'python') else '%s (%s)' % (unit, comm)
    if 'session-' in cg:
        return '%s (термінал)' % (comm or '?')
    return comm or '?'


def proc_hits(pids, paths, devs):
    """{pid: True}, якщо процес тримає відкритий файл/теку на диску (за шляхами монтування або /dev/sdX)."""
    hit = {}
    for pid in pids:
        targets = []
        try:
            fds = os.listdir('/proc/%d/fd' % pid)
        except OSError:
            fds = []
        for fd in fds[:4000]:
            try:
                targets.append(os.readlink('/proc/%d/fd/%s' % (pid, fd)))
            except OSError:
                pass
        try:
            targets.append(os.readlink('/proc/%d/cwd' % pid))
        except OSError:
            pass
        for t in targets:
            if any(t == p or t.startswith(p + '/') for p in paths) or any(t == d or (t.startswith(d) and t[len(d):].isdigit()) for d in devs):
                hit[pid] = True
                break
    return hit


# ───────────────────────── журнал ядра ─────────────────────────

KERNEL_RULES = [
    (re.compile(r'usb (?P<p>\d+-[\d.]+): USB disconnect'), 'usb_off', 'yel'),
    (re.compile(r'usb (?P<p>\d+-[\d.]+): new (?P<speed>\S+) USB device'), 'usb_on', 'dim'),
    (re.compile(r'usb (?P<p>\d+-[\d.]+): reset (?P<speed>\S+) USB device'), 'usb_reset', 'yel'),
    (re.compile(r'usb (?P<p>\d+-[\d.]+):.*(?:error -110|error -71|error=-110|error=-71|device descriptor read.*error|device not accepting address)'), 'usb_err', 'red'),
    (re.compile(r'usb usb(?P<bus>\d+)-port(?P<port>[\d.]+): (?:unable to enumerate|Cannot enable|cannot reset|attempt power cycle)'), 'usb_err', 'red'),
    (re.compile(r'usb usb(?P<bus>\d+)-port(?P<port>[\d.]+): over-current'), 'overcurrent', 'red'),
    (re.compile(r'(?:I/O error, dev |Buffer I/O error on dev(?:ice)? )(?P<dev>sd[a-z]+|nvme\d+n\d+)'), 'io_error', 'red'),
    (re.compile(r'sd (?P<scsi>\d+:\d+:\d+:\d+): (?:\[(?P<dev>sd[a-z]+)\] )?.*(?:Device offlined|rejecting I/O to offline)'), 'offline', 'red'),
    (re.compile(r'Out of memory: Killed process \d+ \((?P<proc>[^)]+)\)'), 'oom', 'red'),
    (re.compile(r'(?:Package|Core) temperature above threshold|cpu clock throttled'), 'throttle_k', 'yel'),
]


def scsi_dev(addr):
    for b in os.listdir('/sys/class/scsi_device/%s/device/block' % addr) if os.path.isdir('/sys/class/scsi_device/%s/device/block' % addr) else []:
        return b
    return ''


def kernel_text(kind, m, msg, usbn, disk_name):
    g = m.groupdict()
    subj = g.get('p') or ('%s-%s' % (g['bus'], g['port']) if g.get('bus') else '') or g.get('dev') or ''
    if kind == 'offline' and not subj and g.get('scsi'):
        subj = scsi_dev(g['scsi']) or g['scsi']
    dev = usbn.get(subj, '')
    name = ' (%s)' % dev if dev else ''
    disk = lambda d: disk_name(d) or d
    if kind == 'usb_off':
        return subj, 'Від\'єднався USB-пристрій %s%s' % (subj, name)
    if kind == 'usb_on':
        sp = (g.get('speed') or '').lower()
        mode = 'USB 2.0' if sp.startswith('high') else 'USB 1.1' if sp.startswith(('full', 'low')) else 'USB 3' if 'super' in sp else sp
        return subj, 'Підключився USB-пристрій %s%s — %s' % (subj, name, mode)
    if kind == 'usb_reset':
        return subj, 'USB-пристрій %s%s скинуто (не відповідав)' % (subj, name)
    if kind == 'usb_err':
        return subj, 'USB-пристрій %s%s не відповідає (помилка зв\'язку)' % (subj, name)
    if kind == 'overcurrent':
        return subj, 'Перевантаження USB-порту %s — пристрою бракує живлення' % subj
    if kind == 'io_error':
        return subj, 'Помилка читання/запису на диску %s' % disk(subj)
    if kind == 'offline':
        return subj, 'Диск %s відключено системою (не відповідав)' % disk(subj)
    if kind == 'oom':
        return g.get('proc') or '', 'Забракло пам\'яті — система закрила процес %s' % g.get('proc')
    if kind == 'throttle_k':
        return 'cpu', 'Процесор перегрівся й скинув частоту'
    return subj, msg[:200]


# ───────────────────────── збирач ─────────────────────────

class Collector:
    """Щохвилинний обхід. g — модуль gazda (SMART, phys_disks, BOOST, стан)."""

    def __init__(self, store, g):
        self.s, self.g = store, g
        self.prev = {}
        self.kcursor = store.meta('kcursor')
        self.ecursor = store.meta('ecursor')
        self.state = store.meta('state', {}) or {}
        self.usbn = {}
        self.slow_at = 0
        self.disk_meta = store.meta('disks', {}) or {}
        self.started = time.time()

    # ── допоміжне ──
    def delta(self, key, val, now):
        old = self.prev.get(key)
        self.prev[key] = (val, now)
        if old is None or val is None or old[0] is None:
            return None, None
        return val - old[0], now - old[1]

    def keep(self, k, v):
        """Запам'ятати стан між перезапусками gazda (у meta, при скиданні буфера)."""
        self.state[k] = v

    def tick(self, now=None):
        now = int(now or time.time())
        slow = now - self.slow_at >= SLOW_EVERY
        if slow:
            self.slow_at = now
        for part in (self.cpu, self.sensors, self.power, self.memnet, self.disks, self.kernel, self.services,
                     self.boost, self.vidbox, self.backups):
            try:
                part(now, slow)
            except Exception as e:      # один датчик не має зупиняти решту
                k = 'err.' + part.__name__
                if self.state.get(k) != repr(e):
                    print('gazda ТО: %s — %r' % (part.__name__, e), flush=True)
                    self.state[k] = repr(e)
        self.state['last_tick'] = now
        if now - self.s.flushed >= FLUSH_EVERY:
            self.save()

    def save(self):
        self.s.set_meta('state', self.state)
        self.s.set_meta('kcursor', self.kcursor)
        self.s.set_meta('ecursor', self.ecursor)
        self.s.set_meta('disks', self.disk_meta)
        self.s.flush(force=True)

    def add(self, now, key, v, slow=True):
        if SLOW_RE.search(key) and not slow:
            return
        self.s.add(now, key, v)

    # ── розділи ──
    def boot_check(self, now):
        boot = int(now - float((fread('/proc/uptime', '0').split() or ['0'])[0]))
        last_boot, last_tick, stopped = self.state.get('boot'), self.state.get('last_tick'), self.state.get('stopped')
        if last_boot is None or abs(boot - last_boot) > 120:
            clean = bool(stopped and last_tick and stopped >= last_tick - 5)
            prev_end = prev_boot_end()          # останній запис журналу попереднього запуску — точніше за наш last_tick
            if prev_end and last_tick and prev_end > last_tick:
                last_tick = prev_end
            if last_tick:
                off = max(0, boot - last_tick)
                if clean:
                    self.s.event(boot, 'boot', 'server', 'vio', 'Сервер увімкнувся (був вимкнений %s)' % dur_text(off), off)
                else:
                    self.s.event(boot, 'crash', 'server', 'red', 'Сервер вимкнувся раптово (без завершення роботи) — не працював %s. '
                                 'Буває, коли зникло світло й села батарея, або ноутбук завис' % dur_text(off), off)
            else:
                self.s.event(boot, 'boot', 'server', 'vio', 'Почато збір даних ТО')
            self.state['boot'] = boot
        self.state.pop('stopped', None)

    def cpu(self, now, slow):
        ps = proc_stat()
        if ps:
            di, dt = self.delta('cpu.idle', ps[0], now)[0], self.delta('cpu.total', ps[1], now)[0]
            if di is not None and dt:
                self.add(now, 'cpu.load', round(100 * (1 - di / dt), 1))
        t = cpu_temp()
        self.add(now, 'cpu.temp', t)
        self.add(now, 'cpu.freq', cpu_freq())
        r = rapl_uj()
        if r:
            d, dt = self.delta('rapl', r[0], now)
            if d is not None and dt:
                self.add(now, 'cpu.w', round((d if d >= 0 else d + r[1]) / dt / 1e6, 2))
        th = throttle_total()
        if th is not None:
            self.add(now, 'cpu.throttle', th)
        lim = limits(self.g)
        # перегрів: середнє за хвилину ≥ межі — епізод (одна подія на початок і одна на кінець)
        hot = self.state.get('hot')
        if t is not None and t >= lim['cpu_temp'] and not hot:
            self.state['hot'] = [now, t]
        elif t is not None and hot:
            hot[1] = max(hot[1], t)
            if t < lim['cpu_temp'] - 5:
                if now - hot[0] >= 60 * 3:
                    self.s.event(hot[0], 'cpu_hot', 'cpu', 'yel', 'Процесор грівся до %d °C %s' % (hot[1], dur_text(now - hot[0])), now - hot[0], {'max': hot[1]})
                self.state.pop('hot', None)

    def sensors(self, now, slow):
        for k, v in hwmon_sensors().items():
            self.add(now, k, v)

    def power(self, now, slow):
        b = battery()
        if not b:
            return
        self.add(now, 'bat.pct', b['pct'])
        self.add(now, 'bat.ac', 1 if b['ac'] else 0)
        self.add(now, 'bat.w', b['w'])
        self.add(now, 'bat.health', b['health'], slow)
        self.add(now, 'bat.cycles', b['cycles'], slow)
        was = self.state.get('ac')
        if was is not None and was != b['ac']:
            if not b['ac']:
                self.state['ac_off'] = now
                self.s.event(now, 'ac_off', 'power', 'yel', 'Живлення від батареї — схоже, зникло світло (заряд %s%%)' % b['pct'])
            else:
                off = now - (self.state.pop('ac_off', None) or now)
                self.s.event(now, 'ac_on', 'power', 'acc', 'Живлення повернулось%s, заряд %s%%' % (' — не було %s' % dur_text(off) if off else '', b['pct']), off or None)
        self.state['ac'] = b['ac']

    def memnet(self, now, slow):
        mu, su, _ = mem()
        self.add(now, 'mem.used', mu)
        self.add(now, 'swap.used', su)
        rx, tx = net_bytes()
        for k, v in (('net.rx', rx), ('net.tx', tx)):
            d, dt = self.delta(k, v, now)
            if d is not None and dt and d >= 0:
                self.add(now, k, round(d / dt))
        self.add(now, 'wifi.signal', wifi_signal())
        ms = inet_ping()
        self.add(now, 'net.ping', ms)
        self.add(now, 'net.inet', 0 if ms is None else 1)
        fails = self.state.get('inet_fail', 0) + 1 if ms is None else 0
        self.state['inet_fail'] = fails
        if fails == 2 and not self.state.get('inet_down'):
            self.state['inet_down'] = now - 60
            self.s.event(now - 60, 'inet_down', 'net', 'yel', 'Зник інтернет')
        elif ms is not None and self.state.get('inet_down'):
            off = now - self.state.pop('inet_down')
            self.s.event(now, 'inet_up', 'net', 'acc', 'Інтернет повернувся — не було %s' % dur_text(off), off)
        ip = route_ip()
        if ip and self.state.get('ip') and ip != self.state['ip']:
            self.s.event(now, 'ip_change', 'net', 'dim', 'Адреса в мережі змінилась: %s → %s' % (self.state['ip'], ip))
        if ip:
            self.state['ip'] = ip

    def disk_name(self, kname):
        kname = (self.state.get('scsi') or {}).get(kname, kname)
        return (self.state.get('knames') or {}).get(re.sub(r'\d+$', '', kname) if kname.startswith('sd') else kname, '')

    def disks(self, now, slow):
        g = self.g
        disks = g.phys_disks()
        st = diskstats()
        knames = {}
        foreign = {}
        for d in disks:
            if d.get('loop'):
                continue
            did = re.sub(r'[^A-Za-z0-9]', '', d['serial'] or '')[-14:] or d['kname']
            names = [n for n in d['names']]
            knames[d['kname']] = ' · '.join(names)
            scsi = os.path.basename(os.path.realpath('/sys/block/%s/device' % d['kname']))
            if re.fullmatch(r'\d+:\d+:\d+:\d+', scsi):
                self.state.setdefault('scsi', {})[scsi] = d['kname']
            sm = g.SMART.get(d['dev']) or {}
            usb = usb_info(d['kname']) if d['usb'] else None
            meta = {'names': names, 'model': d['model'] or sm.get('model') or '', 'rot': d['rot'], 'usb': d['usb'], 'size': d['size'],
                    'system': d['system'], 'form': sm.get('form'), 'serial': d['serial'], 'kname': d['kname'], 'seen': now,
                    'bridge': {'port': usb[0], 'speed': usb[1], 'name': usb[2]} if usb else None}
            self.disk_meta[did] = dict(self.disk_meta.get(did) or {}, **meta)
            pre = 'disk.%s.' % did
            asleep = sm.get('state') == 'standby'
            if d['rot'] and not d['system']:
                self.add(now, pre + 'awake', 0 if asleep else 1)
            if not asleep and sm.get('at') and now - sm['at'] < 900:
                self.add(now, pre + 'temp', sm.get('temp'))
            for k in ('hours', 'cycles', 'load_cycles', 'crc', 'realloc', 'pending', 'uncorrect', 'media_errors', 'life', 'spare'):
                if sm.get(k) is not None:
                    changed = self.smart_changed(did, k, sm[k], names, now)
                    self.add(now, pre + k, sm[k], slow or changed)
            mp = '/' if d['system'] else os.path.join(g.DISKS, names[0]) if names else None
            if mp and (d['system'] or os.path.ismount(mp)) and slow:
                try:
                    v = os.statvfs(mp)
                    self.add(now, pre + 'used', round((1 - v.f_bavail / v.f_blocks) * 100, 1) if v.f_blocks else None)
                except OSError:
                    pass
            io = st.get(d['kname'])
            if io:
                d1 = self.delta('io.%s.r' % d['kname'], io[0], now)[0]
                d2 = self.delta('io.%s.w' % d['kname'], io[1], now)[0]
                d3, dt = self.delta('io.%s.t' % d['kname'], io[2], now)
                if d1 is not None and dt:
                    own = g.TOUCHED.pop(d['kname'], 0) if hasattr(g, 'TOUCHED') else 0
                    self.add(now, pre + 'io', round(max(0, d1 + d2) * 512 / dt))
                    self.add(now, pre + 'busy', round(min(100, max(0, d3) / (dt * 1000) * 100), 1))
                    other = max(0, d1 - own) + max(0, d2)
                    if other > 0 and d['rot'] and not d['system']:
                        foreign[d['kname']] = (did, other * 512, d2 > 0, names, d['dev'])
            # сон і пробудження
            if d['rot'] and not d['system']:
                was = self.state.setdefault('awake', {}).get(did)
                if was is not None and was != (not asleep):
                    if asleep:
                        self.s.event(now, 'disk_sleep', did, 'dim', 'Диск %s заснув' % ' · '.join(names))
                    else:
                        self.state.setdefault('wake_pending', {})[did] = now
                self.state['awake'][did] = not asleep
        self.state['knames'] = knames
        self.attribute(now, foreign)
        # диски з fstab, яких немає
        marked = [l.split()[1] for l in fread(g.FSTAB).splitlines() if l.endswith(g.FSTAB_MARK) and len(l.split()) > 1]
        gone = self.state.setdefault('gone', {})
        for mp in marked:
            n = os.path.basename(mp)
            if not os.path.ismount(mp):
                if n not in gone:
                    gone[n] = now
                elif gone[n] > 0 and now - gone[n] >= 120:
                    self.s.event(gone[n], 'disk_gone', n, 'red', 'Диск %s зник (не змонтований) — перевір живлення доку й кабель' % n)
                    gone[n] = -gone[n]               # подію вже записано
            elif n in gone:
                t0 = abs(gone.pop(n))
                if now - t0 >= 120:
                    self.s.event(now, 'disk_back', n, 'acc', 'Диск %s повернувся — не було %s' % (n, dur_text(now - t0)), now - t0)

    def smart_changed(self, did, k, v, names, now):
        """Погані лічильники записуємо одразу, а їхнє зростання — подія."""
        key = 'smart.%s.%s' % (did, k)
        old = self.state.get(key)
        self.state[key] = v
        if k in ('crc', 'realloc', 'pending', 'uncorrect', 'media_errors') and old is not None and v > old:
            word = {'crc': 'помилок передачі (кабель/USB)', 'realloc': 'перепризначених секторів', 'pending': 'нестабільних секторів',
                    'uncorrect': 'невиправних помилок', 'media_errors': 'помилок носія'}[k]
            self.s.event(now, 'smart', did, 'yel' if k == 'crc' else 'red', 'Диск %s: %s %s → %s' % (' · '.join(names), word, old, v), data={'k': k, 'from': old, 'to': v})
            return True
        return old is None or old != v and k not in ('hours',)

    def attribute(self, now, foreign):
        """Хто читав/писав на HDD за цю хвилину; хто розбудив диск."""
        cur = proc_io()
        prev = self.prev.get('procio', ({}, 0))[0]
        self.prev['procio'] = (cur, now)
        pend = self.state.setdefault('wake_pending', {})
        self.attribute_disks(now, foreign, cur, prev, pend)
        for did, t in list(pend.items()):          # прокинувся, а хто — не впіймали (читання було коротким)
            if now - t > 180:
                names = (self.disk_meta.get(did) or {}).get('names') or [did]
                self.s.event(t, 'disk_wake', did, 'dim', 'Диск %s прокинувся' % ' · '.join(names), data={'who': 'невідомо'})
                pend.pop(did)

    def attribute_disks(self, now, foreign, cur, prev, pend):
        if not foreign:
            return
        me = os.getpid()
        moved = {pid: b - prev.get(pid, 0) for pid, b in cur.items() if pid != me and b - prev.get(pid, 0) > 0}
        for kname, (did, nbytes, wrote, names, dev) in foreign.items():
            paths = [os.path.join(self.g.DISKS, n) for n in names if n != 'система']
            devs = ['/dev/' + kname]
            majmin = fread('/sys/block/%s/dev' % kname)
            hits = proc_hits(list(moved), paths, devs)
            whos = {}
            for pid in moved:
                comm = fread('/proc/%d/comm' % pid)
                if pid in hits or kname in comm or (majmin and 'flush-' + majmin in comm):
                    lab = proc_label(pid)
                    whos[lab] = whos.get(lab, 0) + moved[pid]
            if not whos:
                whos = {'система (скидання кешу на диск)' if wrote else 'невідомо': nbytes}
            for who, b in sorted(whos.items(), key=lambda x: -x[1])[:4]:
                self.s.touched(now, did, who[:60], b)
            if did in pend:
                top = max(whos.items(), key=lambda x: x[1])[0]
                self.s.event(pend.pop(did), 'disk_wake', did, 'dim', 'Диск %s прокинувся — %s' % (' · '.join(names), top), data={'who': top})

    def kernel(self, now, slow):
        self.usbn.update({k: v for k, v in usb_names().items() if v})
        cmd = ['journalctl', '-k', '-o', 'json', '--no-pager']
        if self.kcursor:
            cmd += ['--after-cursor', self.kcursor]
        else:
            cmd += ['-n', '1']
        try:
            out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return
        first = not self.kcursor
        last = {}
        for raw in out.splitlines()[-5000:]:
            try:
                j = json.loads(raw)
            except ValueError:
                continue
            self.kcursor = j.get('__CURSOR') or self.kcursor
            if first:
                continue
            msg = j.get('MESSAGE')
            if isinstance(msg, list):
                msg = bytes(msg).decode('utf-8', 'replace')
            msg = str(msg or '')
            ts = int(j.get('__REALTIME_TIMESTAMP', now * 1e6)) // 1000000
            for rx, kind, lvl in KERNEL_RULES:
                m = rx.search(msg)
                if not m:
                    continue
                subj, text = kernel_text(kind, m, msg, self.usbn, self.disk_name)
                k = (kind, subj)
                if k in last and ts - last[k] < 15:       # один збій — десяток рядків; пишемо одну подію
                    break
                last[k] = ts
                if kind == 'usb_on' and 'USB 2.0' in text and self.usbn.get(subj, '') and re.search(r'(?i)sata|disk|storage|bridge|realtek|jmicron|asmedia|maiwo|9201', self.usbn.get(subj, '')):
                    text += ' (для диска повільно — переткни в синій порт USB 3 або заміни кабель)'
                    lvl = 'yel'
                self.s.event(ts, kind, subj, lvl, text, data={'msg': msg[:300]})
                break

    def services(self, now, slow):
        names = ['vidbox', 'hata', 'hata-screen', 'smbd', 'tailscaled']
        try:
            out = subprocess.run(['systemctl', 'show', '-p', 'Id,ActiveState,NRestarts,ExecMainStartTimestampMonotonic,LoadState'] +
                                 [n + '.service' for n in names], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return
        svc = self.state.setdefault('svc', {})
        for block in out.split('\n\n'):
            kv = dict(l.split('=', 1) for l in block.splitlines() if '=' in l)
            n = kv.get('Id', '').replace('.service', '')
            if not n or kv.get('LoadState') != 'loaded':
                continue
            if n in ('smbd', 'tailscaled') and kv.get('ActiveState') == 'inactive' and n not in svc:
                continue        # не ввімкнено — не стежимо
            up = kv.get('ActiveState') == 'active'
            self.add(now, 'svc.%s' % n, 1 if up else 0, slow)
            old = svc.get(n) or {}
            start, nr = kv.get('ExecMainStartTimestampMonotonic', '0'), int(kv.get('NRestarts', '0') or 0)
            if old:
                if nr > old.get('nr', nr):
                    self.s.event(now, 'svc_crash', n, 'red', 'Служба %s упала й перезапустилась сама' % n)
                elif up and start != old.get('start') and old.get('up'):
                    self.s.event(now, 'svc_restart', n, 'dim', 'Службу %s перезапущено' % n)
                if old.get('up') and not up and kv.get('ActiveState') in ('failed', 'inactive'):
                    self.s.event(now, 'svc_down', n, 'red' if kv.get('ActiveState') == 'failed' else 'yel',
                                 'Служба %s %s' % (n, 'не працює (помилка)' if kv.get('ActiveState') == 'failed' else 'зупинена'))
            svc[n] = {'start': start, 'nr': nr, 'up': up}
        # помилки в журналах служб Хати — лічильник за хвилину
        cmd = ['journalctl', '-p', 'err', '-o', 'json', '--no-pager'] + [x for u in ('hata', 'vidbox', 'gazda', 'hata-screen') for x in ('-u', u)]
        cmd += ['--after-cursor', self.ecursor] if self.ecursor else ['-n', '1']
        try:
            lines = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=20).stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            return
        n = 0
        for raw in lines:
            try:
                self.ecursor = json.loads(raw).get('__CURSOR') or self.ecursor
                n += 1
            except ValueError:
                pass
        self.add(now, 'log.err', n if self.state.get('ecur_ok') else 0)
        self.state['ecur_ok'] = True

    def boost(self, now, slow):
        on = bool((getattr(self.g, 'BOOST', {}) or {}).get('on'))
        self.add(now, 'boost', 1 if on else 0)
        b = self.state.get('boost')
        if on and not b:
            self.state['boost'] = [now, 0]
            self.s.event(now, 'boost_on', 'boost', 'dim', 'Режим продуктивності (субтитри ШІ): кулери на 100 %')
        elif on and b:
            b[1] = max(b[1], cpu_temp() or 0)
        elif not on and b:
            self.s.event(now, 'boost_off', 'boost', 'dim', 'Режим продуктивності вимкнено — тривав %s, процесор до %d °C' % (dur_text(now - b[0]), b[1]), now - b[0], {'max': b[1]})
            self.state.pop('boost', None)

    def vidbox(self, now, slow):
        p = os.path.join(os.path.dirname(self.s.path), 'vidbox', 'aisubs', 'queue.json')
        try:
            with open(p, encoding='utf-8') as f:
                q = json.load(f)
        except (OSError, ValueError):
            return
        seen = self.state.setdefault('vb', {})
        active = 0
        for it in q if isinstance(q, list) else []:
            vid, stt = str(it.get('id')), it.get('state')
            if stt not in ('done', 'error') and stt:
                active += 1
            old = seen.get(vid)
            if stt in ('audio', 'model', 'recog', 'translate', 'context') and (not old or old[0] in ('queued', 'done', 'error')):
                seen[vid] = [stt, now]
            elif stt in ('done', 'error') and old and old[0] not in ('done', 'error'):
                took = now - old[1] if old[0] != 'queued' else None
                if stt == 'done':
                    self.s.event(now, 'vb_done', vid, 'dim', 'Субтитри ШІ готові%s' % (' за %s' % dur_text(took) if took else ''), took)
                    if took:
                        self.add(now, 'vb.min', round(took / 60, 1))
                else:
                    self.s.event(now, 'vb_error', vid, 'yel', 'Субтитри ШІ: помилка — %s' % str(it.get('err') or '')[:160])
                seen[vid] = [stt, now]
            elif not old:
                seen[vid] = [stt or 'queued', now]
        ids = {str(it.get('id')) for it in q if isinstance(it, dict)}
        for k in [k for k in seen if k not in ids]:
            seen.pop(k)
        self.add(now, 'vb.queue', active)

    def backups(self, now, slow):
        try:
            with open('/var/lib/hata/hata.json', encoding='utf-8') as f:
                last = (json.load(f).get('backup') or {}).get('last') or {}
        except (OSError, ValueError):
            return
        at = last.get('at')
        if at and at != self.state.get('backup_at'):
            if self.state.get('backup_at') is not None:
                if last.get('error'):
                    self.s.event(at, 'backup_fail', 'backup', 'red', 'Копія не вдалася: %s' % str(last['error'])[:200])
                else:
                    self.s.event(at, 'backup_ok', 'backup', 'acc' if last.get('ok') else 'yel', 'Копія %s: %s файлів%s' % (
                        last.get('name') or '', '{:,}'.format(last.get('files') or 0).replace(',', ' '),
                        '' if last.get('ok') else ', помилок %s' % last.get('errors')), last.get('took'))
            self.state['backup_at'] = at


STORE = None
COLLECTOR = None


def start(g, path=DB_PATH):
    """Запуск із gazda: база, подія про увімкнення, щохвилинний потік."""
    global STORE, COLLECTOR
    STORE = Store(path)
    COLLECTOR = Collector(STORE, g)
    COLLECTOR.boot_check(time.time())

    def loop():
        while True:
            try:
                COLLECTOR.tick()
            except Exception as e:
                print('gazda ТО:', repr(e), flush=True)
            time.sleep(60 - time.time() % 60 + 1)
    threading.Thread(target=loop, daemon=True).start()
    return STORE


def stop():
    """gazda завершується (вимкнення, перезавантаження, оновлення): дописуємо буфер і позначку «вимкнено як слід»."""
    if COLLECTOR:
        COLLECTOR.state['stopped'] = int(time.time())
        COLLECTOR.state['last_tick'] = int(time.time())
        COLLECTOR.save()


def limits(g):
    st = g.load_state() if hasattr(g, 'load_state') else {}
    return dict(DEFAULT_LIMITS, **{k: v for k, v in (st.get('health_limits') or {}).items() if k in DEFAULT_LIMITS})


# ───────────────────────── запити панелі ─────────────────────────

RANGES = {'6h': (6 * 3600, 60), '24h': (86400, 300), '7d': (7 * 86400, 3600), '30d': (30 * 86400, 3 * 3600),
          '90d': (90 * 86400, 86400), '1y': (365 * 86400, 86400)}


def is_counter(k):
    return bool(COUNTER_RE.search(k))


def series(store, keys, rng, now=None):
    now = int(now or time.time())
    span, step = RANGES.get(rng, RANGES['24h'])
    a = now - span
    out = {}
    for k in keys[:24]:
        rows = store.rows(k, a - (step if is_counter(k) else 0), now + 1)
        buckets = {}
        for t, avg, lo, hi, last in rows:
            b = (t // step) * step if step < 86400 else local_day(t)
            x = buckets.setdefault(b, [0.0, 0, lo, hi, last])
            x[0] += avg; x[1] += 1; x[2] = min(x[2], lo); x[3] = max(x[3], hi); x[4] = last
        pts = []
        prev = None
        for b in sorted(buckets):
            x = buckets[b]
            if is_counter(k):
                if prev is not None and b >= a:
                    pts.append([b, max(0, round(x[4] - prev, 3))])
                prev = x[4]
            elif b >= a:
                pts.append([b, round(x[0] / x[1], 2), x[2], x[3]])
        out[k] = {'counter': is_counter(k), 'points': pts}
    return {'range': rng, 'from': a, 'to': now, 'step': step, 'series': out}


def events(store, rng='7d', kinds=None, limit=400, now=None):
    now = int(now or time.time())
    span = RANGES.get(rng, (int(rng) if str(rng).isdigit() else 7 * 86400, 0))[0]
    sql = 'SELECT * FROM events WHERE ts>=?'
    args = [now - span]
    if kinds:
        sql += ' AND kind IN (%s)' % ','.join('?' * len(kinds))
        args += list(kinds)
    rows = store.q(sql + ' ORDER BY ts DESC LIMIT ?', args + [int(limit)])
    return [{'ts': r['ts'], 'kind': r['kind'], 'subj': r['subj'], 'lvl': r['lvl'], 'text': r['text'], 'dur': r['dur'],
             'data': json.loads(r['data']) if r['data'] else None} for r in rows]


def disk_table(store, span, now=None):
    now = int(now or time.time())
    a = now - span
    dm = store.meta('disks', {}) or {}
    out = []
    for did, m in sorted(dm.items(), key=lambda x: (not x[1].get('system'), x[1].get('names') or [])):
        if now - (m.get('seen') or 0) > max(span, 86400 * 30):
            continue
        pre = 'disk.%s.' % did
        row = {'id': did, 'names': m.get('names') or [did], 'model': m.get('model'), 'rot': m.get('rot'), 'usb': m.get('usb'),
               'system': m.get('system'), 'bridge': m.get('bridge'), 'form': m.get('form'), 'size': m.get('size'), 'seen': m.get('seen'), 'c': {}}
        for k in ('hours', 'cycles', 'load_cycles', 'crc', 'realloc', 'pending', 'uncorrect', 'media_errors', 'life'):
            s0 = store.value_at(pre + k, a)
            if s0 is None:
                s0 = store.value_at(pre + k, a, after=True)
            s1 = store.value_at(pre + k, now)
            if s1 is not None:
                row['c'][k] = {'from': s0, 'to': s1, 'd': round(s1 - s0, 1) if s0 is not None else None}
        aw = store.q('SELECT AVG(v) AS a, COUNT(*) AS n FROM samples WHERE key=? AND ts>=?', (pre + 'awake', a)) if span <= RAW_DAYS * 86400 else \
            store.q('SELECT SUM(avg*n)/SUM(n) AS a, SUM(n) AS n FROM hourly WHERE key=? AND ts>=?', (pre + 'awake', a))
        row['awake'] = round(aw[0]['a'] * 100, 1) if aw and aw[0]['a'] is not None else None
        tq = store.q('SELECT AVG(avg) AS a, MAX(max) AS m FROM hourly WHERE key=? AND ts>=?', (pre + 'temp', a)) if span > 86400 else \
            store.q('SELECT AVG(v) AS a, MAX(v) AS m FROM samples WHERE key=? AND ts>=?', (pre + 'temp', a))
        if not tq or tq[0]['a'] is None:
            tq = store.q('SELECT AVG(v) AS a, MAX(v) AS m FROM samples WHERE key=? AND ts>=?', (pre + 'temp', a))
        row['temp'] = {'avg': round(tq[0]['a'], 1) if tq and tq[0]['a'] is not None else None, 'max': tq[0]['m'] if tq else None}
        row['wakes'] = store.q("SELECT COUNT(*) AS n FROM events WHERE kind='disk_wake' AND subj=? AND ts>=?", (did, a))[0]['n']
        row['sleeps'] = store.q("SELECT COUNT(*) AS n FROM events WHERE kind='disk_sleep' AND subj=? AND ts>=?", (did, a))[0]['n']
        row['who'] = [{'who': r['who'], 'min': r['n'], 'bytes': r['b']} for r in store.q(
            'SELECT who, COUNT(*) AS n, SUM(bytes) AS b FROM touch WHERE disk=? AND ts>=? GROUP BY who ORDER BY n DESC LIMIT 8', (did, a))]
        row['wokeBy'] = [{'who': r['w'], 'n': r['n']} for r in store.q(
            "SELECT json_extract(data, '$.who') AS w, COUNT(*) AS n FROM events WHERE kind='disk_wake' AND subj=? AND ts>=? GROUP BY w ORDER BY n DESC LIMIT 6", (did, a))]
        row['usbEvents'] = 0
        br = row['bridge'] or {}
        if br.get('port'):
            row['usbEvents'] = store.q("SELECT COUNT(*) AS n FROM events WHERE kind IN ('usb_off','usb_err','usb_reset') AND subj=? AND ts>=?", (br['port'], a))[0]['n']
        row['ioErrors'] = store.q("SELECT COUNT(*) AS n FROM events WHERE kind IN ('io_error','offline') AND ts>=? AND text LIKE ?", (a, '%' + (row['names'][0]) + '%'))[0]['n']
        row['verdict'] = disk_verdict(row, span)
        out.append(row)
    return out


def park_limit(row):
    return 600000 if re.match(r'2\.5', row.get('form') or '') or (not row.get('form') and row.get('usb') and (row.get('size') or 0) < 2.2e12) else 300000


def disk_verdict(row, span):
    c = row['c']
    d = lambda k: (c.get(k) or {}).get('d') or 0
    v = lambda k: (c.get(k) or {}).get('to') or 0
    if d('pending') > 0 or d('uncorrect') > 0 or d('media_errors') > 0 or v('pending') > 0:
        return ['red', 'замінити']
    if d('realloc') > 0:
        return ['red', 'замінити найближчим часом']
    if row['rot'] and v('load_cycles') >= park_limit(row):
        return ['yel', 'стежити: ресурс паркувань вичерпано']
    if d('crc') > 0 or row.get('ioErrors') or row.get('usbEvents'):
        return ['yel', 'стежити: збої зв\'язку']
    if (row['temp'] or {}).get('max') and row['temp']['max'] >= 55:
        return ['yel', 'стежити: гарячий']
    return ['acc', 'норма']


def system_table(store, span, now=None):
    now = int(now or time.time())
    a = now - span

    def agg(k):
        rows = store.rows(k, a, now + 1)
        if not rows:
            return None
        return {'avg': round(sum(r[1] for r in rows) / len(rows), 1), 'min': min(r[2] for r in rows), 'max': max(r[3] for r in rows)}

    def cnt(*kinds):
        return store.q('SELECT COUNT(*) AS n, SUM(dur) AS d FROM events WHERE kind IN (%s) AND ts>=?' % ','.join('?' * len(kinds)), kinds + (a,))[0]

    def diff(k):
        s0, s1 = store.value_at(k, a) or store.value_at(k, a, after=True), store.value_at(k, now)
        return {'from': s0, 'to': s1, 'd': round(s1 - s0, 1) if s0 is not None and s1 is not None else None}
    hot_min = None
    if span <= RAW_DAYS * 86400:
        hot_min = store.q('SELECT COUNT(*) AS n FROM samples WHERE key=? AND ts>=? AND v>=?', ('cpu.temp', a, limits_static(store)['cpu_temp']))[0]['n']
    fans = {k: agg(k) for k in store.keys(a) if k.startswith('fan.')}
    out = {'cpu.temp': agg('cpu.temp'), 'cpu.load': agg('cpu.load'), 'cpu.w': agg('cpu.w'), 'cpu.freq': agg('cpu.freq'), 'mem.used': agg('mem.used'),
           'swap.used': agg('swap.used'), 'net.ping': agg('net.ping'), 'wifi.signal': agg('wifi.signal'), 'hotMin': hot_min,
           'throttle': diff('cpu.throttle'), 'bat.health': diff('bat.health'), 'bat.cycles': diff('bat.cycles'), 'fans': fans,
           'outages': dict(cnt('ac_on')), 'inet': dict(cnt('inet_up')), 'boots': dict(cnt('boot')), 'crashes': dict(cnt('crash')),
           'usb': dict(cnt('usb_off', 'usb_err', 'usb_reset')), 'ioerr': dict(cnt('io_error', 'offline')), 'svcCrash': dict(cnt('svc_crash', 'svc_down')),
           'boost': dict(cnt('boost_off')), 'backupOk': dict(cnt('backup_ok')), 'backupFail': dict(cnt('backup_fail')),
           'vbDone': dict(cnt('vb_done')), 'vbErr': dict(cnt('vb_error')), 'vbMin': agg('vb.min'), 'logErr': None,
           'online': None}
    le = store.rows('log.err', a, now + 1)
    out['logErr'] = round(sum(r[1] * (1 if span <= RAW_DAYS * 86400 else 60) for r in le)) if le else 0
    up = store.rows('cpu.load', a, now + 1)
    if up:
        if span <= RAW_DAYS * 86400:
            out['online'] = min(100, round(len(up) * 60 / span * 100, 1))
        else:
            n = store.q('SELECT SUM(n) AS n FROM hourly WHERE key=? AND ts>=?', ('cpu.load', a))[0]['n'] or 0
            out['online'] = min(100, round(n * 60 / span * 100, 1))
    return out


def limits_static(store):
    return dict(DEFAULT_LIMITS, **(store.meta('limits', {}) or {}))


def summary(store, lim, now=None):
    """Зведення звичайними словами: що погіршується або потребує уваги."""
    now = int(now or time.time())
    store.set_meta('limits', lim)
    items = []

    def add(lvl, text, area='', key=''):
        items.append({'lvl': lvl, 'text': text, 'area': area, 'key': key})

    disks = disk_table(store, 30 * 86400, now)
    week = {r['id']: r for r in disk_table(store, 7 * 86400, now)}
    day = {r['id']: r for r in disk_table(store, 86400, now)}
    for r in disks:
        n = ' · '.join(r['names'])
        c, w, dd = r['c'], week.get(r['id'], {}).get('c', {}), day.get(r['id'], {}).get('c', {})
        g = lambda src, k: (src.get(k) or {}).get('d') or 0
        if g(c, 'pending') or g(c, 'uncorrect') or g(c, 'media_errors'):
            add('red', '%s: з\'явились нестабільні чи невиправні сектори (за місяць +%d). Скопіюй важливе й готуй заміну.' % (n, g(c, 'pending') + g(c, 'uncorrect') + g(c, 'media_errors')), 'disk', r['id'])
        if g(c, 'realloc'):
            add('red', '%s: перепризначених секторів +%d за місяць — диск зношується.' % (n, g(c, 'realloc')), 'disk', r['id'])
        if g(w, 'crc'):
            add('yel', '%s: помилки передачі +%d за тиждень — винен кабель, USB-міст чи живлення доку.' % (n, g(w, 'crc')), 'disk', r['id'])
        if r['rot']:
            pd = g(dd, 'load_cycles')
            if pd >= lim['parks_day']:
                add('yel', '%s: головки паркуються %d разів за добу (межа %d).' % (n, pd, lim['parks_day']), 'disk', r['id'])
            lc = (c.get('load_cycles') or {}).get('to')
            if lc and lc >= park_limit(r):
                add('dim', '%s: ресурс паркувань від виробника вичерпано (%s з %d тис.) — працює, але копії тримай свіжими.' % (n, '{:,}'.format(int(lc)).replace(',', ' '), park_limit(r) // 1000), 'disk', r['id'])
            wd = day.get(r['id'], {}).get('wakes', 0)
            if wd >= lim['wakes_day']:
                top = (day[r['id']].get('wokeBy') or [{}])[0].get('who') or 'невідомо'
                add('yel', '%s: прокидався %d разів за добу — найчастіше будить «%s». Часті розкрутки зношують диск.' % (n, wd, top), 'disk', r['id'])
        tmax = (day.get(r['id'], {}).get('temp') or {}).get('max')
        if tmax and tmax >= lim['disk_temp']:
            add('red' if tmax >= lim['disk_temp'] + 5 else 'yel', '%s: нагрівався до %d °C за добу (межа %d °C).' % (n, tmax, lim['disk_temp']), 'disk', r['id'])
        t30 = r.get('temp') or {}
        t7 = (week.get(r['id'], {}).get('temp') or {})
        if t30.get('avg') and t7.get('avg') and t7['avg'] - t30['avg'] >= 5:
            add('yel', '%s: середня температура за тиждень на %d° вища, ніж за місяць.' % (n, round(t7['avg'] - t30['avg'])), 'disk', r['id'])
        uw = week.get(r['id'], {}).get('usbEvents') or 0
        if uw:
            add('red' if uw >= 3 else 'yel', '%s: %d %s USB за тиждень (міст %s).' % (n, uw, 'збої' if 1 < uw < 5 else 'збій' if uw == 1 else 'збоїв',
                                                                         ((r.get('bridge') or {}).get('name') or '?')), 'disk', r['id'])
        br = r.get('bridge') or {}
        if br.get('speed') and br['speed'] < 5000 and r['rot']:
            add('yel', '%s: підключений як USB 2.0 (%d Мбіт/с) — переткни в порт USB 3 або заміни кабель.' % (n, br['speed']), 'disk', r['id'])
    for e in events(store, '7d', ('disk_gone',), 20, now):
        back = store.q("SELECT 1 FROM events WHERE kind='disk_back' AND subj=? AND ts>=?", (e['subj'], e['ts']))
        if not back:
            add('red', 'Диск %s зник %s і досі не повернувся.' % (e['subj'], time.strftime('%d.%m %H:%M', time.localtime(e['ts']))), 'disk')
    io7 = store.q("SELECT COUNT(*) AS n FROM events WHERE kind IN ('io_error','offline') AND ts>=?", (now - 7 * 86400,))[0]['n']
    if io7:
        add('red', 'Помилки читання/запису на дисках: %d за тиждень (див. події).' % io7, 'disk')
    # процесор і охолодження
    hot = store.q('SELECT COUNT(*) AS n, MAX(v) AS m FROM samples WHERE key=? AND ts>=? AND v>=?', ('cpu.temp', now - 86400, lim['cpu_temp']))[0]
    if hot['n'] >= lim['cpu_hot_min']:
        add('yel', 'Процесор був гарячим (≥ %d °C) %d хв за добу, до %d °C.' % (lim['cpu_temp'], hot['n'], hot['m']), 'cpu')
    th = store.value_at('cpu.throttle', now), store.value_at('cpu.throttle', now - 86400) or store.value_at('cpu.throttle', now - 86400, after=True)
    if th[0] is not None and th[1] is not None and th[0] - th[1] > 100:
        add('yel', 'Процесор скидав частоту від перегріву: %d разів за добу.' % (th[0] - th[1]), 'cpu')
    for f in [k for k in store.keys(now - 86400) if k.startswith('fan.')]:
        rows = store.rows(f, now - 3600, now + 1)
        t = store.rows('cpu.temp', now - 3600, now + 1)
        if rows and t and max(r[3] for r in rows) == 0 and sum(r[1] for r in t) / len(t) >= 70:
            add('red', 'Кулер (%s) стоїть, хоча процесор гарячий — перевір вентилятор.' % f[4:], 'cpu')
    # батарея
    h1, h0 = store.value_at('bat.health', now), store.value_at('bat.health', now - 30 * 86400) or store.value_at('bat.health', now - 30 * 86400, after=True)
    if h1 is not None and h0 is not None and h0 - h1 >= lim['bat_drop']:
        add('yel', 'Батарея втратила %.1f%% ємності за місяць (зараз %.0f%% від заводської).' % (h0 - h1, h1), 'bat')
    elif h1 is not None and h1 < 60:
        add('dim', 'Батарея тримає %.0f%% від заводської ємності — під час відключень сервер протримається менше.' % h1, 'bat')
    for e in events(store, '24h', ('ac_off',), 1, now):
        if not store.q("SELECT 1 FROM events WHERE kind='ac_on' AND ts>=?", (e['ts'],)):
            add('yel', 'Зараз живлення від батареї (світла немає з %s).' % time.strftime('%H:%M', time.localtime(e['ts'])), 'bat')
    # служби, сервер, копії
    cr = store.q("SELECT COUNT(*) AS n FROM events WHERE kind='crash' AND ts>=?", (now - 30 * 86400,))[0]['n']
    if cr:
        add('yel', 'Сервер вимикався раптово %d %s за місяць.' % (cr, 'рази' if 1 < cr < 5 else 'раз' if cr == 1 else 'разів'), 'sys')
    sc = store.q("SELECT subj, COUNT(*) AS n FROM events WHERE kind IN ('svc_crash','svc_down') AND ts>=? GROUP BY subj", (now - 7 * 86400,))
    for r in sc:
        add('yel', 'Служба %s падала %d %s за тиждень.' % (r['subj'], r['n'], 'рази' if 1 < r['n'] < 5 else 'раз' if r['n'] == 1 else 'разів'), 'sys')
    oom = store.q("SELECT COUNT(*) AS n FROM events WHERE kind='oom' AND ts>=?", (now - 7 * 86400,))[0]['n']
    if oom:
        add('red', 'Забракло оперативної пам\'яті %d р. за тиждень — система закривала процеси.' % oom, 'sys')
    try:
        with open('/var/lib/hata/hata.json', encoding='utf-8') as f:
            bk = json.load(f).get('backup') or {}
    except (OSError, ValueError):
        bk = store.meta('demo_backup') or {}
    if bk.get('target'):
        last = bk.get('last') or {}
        if last.get('error'):
            add('red', 'Остання копія не вдалася: %s' % str(last['error'])[:160], 'backup')
        elif not last.get('at') or now - last['at'] > lim['backup_days'] * 86400:
            add('yel', 'Копій не було понад %d дн.' % lim['backup_days'], 'backup')
    order = {'red': 0, 'yel': 1, 'dim': 2}
    items.sort(key=lambda x: order.get(x['lvl'], 3))
    level = 'red' if any(i['lvl'] == 'red' for i in items) else 'yel' if any(i['lvl'] == 'yel' for i in items) else 'acc'
    first = store.q('SELECT MIN(ts) AS t FROM samples')[0]['t']
    fh = store.q('SELECT MIN(ts) AS t FROM hourly')[0]['t']
    since = min(x for x in (first, fh, now) if x)
    return {'level': level, 'items': items, 'since': since, 'now': now, 'limits': lim}


def export_csv(store, rng, now=None):
    now = int(now or time.time())
    span = RANGES.get(rng, RANGES['30d'])[0]
    a = now - span
    keys = store.keys(a)
    lines = ['час,показник,середнє,мінімум,максимум']
    for k in keys:
        for t, avg, lo, hi, _ in store.rows(k, a, now + 1):
            lines.append('%s,%s,%s,%s,%s' % (time.strftime('%Y-%m-%d %H:%M', time.localtime(t)), k, avg, lo, hi))
    lines.append('')
    lines.append('час,подія,об\'єкт,рівень,опис,тривалість_с')
    for e in reversed(events(store, rng, None, 100000, now)):
        lines.append('%s,%s,%s,%s,"%s",%s' % (time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e['ts'])), e['kind'], e['subj'], e['lvl'],
                                             e['text'].replace('"', "'"), e['dur'] if e['dur'] is not None else ''))
    return '\n'.join(lines) + '\n'


def handle(store, a, g=None, now=None):
    """Дія gazda «health»: op = summary | series | events | table | limits | export."""
    op = a.get('op') or 'summary'
    with LOCK:
        store.flush()
    lim = limits(g) if g else limits_static(store)
    rng = a.get('range') if a.get('range') in RANGES else '24h'
    if op == 'summary':
        return summary(store, lim, now)
    if op == 'series':
        keys = [str(k) for k in (a.get('keys') or []) if re.fullmatch(r'[\w.:-]{1,80}', str(k))]
        return series(store, keys, rng, now)
    if op == 'keys':
        span = RANGES.get(rng)[0]
        return {'keys': store.keys(int(now or time.time()) - span), 'disks': store.meta('disks', {}) or {}}
    if op == 'events':
        kinds = [str(k) for k in a.get('kinds') or [] if re.fullmatch(r'[a-z_]{2,20}', str(k))] or None
        return {'events': events(store, rng, kinds, min(int(a.get('limit') or 400), 2000), now)}
    if op == 'table':
        span = RANGES[rng][0]
        return {'range': rng, 'disks': disk_table(store, span, now), 'system': system_table(store, span, now),
                'disks_meta': store.meta('disks', {}) or {}}
    if op == 'export':
        if a.get('fmt') == 'json':
            span = RANGES[rng][0]
            return {'text': json.dumps({'summary': summary(store, lim, now), 'disks': disk_table(store, span, now),
                                        'system': system_table(store, span, now), 'events': events(store, rng, None, 100000, now)},
                                       ensure_ascii=False, indent=1), 'name': 'hata-to-%s.json' % rng}
        return {'text': export_csv(store, rng, now), 'name': 'hata-to-%s.csv' % rng}
    if op == 'limits':
        return {'limits': lim, 'defaults': DEFAULT_LIMITS, 'range': LIMIT_RANGE}
    raise ValueError('Невідома дія ТО')


def clean_limits(d):
    out = {}
    for k, (lo, hi) in LIMIT_RANGE.items():
        if k in (d or {}):
            try:
                v = float(d[k])
            except (TypeError, ValueError):
                continue
            out[k] = max(lo, min(hi, int(round(v))))
    return out


# ───────────────────────── демо-дані (перевірка інтерфейсу без сервера) ─────────────────────────

def demo_fill(path, days=35):
    """Правдоподібні 35 днів: добовий ритм, сон дисків, відключення світла, пара збоїв USB."""
    import math
    import random
    rnd = random.Random(7)
    if os.path.exists(path):
        os.remove(path)
    for x in ('-wal', '-shm'):
        if os.path.exists(path + x):
            os.remove(path + x)
    s = Store(path)
    now = int(time.time())
    t0 = now - days * 86400
    t0 -= t0 % 60
    disks = {'WDWX1': {'names': ['disk'], 'model': 'WDC WD10SPZX-22Z10T1', 'rot': True, 'usb': True, 'size': 1e12, 'system': False, 'form': '2.5 inches',
                       'serial': 'WD-WX1', 'kname': 'sda', 'seen': now, 'bridge': {'port': '2-1', 'speed': 5000, 'name': 'MAIWO K3016'}},
             'TOS1': {'names': ['1'], 'model': 'TOSHIBA MQ04ABF100', 'rot': True, 'usb': True, 'size': 1e12, 'system': False, 'form': '2.5 inches',
                      'serial': 'TOS1', 'kname': 'sdb', 'seen': now, 'bridge': {'port': '2-1', 'speed': 5000, 'name': 'MAIWO K3016'}},
             'S6X1': {'names': ['система'], 'model': 'SAMSUNG MZVLQ512HALU', 'rot': False, 'usb': False, 'size': 512e9, 'system': True, 'kname': 'nvme0n1',
                      'serial': 'S6X1', 'seen': now, 'bridge': None}}
    s.set_meta('disks', disks)
    cnt = {'WDWX1': {'hours': 14500, 'cycles': 6240, 'load_cycles': 598900, 'crc': 2, 'realloc': 0, 'pending': 0, 'uncorrect': 0},
           'TOS1': {'hours': 6600, 'cycles': 3560, 'load_cycles': 227500, 'crc': 0, 'realloc': 0, 'pending': 0, 'uncorrect': 0},
           'S6X1': {'hours': 9400, 'cycles': 2050, 'life': 93, 'media_errors': 0}}
    awake = {'WDWX1': True, 'TOS1': False}
    bat_h, bat_c, thr = 88.0, 140, 1200
    outages = [(now - d * 86400 - h * 3600, dur) for d, h, dur in ((2, 14, 4 * 3600), (9, 9, 3 * 3600), (16, 19, 2 * 3600), (23, 8, 4 * 3600), (30, 17, 3600))]
    rows, evs, touch = [], [], []
    ev = lambda ts, kind, subj, lvl, text, dur=None, data=None: evs.append((ts, kind, subj, lvl, text, dur, json.dumps(data, ensure_ascii=False) if data else None))
    ev(t0, 'boot', 'server', 'vio', 'Почато збір даних ТО')
    for a, d in outages:
        ev(a, 'ac_off', 'power', 'yel', 'Живлення від батареї — схоже, зникло світло (заряд 60%)')
        ev(a + d, 'ac_on', 'power', 'acc', 'Живлення повернулось — не було %s, заряд %d%%' % (dur_text(d), 60 - d // 400), d)
        ev(a + 120, 'inet_down', 'net', 'yel', 'Зник інтернет')
        ev(a + d + 300, 'inet_up', 'net', 'acc', 'Інтернет повернувся — не було %s' % dur_text(d + 180), d + 180)
    ev(now - 3 * 86400 + 7200, 'usb_reset', '2-1', 'yel', 'USB-пристрій 2-1 (MAIWO K3016) скинуто (не відповідав)')
    ev(now - 3 * 86400 + 7230, 'usb_err', '2-1', 'red', 'USB-пристрій 2-1 (MAIWO K3016) не відповідає (помилка зв\'язку)')
    ev(now - 20 * 86400, 'crash', 'server', 'red', 'Сервер вимкнувся раптово (без завершення роботи) — не працював 41 хв.', 2460)
    ev(now - 6 * 86400, 'svc_restart', 'vidbox', 'dim', 'Службу vidbox перезапущено')
    ev(now - 86400 * 1 - 5000, 'smart', 'WDWX1', 'yel', 'Диск disk: помилок передачі (кабель/USB) 2 → 3', data={'k': 'crc', 'from': 2, 'to': 3})
    ev(now - 5 * 3600, 'boost_on', 'boost', 'dim', 'Режим продуктивності (субтитри ШІ): кулери на 100 %')
    ev(now - 3 * 3600, 'boost_off', 'boost', 'dim', 'Режим продуктивності вимкнено — тривав 2 год 0 хв, процесор до 78 °C', 7200, {'max': 78})
    ev(now - 86400 * 4, 'backup_ok', 'backup', 'acc', 'Копія 2026-11-21: 1 240 файлів', 41)
    for i in range(11):
        ev(now - 5 * 3600 + i * 650, 'vb_done', 'v%d' % i, 'dim', 'Субтитри ШІ готові за %s' % dur_text(560 + i * 7), 560 + i * 7)
    temp_hist = {}
    raw_from = now - RAW_DAYS * 86400
    t = t0
    while t < now:
        t += 60 if t >= raw_from else 600
        lt = time.localtime(t)
        hr = lt.tm_hour + lt.tm_min / 60
        evening = 1 if 18 <= hr <= 23.5 else 0
        off = any(a <= t < a + d for a, d in outages)
        boost = now - 5 * 3600 <= t < now - 3 * 3600
        load = (6 + 22 * evening + rnd.random() * 8) if not boost else 92 + rnd.random() * 6
        room = 21 + 2.5 * math.sin((hr - 9) / 24 * 2 * math.pi) + (t - t0) / 86400 * 0.05
        ct = room + 16 + load * 0.38 + rnd.random() * 2 - (8 if boost else 0)
        add = lambda k, v: rows.append((t, k, round(v, 2)))
        add('cpu.load', load); add('cpu.temp', ct); add('cpu.freq', 1100 + load * 25 + rnd.random() * 200); add('cpu.w', 3 + load * 0.22 + rnd.random())
        add('t.acpi', ct - 6); add('t.nvme', room + 13 + load * 0.05); add('t.wifi', room + 18); add('t.pch', room + 22)
        add('fan.asus1', 7000 if boost else 1900 + load * 30 + (rnd.random() * 200) if ct > 50 else 0)
        add('mem.used', 11 + (14 if evening else 0) + (30 if boost else 0) + rnd.random() * 2); add('swap.used', 5 + (3 if boost else 0))
        rx = (2.5e6 + rnd.random() * 3e6) if evening and rnd.random() < 0.7 else rnd.random() * 2e4
        add('net.rx', rx); add('net.tx', rx * 0.03 + rnd.random() * 5e3)
        add('wifi.signal', -58 + rnd.random() * 5)
        inet = not any(a + 120 <= t < a + d + 300 for a, d in outages)
        add('net.inet', 1 if inet else 0)
        if inet:
            add('net.ping', 14 + rnd.random() * 6 + (40 if rnd.random() < 0.01 else 0))
        pct = 60 if not off else max(15, 60 - (t - next(a for a, d in outages if a <= t < a + d)) / 400)
        add('bat.pct', pct); add('bat.ac', 0 if off else 1); add('bat.w', 9 + load * 0.15 if off else 0.2)
        add('boost', 1 if boost else 0)
        add('log.err', 1 if rnd.random() < 0.0008 else 0)
        add('vb.queue', 4 if boost else 0)
        if t % 600 == 0:
            bat_h -= 0.00012
            add('bat.health', bat_h); add('bat.cycles', bat_c + (t - t0) // (6 * 86400))
            add('cpu.throttle', thr); thr += 1 if boost else 0
            for v in ('vidbox', 'hata', 'hata-screen', 'smbd', 'tailscaled'):
                add('svc.' + v, 1)
        for did, m in disks.items():
            pre = 'disk.%s.' % did
            c = cnt[did]
            if m['rot']:
                if did == 'TOS1':
                    want = evening and rnd.random() < 0.6 or (t - t0) % 86400 < 600
                    if want != awake[did]:
                        if want:
                            c['cycles'] += 0
                            c['load_cycles'] += 1
                            who = rnd.choice(['vidbox', 'vidbox', 'vidbox (ffmpeg)', 'smbd'])
                            if rnd.random() < 0.5 or t % 3600 < 60:
                                evs.append((t, 'disk_wake', did, 'dim', 'Диск 1 прокинувся — %s' % who, None, json.dumps({'who': who})))
                        else:
                            evs.append((t, 'disk_sleep', did, 'dim', 'Диск 1 заснув', None, None))
                        awake[did] = want
                add(pre + 'awake', 1 if awake[did] else 0)
                if awake[did]:
                    add(pre + 'temp', room + (14 if did == 'WDWX1' else 17) + load * 0.03)
                    io = (8e6 + rnd.random() * 4e6) if evening and rnd.random() < 0.5 else rnd.random() * 1e4
                    add(pre + 'io', io); add(pre + 'busy', min(100, io / 2e5))
                    if io > 5e5 or t % 3600 == 0:
                        touch.append((t, did, 'vidbox (ffmpeg)' if io > 5e5 else rnd.choice(['vidbox', 'система (скидання кешу на диск)', 'smbd']), int(io * 60)))
                else:
                    add(pre + 'io', 0); add(pre + 'busy', 0)
            else:
                add(pre + 'temp', room + 6 + load * 0.08); add(pre + 'io', rnd.random() * 2e5); add(pre + 'busy', rnd.random() * 3)
            if t % 3600 == 0:
                c['hours'] += 1 if (m['rot'] is False or did == 'WDWX1' or awake.get(did)) else 0
            if t % 600 == 0:
                if did == 'WDWX1' and abs(t - (now - 86400 - 5000)) < 300:
                    c['crc'] = 3
                if did == 'WDWX1' and rnd.random() < 0.02:
                    c['load_cycles'] += 1
                for k, v in c.items():
                    add(pre + k, v)
                add(pre + 'used', {'WDWX1': 96.4, 'TOS1': 81.2, 'S6X1': 16.1}[did] + (t - t0) / 86400 * 0.02)
        if len(rows) > 200000:
            s.con.executemany('INSERT INTO samples(ts, key, v) VALUES(?,?,?)', rows)
            rows = []
            s.rollup(t)
    s.con.executemany('INSERT INTO samples(ts, key, v) VALUES(?,?,?)', rows)
    s.con.executemany('INSERT INTO events(ts, kind, subj, lvl, text, dur, data) VALUES(?,?,?,?,?,?,?)', evs)
    s.con.executemany('INSERT INTO touch(ts, disk, who, bytes) VALUES(?,?,?,?)', touch)
    s.con.commit()
    s.rollup(now)
    s.set_meta('demo_backup', {'target': 'disk', 'last': {'at': now - 4 * 86400, 'ok': True}})
    return s
