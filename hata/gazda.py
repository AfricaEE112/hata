#!/usr/bin/env python3
"""gazda — господар хати. Єдина частина Hata з правами root.

Панель (користувач hata) не може нічого зробити з системою напряму: вона просить
gazda через unix-сокет /run/hata/gazda.sock, а gazda виконує лише дії з білого
списку нижче і перевіряє кожен параметр. Довільних команд не приймає.

Запит і відповідь — один рядок JSON:  {"do": "status"}  →  {"ok": true, ...}

Те саме з терміналу:  gazda status | gazda disks | gazda update | gazda help
"""
import json
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time

SOCK = '/run/hata/gazda.sock'
STATE = '/var/lib/hata/gazda.json'          # стан, який gazda застосовує після перезавантаження
SRC = '/opt/hata/src'                       # код Hata і VidBox (належить root)
DISKS = '/srv/disks'                        # сюди монтуються диски за назвою
FSTAB = '/etc/fstab'
FSTAB_MARK = '# hata'
USER = 'hata'
SERVICES = {'vidbox', 'hata', 'hata-screen'}
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')
UUID_RE = re.compile(r'^[A-Za-z0-9-]{4,64}$')
LOCK = threading.Lock()


def run(cmd, timeout=60, check=False):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, text=True)
    if check and r.returncode:
        raise Fail((r.stderr or r.stdout).strip()[-400:] or 'команда завершилась з помилкою')
    return r


class Fail(Exception):
    """Помилка, яку можна показати людині як є."""


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE)


# ───────────────────────── стан машини ─────────────────────────

def read(path, default=''):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def cpu_temp():
    best = None
    for z in sorted(os.listdir('/sys/class/thermal')) if os.path.isdir('/sys/class/thermal') else []:
        t = read(f'/sys/class/thermal/{z}/temp')
        kind = read(f'/sys/class/thermal/{z}/type')
        if t.isdigit() and (kind.startswith(('x86_pkg', 'acpitz', 'cpu')) or best is None):
            best = int(t) / 1000
            if kind.startswith('x86_pkg'):
                break
    return round(best, 1) if best is not None else None


def battery():
    for b in sorted(os.listdir('/sys/class/power_supply')) if os.path.isdir('/sys/class/power_supply') else []:
        p = f'/sys/class/power_supply/{b}'
        if read(f'{p}/type') == 'Battery':
            ac = any(read(f'/sys/class/power_supply/{a}/online') == '1' for a in os.listdir('/sys/class/power_supply'))
            limit = read(f'{p}/charge_control_end_threshold')
            return {'pct': int(read(f'{p}/capacity', '0') or 0), 'ac': ac, 'status': read(f'{p}/status'),
                    'limit': int(limit) if limit.isdigit() else None, 'limitSupported': bool(limit)}
    return None


def mem():
    info = {}
    for line in read('/proc/meminfo').splitlines():
        k, _, v = line.partition(':')
        info[k] = int(v.split()[0]) * 1024 if v.split() else 0
    return {'total': info.get('MemTotal', 0), 'avail': info.get('MemAvailable', 0)}


def usage(path):
    try:
        du = shutil.disk_usage(path)
        return {'total': du.total, 'free': du.free}
    except OSError:
        return None


def do_status(_):
    mounted = []
    if os.path.isdir(DISKS):
        for n in sorted(os.listdir(DISKS)):
            p = os.path.join(DISKS, n)
            mounted.append({'name': n, 'path': p, 'mounted': os.path.ismount(p), **(usage(p) or {})})
    svc = {s: run(['systemctl', 'is-active', s], 10).stdout.strip() for s in sorted(SERVICES)}
    up = float(read('/proc/uptime', '0').split()[0] or 0)
    return {'host': socket.gethostname(), 'uptime': int(up), 'load': os.getloadavg()[0],
            'cpus': os.cpu_count(), 'temp': cpu_temp(), 'mem': mem(), 'battery': battery(),
            'root': usage('/'), 'disks': mounted, 'services': svc,
            'os': read('/etc/os-release').split('PRETTY_NAME="')[-1].split('"')[0], 'version': git_version()}


# ───────────────────────── диски ─────────────────────────

def lsblk():
    r = run(['lsblk', '-J', '-b', '-o', 'NAME,PATH,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINT,TYPE,TRAN,MODEL,RM'], 20, check=True)
    return json.loads(r.stdout).get('blockdevices', [])


def do_disks(_):
    """Розділи з файловою системою, які можна підключити. Системний диск позначаємо, щоб не чіпати."""
    sysdev = run(['findmnt', '-no', 'SOURCE', '/'], 10).stdout.strip()
    ours = {}
    for line in read(FSTAB).splitlines():
        if line.endswith(FSTAB_MARK):
            parts = line.split()
            ours[parts[0].replace('UUID=', '')] = os.path.basename(parts[1])
    out = []
    for d in lsblk():
        model = (d.get('model') or '').strip()
        for p in (d.get('children') or [d]):
            if not p.get('fstype') or p.get('fstype') in ('swap', 'LVM2_member', 'crypto_LUKS'):
                continue
            system = p.get('path') == sysdev or (p.get('mountpoint') or '') in ('/', '/boot', '/boot/efi')
            out.append({'dev': p.get('path'), 'size': p.get('size'), 'fs': p.get('fstype'), 'label': p.get('label') or '',
                        'uuid': p.get('uuid') or '', 'mountpoint': p.get('mountpoint') or '', 'model': model,
                        'usb': d.get('tran') == 'usb', 'system': system, 'name': ours.get(p.get('uuid') or '')})
    return {'disks': out}


def suggest_name(label, dev):
    n = re.sub(r'[^a-z0-9_-]+', '-', (label or os.path.basename(dev or 'disk')).lower()).strip('-_')
    return (n or 'disk')[:32]


def do_mount(a):
    uuid, name = str(a.get('uuid', '')), str(a.get('name', '')).lower()
    if not UUID_RE.match(uuid):
        raise Fail('Незрозумілий ідентифікатор диска')
    if not NAME_RE.match(name):
        raise Fail('Назва — лише латинські малі літери, цифри, «-» і «_», до 32 символів')
    disk = next((d for d in do_disks({})['disks'] if d['uuid'] == uuid), None)
    if not disk:
        raise Fail('Диск не знайдено — можливо, його відключили')
    if disk['system']:
        raise Fail('Це системний диск, його не підключаємо як диск з даними')
    point = os.path.join(DISKS, name)
    with LOCK:
        lines = [l for l in read(FSTAB).splitlines() if not (l.endswith(FSTAB_MARK) and (f'UUID={uuid} ' in l or f' {point} ' in l))]
        fs = disk['fs']
        uidgid = 'uid={0},gid={0}'.format(USER_IDS()[0])
        if fs in ('ntfs', 'ntfs3'):
            opts, fstype = f'nofail,x-systemd.device-timeout=10s,{uidgid},umask=022,windows_names', 'ntfs3'
        elif fs in ('vfat', 'exfat'):
            opts, fstype = f'nofail,x-systemd.device-timeout=10s,{uidgid},umask=022', fs
        else:
            opts, fstype = 'nofail,x-systemd.device-timeout=10s,noatime', 'auto'
        lines.append(f'UUID={uuid} {point} {fstype} {opts} 0 2 {FSTAB_MARK}')
        with open(FSTAB + '.hata-tmp', 'w') as f:
            f.write('\n'.join(lines) + '\n')
        os.replace(FSTAB + '.hata-tmp', FSTAB)
        os.makedirs(point, exist_ok=True)
        run(['systemctl', 'daemon-reload'], 30)
        if disk['mountpoint'] and disk['mountpoint'] != point:
            run(['umount', disk['mountpoint']], 30)
        if not os.path.ismount(point):
            run(['mount', point], 60, check=True)
    return {'path': point}


def do_unmount(a):
    name = str(a.get('name', '')).lower()
    if not NAME_RE.match(name):
        raise Fail('Невідома назва диска')
    point = os.path.join(DISKS, name)
    with LOCK:
        lines = read(FSTAB).splitlines()
        keep = [l for l in lines if not (l.endswith(FSTAB_MARK) and f' {point} ' in l)]
        if len(keep) != len(lines):
            with open(FSTAB + '.hata-tmp', 'w') as f:
                f.write('\n'.join(keep) + '\n')
            os.replace(FSTAB + '.hata-tmp', FSTAB)
        if os.path.ismount(point):
            run(['umount', point], 60, check=True)
        run(['systemctl', 'daemon-reload'], 30)
    return {}


def USER_IDS():
    import pwd
    p = pwd.getpwnam(USER)
    return p.pw_uid, p.pw_gid


# ───────────────────────── ноутбук ─────────────────────────

def apply_battery_limit(v):
    for b in os.listdir('/sys/class/power_supply') if os.path.isdir('/sys/class/power_supply') else []:
        p = f'/sys/class/power_supply/{b}/charge_control_end_threshold'
        if os.path.exists(p):
            with open(p, 'w') as f:
                f.write(str(v))
            return True
    return False


def do_battery_limit(a):
    v = a.get('value')
    if not isinstance(v, int) or not 50 <= v <= 100:
        raise Fail('Межа заряду — число від 50 до 100')
    if not apply_battery_limit(v):
        raise Fail('Цей ноутбук не дозволяє обмежити заряд з Linux')
    st = load_state()
    st['battery_limit'] = v
    save_state(st)
    return {'limit': v}


# ───────────────────────── служби й живлення ─────────────────────────

def do_service(a):
    name, op = a.get('name'), a.get('op')
    if name not in SERVICES or op not in ('start', 'stop', 'restart', 'enable', 'enable-now'):
        raise Fail('Невідома служба або дія')
    cmd = ['systemctl', 'enable', '--now', name] if op == 'enable-now' else ['systemctl', op, name]
    run(cmd, 60, check=True)
    return {}


def do_power(a):
    op = a.get('op')
    if op not in ('reboot', 'poweroff'):
        raise Fail('Невідома дія')
    threading.Timer(2, lambda: run(['systemctl', op], 30)).start()   # спершу відповідаємо панелі
    return {}


# ───────────────────────── Tailscale ─────────────────────────

TS = {'proc': None, 'url': ''}


def ts_status():
    if not shutil.which('tailscale'):
        return {'installed': False}
    r = run(['tailscale', 'status', '--json'], 15)
    try:
        j = json.loads(r.stdout)
    except ValueError:
        return {'installed': True, 'state': 'NoState'}
    me = j.get('Self') or {}
    return {'installed': True, 'state': j.get('BackendState'), 'name': (me.get('DNSName') or '').rstrip('.'),
            'ips': me.get('TailscaleIPs') or [], 'url': TS['url'] if j.get('BackendState') != 'Running' else ''}


def do_tailscale(a):
    op = a.get('op', 'status')
    if op == 'status':
        return ts_status()
    if op == 'up':
        if not shutil.which('tailscale'):
            r = subprocess.run('curl -fsSL https://tailscale.com/install.sh | sh', shell=True, timeout=600,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if r.returncode or not shutil.which('tailscale'):
                raise Fail('Не вдалося встановити Tailscale: ' + r.stdout.strip()[-300:])
        st = ts_status()
        if st.get('state') == 'Running':
            return st
        if not (TS['proc'] and TS['proc'].poll() is None):
            TS['url'] = ''
            TS['proc'] = subprocess.Popen(['tailscale', 'up', '--qr=false'], stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, text=True)

            def watch(p=TS['proc']):
                for line in p.stdout:
                    m = re.search(r'https://login\.tailscale\.com/\S+', line)
                    if m:
                        TS['url'] = m.group(0)
            threading.Thread(target=watch, daemon=True).start()
        for _ in range(40):     # посилання для входу з'являється за секунду-дві
            if TS['url'] or ts_status().get('state') == 'Running':
                break
            time.sleep(0.25)
        return ts_status()
    if op == 'down':
        run(['tailscale', 'down'], 30)
        return ts_status()
    raise Fail('Невідома дія з Tailscale')


# ───────────────────────── оновлення з відкатом ─────────────────────────

def git(*args, timeout=120):
    return run(['git', '-C', SRC, *args], timeout)


def git_version():
    r = git('log', '-1', '--format=%h %cI', timeout=10)
    return r.stdout.strip() if r.returncode == 0 else ''


def panel_alive(timeout=40):
    import urllib.request
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen('http://127.0.0.1/api/ping', timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def do_update(_):
    """git pull; перезапуск служб; якщо панель не піднялась — повернення на попередню версію."""
    with LOCK:
        before = git('rev-parse', 'HEAD', timeout=10).stdout.strip()
        r = git('fetch', '--quiet', 'origin')
        if r.returncode:
            raise Fail('Немає зв\'язку з GitHub: ' + r.stderr.strip()[-200:])
        target = git('rev-parse', '@{u}', timeout=10).stdout.strip()
        if not target or target == before:
            return {'changed': False, 'version': git_version()}
        if git('reset', '--hard', target).returncode:
            raise Fail('Не вдалося перейти на нову версію')
        run(['systemctl', 'restart', 'hata'], 60)
        if not panel_alive():
            git('reset', '--hard', before)
            run(['systemctl', 'restart', 'hata'], 60)
            raise Fail('Нова версія не запустилась — повернув попередню')
        run(['systemctl', 'try-restart', 'vidbox', 'hata-screen'], 60)
        threading.Timer(3, lambda: os._exit(0)).start()   # systemd підніме gazda вже з новим кодом
        return {'changed': True, 'from': before[:7], 'version': git_version()}


ACTIONS = {
    'ping': lambda a: {'pong': True},
    'status': do_status,
    'disks': do_disks,
    'mount': do_mount,
    'unmount': do_unmount,
    'battery_limit': do_battery_limit,
    'service': do_service,
    'power': do_power,
    'tailscale': do_tailscale,
    'update': do_update,
}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(64 * 1024)
        try:
            req = json.loads(line or b'{}')
            act = ACTIONS.get(req.get('do'))
            if not act:
                raise Fail('Невідома дія')
            res = {'ok': True, **(act(req) or {})}
        except Fail as e:
            res = {'ok': False, 'error': str(e)}
        except Exception as e:   # не падаємо через одну погану дію
            print('gazda: помилка в', line[:200], repr(e), flush=True)
            res = {'ok': False, 'error': 'Внутрішня помилка gazda: %s' % e}
        self.wfile.write((json.dumps(res, ensure_ascii=False) + '\n').encode())


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve():
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    if os.path.exists(SOCK):
        os.remove(SOCK)
    st = load_state()
    if st.get('battery_limit'):
        apply_battery_limit(st['battery_limit'])
    srv = Server(SOCK, Handler)
    gid = USER_IDS()[1]
    os.chown(SOCK, 0, gid)
    os.chmod(SOCK, 0o660)      # лише root і група hata
    print('gazda слухає', SOCK, flush=True)
    srv.serve_forever()


def ask(req, timeout=900):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    s.connect(SOCK)
    s.sendall((json.dumps(req) + '\n').encode())
    data = b''
    while not data.endswith(b'\n'):
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data) if data else {'ok': False, 'error': 'gazda не відповів'}


def cli(argv):
    cmd = argv[0] if argv else 'help'
    if cmd == 'serve':
        return serve()
    simple = {'status': {'do': 'status'}, 'disks': {'do': 'disks'}, 'update': {'do': 'update'},
              'tailscale': {'do': 'tailscale', 'op': argv[1] if len(argv) > 1 else 'status'},
              'restart': {'do': 'service', 'name': argv[1] if len(argv) > 1 else 'vidbox', 'op': 'restart'}}
    if cmd not in simple:
        print(__doc__.strip())
        print('\nКоманди: status, disks, update, tailscale [up|down], restart [vidbox|hata|hata-screen]')
        return 0
    try:
        r = ask(simple[cmd])
    except (OSError, ValueError) as e:
        print('gazda не відповідає (%s). Перевір: systemctl status gazda' % e)
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get('ok') else 1


if __name__ == '__main__':
    sys.exit(cli(sys.argv[1:]) or 0)
