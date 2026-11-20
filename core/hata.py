#!/usr/bin/env python3
"""Hata — панель домашнього сервера. Працює від звичайного користувача hata.

До першого налаштування показує майстер (пароль → диски → папки → Tailscale →
ноутбук → готово), потім — панель зі станом сервера. Усе, що потребує root,
просить у gazda (див. gazda.py). Лише стандартна бібліотека Python.

Запуск для перевірки без системи:  HATA_DEMO=1 HATA_PORT=8080 python3 hata.py
"""
import hashlib
import hmac
import http.cookies
import http.server
import json
import math
import mimetypes
import os
import re
import secrets
import socket
import sys
import threading
import time
import subprocess
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, 'web')
FONTS = os.path.join(WEB, 'fonts')      # ті самі шрифти, що й у VidBox
DATA = os.environ.get('HATA_DATA', '/var/lib/hata')
CFG = os.path.join(DATA, 'hata.json')
VB_DATA = os.path.join(DATA, 'vidbox')
VB_PORT = 8800
PORT = int(os.environ.get('HATA_PORT', '80'))
DEMO = os.environ.get('HATA_DEMO') == '1'       # без gazda: для перевірки інтерфейсу на будь-якому комп'ютері
BROWSE_ROOTS = ('/srv/disks', '/media', '/mnt', '/home')
SCHEMES = ('чай', 'ніч', 'lain', 'ягода', 'nothing', 'папір')    # кольорові схеми; ті самі імена в hata.css і screen.py
LOCK = threading.Lock()


# ───────────────────────── конфігурація ─────────────────────────

def load():
    try:
        with open(CFG, encoding='utf-8') as f:
            c = json.load(f)
    except (OSError, ValueError):
        c = {}
    c.setdefault('secret', secrets.token_hex(16))
    c.setdefault('password_hash', '')
    c.setdefault('setup_done', False)
    return c


def save(c):
    os.makedirs(DATA, exist_ok=True)
    tmp = CFG + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CFG)


CONF = load()


def pw_hash(pw, secret):
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), secret.encode(), 120000).hex()


def token():
    h = CONF.get('password_hash')
    return hmac.new(CONF['secret'].encode(), h.encode(), hashlib.sha256).hexdigest() if h else ''


# ───────────────────────── gazda ─────────────────────────

def gazda(req, timeout=900):
    if DEMO:
        return demo_gazda(req)
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    try:
        s.connect('/run/hata/gazda.sock')
        s.sendall((json.dumps(req) + '\n').encode())
        data = b''
        while not data.endswith(b'\n'):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        return json.loads(data or b'{}') or {'ok': False, 'error': 'gazda не відповів'}
    except (OSError, ValueError):
        return {'ok': False, 'error': 'Служба gazda не відповідає. На сервері: sudo systemctl restart gazda'}
    finally:
        s.close()


DEMO_STATE = {'mounted': {}, 'ts': 'off', 'limit': 100}


def demo_gazda(req):
    """Імітація gazda для перевірки інтерфейсу без root і без справжніх дисків."""
    d, G = req.get('do'), 1024 ** 3
    if d == 'disks':
        return {'ok': True, 'disks': [
            {'dev': '/dev/nvme0n1p2', 'size': 512 * G, 'fs': 'ext4', 'label': '', 'uuid': 'sys-1', 'mountpoint': '/',
             'model': 'SSD 512GB', 'usb': False, 'system': True, 'name': None},
            {'dev': '/dev/sda1', 'size': 2000 * G, 'fs': 'ntfs', 'label': 'Media', 'uuid': 'A1B2-C3D4', 'mountpoint': '',
             'model': 'ST2000LM015', 'usb': False, 'system': False, 'name': DEMO_STATE['mounted'].get('A1B2-C3D4')},
            {'dev': '/dev/sdb1', 'size': 3000 * G, 'fs': 'ext4', 'label': 'archive', 'uuid': 'E5F6-0718', 'mountpoint': '',
             'model': 'WD30EFRX', 'usb': True, 'system': False, 'name': DEMO_STATE['mounted'].get('E5F6-0718')}]}
    if d == 'mount':
        DEMO_STATE['mounted'][req['uuid']] = req['name']
        os.makedirs(os.path.join(DEMO_ROOT, req['name'], 'Фільми'), exist_ok=True)
        os.makedirs(os.path.join(DEMO_ROOT, req['name'], 'Аніме'), exist_ok=True)
        return {'ok': True, 'path': '/srv/disks/' + req['name']}
    if d == 'timezone':
        DEMO_STATE['tz'] = req.get('tz')
        return {'ok': True, 'tz': req.get('tz')}
    if d == 'unmount':
        DEMO_STATE['mounted'] = {k: v for k, v in DEMO_STATE['mounted'].items() if v != req.get('name')}
        return {'ok': True}
    if d == 'tailscale':   # off → (up) чекає входу → (up ще раз) працює
        if req.get('op') == 'up':
            DEMO_STATE['ts'] = 'Running' if DEMO_STATE['ts'] == 'NeedsLogin' else 'NeedsLogin'
        st = DEMO_STATE['ts']
        if st == 'off':
            return {'ok': True, 'installed': False}
        run = st == 'Running'
        return {'ok': True, 'installed': True, 'state': st, 'name': 'hata.tail1234.ts.net' if run else '',
                'ips': ['100.64.0.7'] if run else [], 'url': '' if run else 'https://login.tailscale.com/a/demo123'}
    if d == 'battery_limit':
        DEMO_STATE['limit'] = req['value']
        return {'ok': True, 'limit': req['value']}
    if d == 'wifi':
        op = req.get('op')
        if op == 'scan':
            time.sleep(1)
            return {'ok': True, 'iface': 'wlo1', 'networks': [
                {'ssid': 'Дім', 'signal': -45, 'secure': True, 'band': '5 ГГц'},
                {'ssid': 'TP-Link_4F2A', 'signal': -68, 'secure': True, 'band': '2,4 ГГц'},
                {'ssid': 'Кав\'ярня', 'signal': -81, 'secure': False, 'band': '2,4 ГГц'}]}
        if op == 'connect':
            time.sleep(2)
            if len(req.get('password') or '') < 8:
                return {'ok': False, 'error': 'Не вдалося підключитися до «%s». Перевір пароль.' % req.get('ssid')}
            DEMO_STATE['wifi'] = req['ssid']
        if op == 'forget':
            DEMO_STATE['wifi'] = None
        w = DEMO_STATE.get('wifi')
        return {'ok': True, 'iface': 'wlo1', 'ssid': w, 'signal': -45 if w else None, 'saved': w}
    if d == 'journal':
        now = int(time.time())
        return {'ok': True, 'lines': [
            {'t': now - 1600, 'unit': 'hata', 'msg': 'Hata: панель на порту 80'},
            {'t': now - 1300, 'unit': 'vidbox', 'msg': 'anilist: Frieren — опис і жанри збережено'},
            {'t': now - 340, 'unit': 'gazda', 'msg': 'mount media → /srv/disks/media'},
            {'t': now - 2, 'unit': 'vidbox', 'msg': 'GET /api/anime 200'}]}
    if d == 'update_check':
        return {'ok': True, 'version': 'cd4bff2 2026-11-19T15:00:00+02:00', 'commits': [
            {'hash': 'a1f3c2e', 'msg': 'Аніме: опис і жанри в апці'},
            {'hash': '7b9e011', 'msg': 'Майстер: швидкі кліки по теках'}]}
    if d == 'status':
        return {'ok': True, 'host': 'hata', 'uptime': 93784, 'load': 0.42, 'cpus': 8, 'temp': 47.5,
                'mem': {'total': 8 * G, 'avail': 5.6 * G}, 'os': 'Ubuntu 24.04.1 LTS', 'version': 'cd4bff2 2026-11-19T15:00:00+02:00',
                'battery': {'pct': 80, 'ac': True, 'status': 'Not charging', 'limit': DEMO_STATE['limit'], 'limitSupported': True},
                'root': {'total': 512 * G, 'free': 430 * G},
                'disks': [{'name': n, 'path': '/srv/disks/' + n, 'mounted': True, 'total': 2000 * G, 'free': (600 + 900 * i) * G}
                          for i, n in enumerate(DEMO_STATE['mounted'].values())],
                'services': {'vidbox': 'active' if CONF.get('setup_done') else 'inactive', 'hata': 'active', 'hata-screen': 'active'}}
    return {'ok': True}


DEMO_ROOT = os.path.join(DATA, 'demo-disks')
if DEMO:
    BROWSE_ROOTS = (DEMO_ROOT,)


# ───────────────────────── VidBox ─────────────────────────

def write_vidbox(folders, anime):
    """Майстер налаштовує VidBox: папки, аніме й той самий пароль, що в Hata
    (VidBox хешує пароль так само, тож досить дати йому той самий секрет і хеш)."""
    os.makedirs(VB_DATA, exist_ok=True)
    p = os.path.join(VB_DATA, 'config.json')
    try:
        with open(p, encoding='utf-8') as f:
            vb = json.load(f)
    except (OSError, ValueError):
        vb = {}
    vb['folders'] = folders
    vb['anime_folder'] = anime or ''
    vb['open_browser'] = False
    vb['secret'] = CONF['secret']
    vb['password_hash'] = CONF['password_hash']
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(vb, f, ensure_ascii=False, indent=1)
    os.replace(p + '.tmp', p)


def list_dirs(path):
    path = os.path.realpath(path or '')
    roots = [r for r in BROWSE_ROOTS if os.path.isdir(r)]
    if not path or not any(path == r or path.startswith(r + os.sep) for r in roots):
        return {'path': '', 'dirs': [{'name': r, 'path': r} for r in roots]}
    try:
        names = sorted((n for n in os.listdir(path) if not n.startswith('.') and os.path.isdir(os.path.join(path, n))),
                       key=str.lower)
    except OSError:
        names = []
    up = os.path.dirname(path) if path not in roots else ''
    return {'path': path, 'up': up, 'dirs': [{'name': n, 'path': os.path.join(path, n)} for n in names[:500]]}


# ───────────────────────── живі цифри для панелі ─────────────────────────
# Читаємо /proc і /sys самі (без gazda) — це дешево, тож панель питає щосекунди-дві.

CPU_LAST = [0, 0]


def cpu_percent():
    try:
        with open('/proc/stat') as f:
            v = [int(x) for x in f.readline().split()[1:]]
    except (OSError, ValueError):
        return None
    idle, total = v[3] + (v[4] if len(v) > 4 else 0), sum(v)
    with LOCK:
        di, dt = idle - CPU_LAST[0], total - CPU_LAST[1]
        CPU_LAST[:] = [idle, total]
    return round(100 * (1 - di / dt)) if dt > 0 else None


def read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def live():
    mem = {}
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                k, _, v = line.partition(':')
                if k in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
                    mem[k] = int(v.split()[0]) * 1024
    except OSError:
        pass
    temp = None
    base = '/sys/class/thermal'
    for z in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        t = read_int(os.path.join(base, z, 'temp'))
        try:
            kind = open(os.path.join(base, z, 'type')).read().strip()
        except OSError:
            kind = ''
        if t is not None and (temp is None or kind.startswith('x86_pkg')):
            temp = round(t / 1000, 1)
            if kind.startswith('x86_pkg'):
                break
    rx = tx = 0
    try:
        with open('/proc/net/dev') as f:
            for line in f.readlines()[2:]:
                name, _, v = line.partition(':')
                name, v = name.strip(), v.split()
                if name != 'lo' and not name.startswith(('docker', 'veth', 'br-')) and len(v) > 8:
                    rx += int(v[0])
                    tx += int(v[8])
    except (OSError, ValueError):
        pass
    if DEMO:                      # у демо — вигаданий трафік і температура, щоб графіки жили
        temp = temp if temp is not None else 41.0
        DEMO_NET[0] += int(abs(math.sin(time.time() / 9)) * 6e6 + secrets.randbelow(1500000))
        rx += DEMO_NET[0]
    return {'cpu': cpu_percent(), 'temp': temp, 'time': int(time.time()), 'net': {'rx': rx, 'tx': tx},
            'mem': {'total': mem.get('MemTotal', 0), 'avail': mem.get('MemAvailable', 0)},
            'swap': {'total': mem.get('SwapTotal', 0), 'free': mem.get('SwapFree', 0)}}


# ───────────────────────── мережа: інтерфейси й швидкість ─────────────────────────

def sysread(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ''


def net_ifaces():
    """Що є в мережі: кабель, Wi-Fi, телефон, Tailscale — з швидкістю лінку й USB (для діагностики)."""
    if DEMO:
        return {'route': 'enx00e04c680001', 'ifaces': [
            {'name': 'enx00e04c680001', 'kind': 'cable', 'up': True, 'ips': ['192.168.1.20'], 'speed': 1000, 'usb': 5000, 'driver': 'r8152'},
            {'name': 'wlo1', 'kind': 'wifi', 'up': DEMO_STATE.get('wifi') is not None, 'ips': ['192.168.1.21'] if DEMO_STATE.get('wifi') else []}]}
    addrs = {}
    try:
        out = subprocess.run(['ip', '-j', '-4', 'addr'], stdout=subprocess.PIPE, text=True, timeout=5).stdout
        for i in json.loads(out or '[]'):
            addrs[i['ifname']] = [a['local'] for a in i.get('addr_info', [])]
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    route = ''
    try:
        out = subprocess.run(['ip', '-j', 'route', 'get', '1.1.1.1'], stdout=subprocess.PIPE, text=True, timeout=5).stdout
        route = (json.loads(out or '[{}]') or [{}])[0].get('dev', '')
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    res = []
    for n in sorted(os.listdir('/sys/class/net')):
        if n == 'lo' or n.startswith(('docker', 'veth', 'br-', 'virbr')):
            continue
        base = '/sys/class/net/' + n
        dev = os.path.realpath(base + '/device') if os.path.exists(base + '/device') else ''
        drv = os.path.basename(os.path.realpath(base + '/device/driver')) if dev else ''
        if os.path.isdir(base + '/wireless') or os.path.exists(base + '/phy80211'):
            kind = 'wifi'
        elif n.startswith('tailscale'):
            kind = 'tailscale'
        elif drv in ('rndis_host', 'cdc_ether', 'ipheth') or n.startswith('usb'):
            kind = 'phone'
        elif dev:
            kind = 'cable'
        else:
            continue
        up = sysread(base + '/operstate') in ('up', 'unknown') and bool(addrs.get(n))
        i = {'name': n, 'kind': kind, 'up': up, 'ips': addrs.get(n, []), 'driver': drv}
        if kind == 'cable' and up:
            sp = sysread(base + '/speed')
            i['speed'] = int(sp) if sp.lstrip('-').isdigit() and int(sp) > 0 else None
        if '/usb' in dev:                # швидкість USB-шини: 480 = USB 2.0, 5000+ = USB 3
            sp = sysread(os.path.dirname(dev) + '/speed')
            i['usb'] = int(float(sp)) if sp.replace('.', '', 1).isdigit() else None
        res.append(i)
    return {'route': route, 'ifaces': res}


SPEED_LOCK = threading.Lock()


def speedtest():
    """Швидкість інтернету: затримка (найкраща з 3) і завантаження до ~10 с з Cloudflare."""
    if DEMO:
        time.sleep(3)
        return {'ok': True, 'mbit': 94.2, 'ms': 18, 'dev': 'enx00e04c680001'}
    if not SPEED_LOCK.acquire(blocking=False):
        return {'ok': False, 'error': 'Перевірка вже йде'}
    try:
        # curl — той самий, що й у терміналі: Cloudflare його пускає, а запити з Python часом відкидає (403)
        def curl(url, fmt, limit):
            r = subprocess.run(['curl', '-o', '/dev/null', '-s', '--max-time', str(limit), '-w', fmt, url],
                               stdout=subprocess.PIPE, text=True, timeout=limit + 5)
            return r.stdout.split()
        base = 'https://speed.cloudflare.com/__down?bytes='
        ms = []
        for _ in range(3):
            code, conn = curl(base + '1000', '%{http_code} %{time_connect}', 8)
            if code == '000':
                return {'ok': False, 'error': 'Немає зв\'язку з інтернетом'}
            ms.append(float(conn) * 1000)
        # 25 МБ: більші шматки Cloudflare відкидає (403); на 100 Мбіт це ~2 с, на повільному — обріже --max-time
        code, speed = curl(base + '25000000', '%{http_code} %{speed_download}', 12)
        if code not in ('200', '000'):
            return {'ok': False, 'error': 'Сервер перевірки (Cloudflare) відповів %s — спробуй пізніше' % code}
        return {'ok': True, 'mbit': round(float(speed) * 8 / 1e6, 1), 'ms': round(min(ms)), 'dev': net_ifaces()['route']}
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {'ok': False, 'error': 'Не вдалося перевірити швидкість (%s)' % e}
    finally:
        SPEED_LOCK.release()


UPDATES = {'at': 0, 'data': None}
DEMO_NET = [0]


def updates(force=False):
    """Що нового на GitHub — питаємо gazda не частіше ніж раз на 10 хвилин."""
    if force or not UPDATES['data'] or time.time() - UPDATES['at'] > 600:
        UPDATES['data'] = gazda({'do': 'update_check'}, 660)
        UPDATES['at'] = time.time()
    return UPDATES['data']


def lan_ips():
    if DEMO:
        return ['192.168.1.20']
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return ips


# ───────────────────────── HTTP ─────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'Hata'
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype='application/json; charset=utf-8', extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def json(self, obj, code=200, extra=None):
        self.send(code, json.dumps(obj, ensure_ascii=False).encode(), extra=extra)

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > 1 << 20:
            raise ValueError('завеликий запит')
        try:
            return json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return {}

    def authed(self):
        t = token()
        if not t:
            return True
        c = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
        return 'hata' in c and hmac.compare_digest(c['hata'].value, t)

    def cookie(self):
        return {'Set-Cookie': 'hata=%s; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax' % token()}

    def static(self, path):
        if path in ('', '/'):
            path = '/index.html'
        base = FONTS if path.startswith('/fonts/') else WEB
        rel = path[len('/fonts/'):] if path.startswith('/fonts/') else path.lstrip('/')
        f = os.path.realpath(os.path.join(base, rel))
        if not f.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(f):
            return self.send(404, b'not found', 'text/plain')
        with open(f, 'rb') as fh:
            data = fh.read()
        ctype = mimetypes.guess_type(f)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype.endswith('javascript'):
            ctype += '; charset=utf-8'
        self.send(200, data, ctype)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p, qs = u.path, urllib.parse.parse_qs(u.query, keep_blank_values=True)
        if p == '/api/ping':
            return self.json({'ok': True})
        if p == '/api/state':
            return self.json({'setup': CONF['setup_done'], 'hasPassword': bool(CONF['password_hash']),
                              'authed': self.authed(), 'host': 'hata' if DEMO else socket.gethostname(), 'demo': DEMO,
                              'scheme': CONF.get('scheme', SCHEMES[0]), 'schemes': SCHEMES})
        if not p.startswith('/api/'):
            return self.static(p)
        if not self.authed():
            return self.json({'error': 'auth'}, 401)
        if p == '/api/status':
            st = gazda({'do': 'status'}, 30)
            st['vidbox'] = {'port': VB_PORT}
            st['ips'] = lan_ips()
            st['tailscale'] = gazda({'do': 'tailscale', 'op': 'status'}, 30)
            return self.json(st)
        if p == '/api/disks':
            return self.json(gazda({'do': 'disks'}, 60))
        if p == '/api/dirs':
            return self.json(list_dirs(qs.get('path', [''])[0]))
        if p == '/api/tailscale':
            return self.json(gazda({'do': 'tailscale', 'op': 'status'}, 30))
        if p == '/api/net':
            r = net_ifaces()
            r['wifi'] = gazda({'do': 'wifi', 'op': 'status'}, 20)
            return self.json(r)
        if p == '/api/live':
            return self.json(live())
        if p == '/api/journal':
            return self.json(gazda({'do': 'journal', 'n': 14}, 30))
        if p == '/api/updates':
            return self.json(updates('force' in qs))
        return self.json({'error': 'not found'}, 404)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        d = self.body()
        if p == '/api/login':
            pw = str(d.get('password') or '')
            if CONF['password_hash'] and hmac.compare_digest(pw_hash(pw, CONF['secret']), CONF['password_hash']):
                return self.json({'ok': True}, extra=self.cookie())
            time.sleep(1)       # повільніше підбирати пароль
            return self.json({'ok': False, 'error': 'Неправильний пароль'}, 401)
        if p == '/api/setup/password':
            pw = str(d.get('password') or '')
            with LOCK:
                if CONF['password_hash'] and not self.authed():
                    return self.json({'ok': False, 'error': 'Пароль уже встановлено — увійди з ним'}, 403)
                if len(pw) < 6:
                    return self.json({'ok': False, 'error': 'Пароль має бути щонайменше з 6 символів'})
                CONF['password_hash'] = pw_hash(pw, CONF['secret'])
                save(CONF)
            return self.json({'ok': True}, extra=self.cookie())
        if not self.authed():
            return self.json({'error': 'auth'}, 401)
        if p == '/api/logout':
            return self.json({'ok': True}, extra={'Set-Cookie': 'hata=; Max-Age=0; Path=/'})
        if p == '/api/mount':
            return self.json(gazda({'do': 'mount', 'uuid': d.get('uuid'), 'name': d.get('name')}, 120))
        if p == '/api/unmount':
            return self.json(gazda({'do': 'unmount', 'name': d.get('name')}, 120))
        if p == '/api/tailscale':
            return self.json(gazda({'do': 'tailscale', 'op': d.get('op', 'up')}, 700))
        if p == '/api/battery':
            return self.json(gazda({'do': 'battery_limit', 'value': d.get('value')}, 30))
        if p == '/api/service':
            return self.json(gazda({'do': 'service', 'name': d.get('name'), 'op': d.get('op')}, 90))
        if p == '/api/power':
            return self.json(gazda({'do': 'power', 'op': d.get('op')}, 30))
        if p == '/api/update':
            r = gazda({'do': 'update'}, 900)
            UPDATES['data'] = None
            return self.json(r)
        if p == '/api/wifi':
            if d.get('op') not in ('scan', 'connect', 'forget', 'status'):
                return self.json({'ok': False, 'error': 'Невідома дія'})
            return self.json(gazda({'do': 'wifi', 'op': d['op'], 'ssid': d.get('ssid'), 'password': d.get('password')}, 700))
        if p == '/api/timezone':
            return self.json(gazda({'do': 'timezone', 'tz': d.get('tz')}, 60))
        if p == '/api/speedtest':
            return self.json(speedtest())
        if p == '/api/scheme':
            if d.get('scheme') not in SCHEMES:
                return self.json({'ok': False, 'error': 'Невідома схема'})
            with LOCK:
                CONF['scheme'] = d['scheme']
                save(CONF)
            return self.json({'ok': True})
        if p == '/api/finish':
            folders = [f for f in d.get('folders') or [] if isinstance(f, str) and os.path.isdir(f)]
            anime = d.get('anime') if isinstance(d.get('anime'), str) and os.path.isdir(d.get('anime')) else ''
            if not folders:
                return self.json({'ok': False, 'error': 'Обери хоча б одну папку з відео'})
            write_vidbox(folders, anime)
            r = gazda({'do': 'service', 'name': 'vidbox', 'op': 'enable-now'}, 90)
            if not DEMO:
                gazda({'do': 'service', 'name': 'vidbox', 'op': 'restart'}, 90)
            with LOCK:
                CONF['setup_done'] = True
                save(CONF)
            return self.json({'ok': r.get('ok', True), 'error': r.get('error'), 'vidbox': VB_PORT})
        return self.json({'error': 'not found'}, 404)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    if DEMO:
        os.makedirs(DEMO_ROOT, exist_ok=True)
    save(CONF)
    srv = Server(('0.0.0.0', PORT), Handler)
    print('Hata: панель на порту %d%s' % (PORT, ' (демо без gazda)' if DEMO else ''), flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    sys.exit(main())
