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
import mimetypes
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, 'web')
FONTS = os.path.join(os.path.dirname(HERE), 'web', 'fonts')      # шрифти VidBox — той самий стиль
DATA = os.environ.get('HATA_DATA', '/var/lib/hata')
CFG = os.path.join(DATA, 'hata.json')
VB_DATA = os.path.join(DATA, 'vidbox')
VB_PORT = 8800
PORT = int(os.environ.get('HATA_PORT', '80'))
DEMO = os.environ.get('HATA_DEMO') == '1'       # без gazda: для перевірки інтерфейсу на будь-якому комп'ютері
BROWSE_ROOTS = ('/srv/disks', '/media', '/mnt', '/home')
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
        return {'ok': True, 'path': os.path.join(DEMO_ROOT, req['name'])}
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
    if d == 'status':
        return {'ok': True, 'host': 'hata', 'uptime': 93784, 'load': 0.42, 'cpus': 8, 'temp': 47.5,
                'mem': {'total': 8 * G, 'avail': 5.6 * G}, 'os': 'Ubuntu 24.04.1 LTS', 'version': 'demo',
                'battery': {'pct': 80, 'ac': True, 'status': 'Not charging', 'limit': DEMO_STATE['limit'], 'limitSupported': True},
                'root': {'total': 512 * G, 'free': 430 * G},
                'disks': [{'name': n, 'path': os.path.join(DEMO_ROOT, n), 'mounted': True, 'total': 2000 * G, 'free': 600 * G}
                          for n in DEMO_STATE['mounted'].values()],
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


def lan_ips():
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
        p, qs = u.path, urllib.parse.parse_qs(u.query)
        if p == '/api/ping':
            return self.json({'ok': True})
        if p == '/api/state':
            return self.json({'setup': CONF['setup_done'], 'hasPassword': bool(CONF['password_hash']),
                              'authed': self.authed(), 'host': socket.gethostname(), 'demo': DEMO})
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
            return self.json(gazda({'do': 'update'}, 300))
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
