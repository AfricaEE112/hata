#!/usr/bin/env python3
"""gazda — господар хати. Єдина частина Hata з правами root.

Панель (користувач hata) не може нічого зробити з системою напряму: вона просить
gazda через unix-сокет /run/hata/gazda.sock, а gazda виконує лише дії з білого
списку нижче і перевіряє кожен параметр. Довільних команд не приймає.

Запит і відповідь — один рядок JSON:  {"do": "status"}  →  {"ok": true, ...}

Те саме з терміналу:  gazda status | gazda disks | gazda update | gazda help
Забув пароль панелі:  sudo gazda password
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
        if d.get('type') in ('loop', 'rom', 'zram') or (d.get('name') or '').startswith(('loop', 'zram')):
            continue                 # snap-пакети, CD, стиснена пам'ять — це не диски з даними
        model = (d.get('model') or '').strip()
        for p in (d.get('children') or [d]):
            if not p.get('fstype') or p.get('fstype') in ('swap', 'LVM2_member', 'crypto_LUKS', 'squashfs'):
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
        for l in read(FSTAB).splitlines():
            if l.endswith(FSTAB_MARK) and f' {point} ' in l and not l.startswith(f'UUID={uuid} '):
                raise Fail(f'Назва «{name}» вже зайнята іншим диском — дай цьому іншу (наприклад, {name}2)')
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

def git(*args, timeout=600):
    try:
        return run(['git', '-C', SRC, *args], timeout)
    except subprocess.TimeoutExpired:
        raise Fail('GitHub не відповів за %d хв — дуже повільний інтернет. Перевір швидкість у блоці «мережа».' % (timeout // 60))


def fetch():
    """git fetch лише гілки, за якою йде сервер (зазвичай main), без службових гілок CI."""
    up = git('rev-parse', '--abbrev-ref', '@{u}', timeout=10).stdout.strip() or 'origin/main'
    br = up.split('/', 1)[-1]
    git('config', 'remote.origin.fetch', f'+refs/heads/{br}:refs/remotes/origin/{br}', timeout=10)
    return git('fetch', '--quiet', 'origin')


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
        r = fetch()
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


def do_update_check(_):
    """Що прийде з оновленням: список нових комітів (без зміни коду)."""
    with LOCK:
        r = fetch()
        if r.returncode:
            raise Fail('Немає зв\'язку з GitHub')
        log = git('log', '--format=%h%x09%s', '-n', '20', 'HEAD..@{u}', timeout=10).stdout
    commits = [dict(zip(('hash', 'msg'), l.split('\t', 1))) for l in log.splitlines() if '\t' in l]
    return {'version': git_version(), 'commits': commits}


# ───────────────────────── журнал ─────────────────────────

JOURNAL_UNITS = ('hata', 'vidbox', 'gazda', 'hata-screen')


def do_journal(a):
    """Останні рядки журналу служб Hata — для блоку «журнал» у панелі."""
    n = min(max(int(a.get('n') or 14), 1), 100)
    cmd = ['journalctl', '--no-pager', '-o', 'json', '-n', str(n)]
    for u in JOURNAL_UNITS:
        cmd += ['-u', u]
    lines = []
    for raw in run(cmd, 20).stdout.splitlines():
        try:
            j = json.loads(raw)
        except ValueError:
            continue
        msg = j.get('MESSAGE')
        if isinstance(msg, list):          # не-UTF-8 повідомлення journald віддає байтами
            msg = bytes(msg).decode('utf-8', 'replace')
        unit = j.get('_SYSTEMD_UNIT') or j.get('SYSLOG_IDENTIFIER') or ''
        if unit == 'init.scope':         # повідомлення самого systemd про службу («Started vidbox.service…»)
            unit = j.get('UNIT') or unit
        unit = unit.replace('.service', '')
        lines.append({'t': int(j.get('__REALTIME_TIMESTAMP', 0)) // 1000000, 'unit': unit,
                      'msg': str(msg or '')[:300]})
    return {'lines': lines}


# ───────────────────────── пароль (лише з термінала) ─────────────────────────

def reset_password():
    """sudo gazda password — новий пароль для панелі, VidBox і апки, якщо старий забуто."""
    import getpass
    import hashlib
    cfg = '/var/lib/hata/hata.json'
    try:
        with open(cfg, encoding='utf-8') as f:
            c = json.load(f)
    except (OSError, ValueError):
        print('Hata ще не налаштована — відкрий панель у браузері, там майстер.')
        return 1
    a = getpass.getpass('Новий пароль: ')
    if len(a) < 6:
        print('Щонайменше 6 символів.')
        return 1
    if getpass.getpass('Ще раз: ') != a:
        print('Паролі не збігаються.')
        return 1
    h = hashlib.pbkdf2_hmac('sha256', a.encode('utf-8'), c['secret'].encode(), 120000).hex()
    uid, gid = USER_IDS()
    for path, key_secret in ((cfg, False), ('/var/lib/hata/vidbox/config.json', True)):
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        d['password_hash'] = h
        if key_secret:
            d['secret'] = c['secret']
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chown(tmp, uid, gid)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    run(['systemctl', 'try-restart', 'hata', 'vidbox'], 60)
    print('Готово. Увійди з новим паролем; телефони й апка попросять його ще раз.')
    return 0


# ───────────────────────── Wi-Fi ─────────────────────────
# Через netplan (як і решта мережі в Ubuntu Server): наш файл — 60-hata-wifi.yaml, решту не чіпаємо.

WIFI_NETPLAN = '/etc/netplan/60-hata-wifi.yaml'


def wifi_iface():
    for n in sorted(os.listdir('/sys/class/net')):
        if os.path.isdir(f'/sys/class/net/{n}/wireless') or os.path.exists(f'/sys/class/net/{n}/phy80211'):
            return n
    return None


def ensure_pkgs(*names):
    """Доставити пакети, яких бракує (оновлення Hata не запускає інсталятор заново)."""
    missing = [n for n in names if run(['dpkg-query', '-W', '-f=${Status}', n], 10).stdout.find('install ok installed') < 0]
    if missing:
        r = run(['apt-get', 'install', '-y', '-q', '--no-install-recommends'] + missing, 600)
        if r.returncode:
            raise Fail('Не вдалося встановити ' + ', '.join(missing) + ' — потрібен інтернет')


def iw_text(s):
    """iw показує не-ASCII байти як \\xNN — повертаємо нормальний UTF-8 (кириличні назви мереж)."""
    try:
        return re.sub(rb'\\x([0-9a-fA-F]{2})', lambda m: bytes([int(m.group(1), 16)]), s.encode('latin-1', 'replace')).decode('utf-8', 'replace')
    except Exception:
        return s


def wifi_saved():
    try:
        m = re.search(r'access-points:\s*\n\s*("(?:[^"\\]|\\.)*")', read(WIFI_NETPLAN))
        return json.loads(m.group(1)) if m else None
    except ValueError:
        return None


def wifi_link(iface):
    out = run(['iw', 'dev', iface, 'link'], 10).stdout if shutil.which('iw') else ''
    ssid = re.search(r'^\s*SSID: (.*)$', out, re.M)
    sig = re.search(r'signal: (-?\d+)', out)
    return {'ssid': iw_text(ssid.group(1)) if ssid else None, 'signal': int(sig.group(1)) if sig else None}


KEEPER_SAID = {}


def keeper():
    """Фонова турбота, раз на 20 с:
    - диск з fstab з'явився пізніше за завантаження (USB, док без живлення) — підмонтувати;
    - енергозбереження Wi-Fi знову ввімкнулось (після перепідключення) — вимкнути: серверу воно лише ріже швидкість."""
    while True:
        try:
            for line in read(FSTAB).splitlines():
                if not line.endswith(FSTAB_MARK) or not line.startswith('UUID='):
                    continue
                uuid, point = line.split()[0][5:], line.split()[1]
                if os.path.exists('/dev/disk/by-uuid/' + uuid) and not os.path.ismount(point):
                    with LOCK:
                        r = run(['mount', point], 60)
                    msg = 'з запізненням' if r.returncode == 0 else '— не вдалося: ' + r.stderr.strip()[-200:]
                    if KEEPER_SAID.get(point) != msg:      # не засмічуємо журнал однаковою помилкою щоразу
                        print('gazda: підмонтував' if r.returncode == 0 else 'gazda: не підмонтував', point, msg, flush=True)
                        KEEPER_SAID[point] = msg
            iface = wifi_iface()
            if iface and shutil.which('iw') and 'on' in run(['iw', 'dev', iface, 'get', 'power_save'], 10).stdout:
                run(['iw', 'dev', iface, 'set', 'power_save', 'off'], 10)
        except Exception as e:      # турбота не має валити gazda
            print('gazda keeper:', repr(e), flush=True)
        time.sleep(20)


def do_wifi(a):
    op = a.get('op') or 'status'
    iface = wifi_iface()
    if not iface:
        return {'iface': None}
    if op == 'status':
        return dict(wifi_link(iface), iface=iface, saved=wifi_saved())
    ensure_pkgs('iw', 'wpasupplicant')
    if op == 'scan':
        run(['ip', 'link', 'set', iface, 'up'], 10)
        for _ in range(3):
            r = run(['iw', 'dev', iface, 'scan'], 40)
            if r.returncode == 0:
                break
            time.sleep(1.5)          # «Device or resource busy» — адаптер ще шукає сам
        nets = {}
        for block in re.split(r'^BSS ', r.stdout, flags=re.M)[1:]:
            m = re.search(r'^\s*SSID: (.+)$', block, re.M)
            if not m or not m.group(1).strip():
                continue
            ssid = iw_text(m.group(1).strip())
            sig = re.search(r'signal: (-?[\d.]+)', block)
            freq = re.search(r'freq: (\d+)', block)
            n = {'ssid': ssid, 'signal': int(float(sig.group(1))) if sig else -100,
                 'secure': bool(re.search(r'^\s*(RSN|WPA):', block, re.M)),
                 'band': '5 ГГц' if freq and int(freq.group(1)) > 4000 else '2,4 ГГц'}
            if ssid not in nets or n['signal'] > nets[ssid]['signal']:
                nets[ssid] = n
        return {'iface': iface, 'networks': sorted(nets.values(), key=lambda n: -n['signal'])}
    if op == 'connect':
        ssid, pw = str(a.get('ssid') or ''), str(a.get('password') or '')
        if not 0 < len(ssid.encode()) <= 32:
            raise Fail('Назва мережі — від 1 до 32 символів')
        if pw and not 8 <= len(pw) <= 63:
            raise Fail('Пароль Wi-Fi — від 8 до 63 символів')
        ap = ('\n          password: ' + json.dumps(pw, ensure_ascii=False)) if pw else ' {}'
        text = ('# Записано Hata (панель → мережа → Wi-Fi). Змінюй через панель.\nnetwork:\n  version: 2\n  wifis:\n'
                f'    {iface}:\n      dhcp4: true\n      optional: true\n'
                '      dhcp4-overrides:\n        route-metric: 2000\n'        # кабель (1024) завжди важливіший за Wi-Fi
                '      access-points:\n'
                f'        {json.dumps(ssid, ensure_ascii=False)}:{ap}\n')
        old = read(WIFI_NETPLAN, None)
        with LOCK:
            fd = os.open(WIFI_NETPLAN + '.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(text)
            os.replace(WIFI_NETPLAN + '.tmp', WIFI_NETPLAN)
            r = run(['netplan', 'apply'], 90)
        if r.returncode:
            raise Fail('netplan: ' + (r.stderr or r.stdout).strip()[-300:])
        for _ in range(30):              # до ~30 с на підключення й адресу
            time.sleep(1)
            if wifi_link(iface)['ssid'] == ssid and 'inet ' in run(['ip', '-4', 'addr', 'show', 'dev', iface], 10).stdout:
                return dict(wifi_link(iface), iface=iface, saved=ssid)
        if old is None:                  # не вийшло — прибираємо, щоб не лишати зламану мережу
            os.remove(WIFI_NETPLAN)
        else:
            with open(WIFI_NETPLAN, 'w', encoding='utf-8') as f:
                f.write(old)
        run(['netplan', 'apply'], 90)
        raise Fail('Не вдалося підключитися до «%s». Перевір пароль і чи ловить мережа біля ноутбука.' % ssid)
    if op == 'forget':
        with LOCK:
            if os.path.exists(WIFI_NETPLAN):
                os.remove(WIFI_NETPLAN)
            run(['netplan', 'apply'], 90)
        return {'iface': iface, 'saved': None}
    raise Fail('Невідома дія з Wi-Fi')


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
    'update_check': do_update_check,
    'journal': do_journal,
    'wifi': do_wifi,
}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(64 * 1024)
        req = {}
        try:
            req = json.loads(line or b'{}')
            act = ACTIONS.get(req.get('do'))
            if not act:
                raise Fail('Невідома дія')
            res = {'ok': True, **(act(req) or {})}
        except Fail as e:
            res = {'ok': False, 'error': str(e)}
        except Exception as e:   # не падаємо через одну погану дію
            print('gazda: помилка в дії', (req.get('do') if isinstance(req, dict) else '?'), repr(e), flush=True)   # без аргументів: там бувають паролі
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
    threading.Thread(target=keeper, daemon=True).start()
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
    if cmd == 'password':
        if os.geteuid():
            print('Потрібні права: sudo gazda password')
            return 1
        return reset_password()
    simple = {'status': {'do': 'status'}, 'disks': {'do': 'disks'}, 'update': {'do': 'update'},
              'tailscale': {'do': 'tailscale', 'op': argv[1] if len(argv) > 1 else 'status'},
              'restart': {'do': 'service', 'name': argv[1] if len(argv) > 1 else 'vidbox', 'op': 'restart'}}
    if cmd not in simple:
        print(__doc__.strip())
        print('\nКоманди: status, disks, update, password, tailscale [up|down], restart [vidbox|hata|hata-screen]')
        return 0
    try:
        r = ask(simple[cmd])
    except PermissionError:
        print('gazda керує системою, тож потрібні права: sudo gazda %s' % ' '.join(argv))
        return 1
    except (OSError, ValueError) as e:
        print('gazda не відповідає (%s). Перевір: systemctl status gazda' % e)
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get('ok') else 1


if __name__ == '__main__':
    sys.exit(cli(sys.argv[1:]) or 0)
