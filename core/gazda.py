#!/usr/bin/env python3
"""gazda — господар хати. Єдина частина Hata з правами root.

Панель (користувач hata) не може нічого зробити з системою напряму: вона просить
gazda через unix-сокет /run/hata/gazda.sock, а gazda виконує лише дії з білого
списку нижче і перевіряє кожен параметр. Довільних команд не приймає.

Запит і відповідь — один рядок JSON:  {"do": "status"}  →  {"ok": true, ...}

Те саме з терміналу:  gazda status | gazda disks | gazda update | gazda help
Забув пароль панелі:  sudo gazda password
"""
import glob
import json
import mmap
import os
import random
import re
import shutil
import signal
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
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
HEALTH = None          # сховище ТО (core/health.py), запускається в serve()


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


def tz_name():
    p = os.path.realpath('/etc/localtime')
    return p.split('/zoneinfo/', 1)[1] if '/zoneinfo/' in p else 'UTC'


def do_status(_):
    # диски Hata — ті, що записані в fstab; порожні теки від відключених дисків не показуємо
    names = sorted({os.path.basename(l.split()[1]) for l in read(FSTAB).splitlines() if l.endswith(FSTAB_MARK) and len(l.split()) > 1})
    mounted = []
    for n in names:
        p = os.path.join(DISKS, n)
        mounted.append({'name': n, 'path': p, 'mounted': os.path.ismount(p), **(usage(p) if os.path.ismount(p) else {})})
    svc = {s: run(['systemctl', 'is-active', s], 10).stdout.strip() for s in sorted(SERVICES)}
    up = float(read('/proc/uptime', '0').split()[0] or 0)
    return {'host': socket.gethostname(), 'uptime': int(up), 'load': os.getloadavg()[0],
            'cpus': os.cpu_count(), 'cpu_model': next((l.split(':', 1)[1].strip() for l in read('/proc/cpuinfo').splitlines()
                                                      if l.startswith('model name')), ''), 'temp': cpu_temp(), 'mem': mem(), 'battery': battery(),
            'root': usage('/'), 'disks': mounted, 'services': svc,
            'os': read('/etc/os-release').split('PRETTY_NAME="')[-1].split('"')[0], 'version': git_version(), 'tz': tz_name()}


def do_timezone(a):
    tz = str(a.get('tz') or '')
    if not re.fullmatch(r'[A-Za-z_]+(/[A-Za-z0-9_+-]+){0,2}', tz) or not os.path.isfile('/usr/share/zoneinfo/' + tz):
        raise Fail('Невідомий часовий пояс: %s' % tz)
    run(['timedatectl', 'set-timezone', tz], 30, check=True)
    return {'tz': tz_name()}


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
        if d.get('type') in ('rom',) or (d.get('name') or '').startswith('zram'):
            continue                 # CD і стиснена пам'ять — не диски з даними (snap-пакети відсіє squashfs нижче)
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
        if fstype == 'auto' and os.stat(point).st_uid == 0:
            # ext4 тощо: корінь нового диска належить root — дамо hata писати туди (файли, завантаження, Samba)
            os.chown(point, *USER_IDS())
    share_reload()
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
    share_reload()
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
    https = False
    if j.get('BackendState') == 'Running':
        try:
            sv = json.loads(run(['tailscale', 'serve', 'status', '--json'], 15).stdout or '{}')
            https = '443' in (sv.get('TCP') or {})
        except (ValueError, OSError, subprocess.TimeoutExpired):
            pass
    return {'installed': True, 'state': j.get('BackendState'), 'name': (me.get('DNSName') or '').rstrip('.'),
            'ips': me.get('TailscaleIPs') or [], 'url': TS['url'] if j.get('BackendState') != 'Running' else '', 'https': https}


def ts_serve(port, target):
    """tailscale serve у фоні. Якщо в мережі Tailscale не ввімкнено HTTPS — команда чекає й друкує посилання."""
    try:
        r = subprocess.run(['tailscale', 'serve', '--bg', '--https=%d' % port, target], timeout=25,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        out, code = r.stdout or '', r.returncode
    except subprocess.TimeoutExpired as e:
        out, code = (e.stdout or b'').decode() if isinstance(e.stdout, bytes) else (e.stdout or ''), -1
    if code:
        m = re.search(r'https://login\.tailscale\.com/\S+', out)
        if m:
            raise Fail('У Tailscale треба один раз дозволити HTTPS-адреси: відкрий ' + m.group(0) + ' , натисни «Enable» і повтори.')
        raise Fail('tailscale serve: ' + out.strip()[-300:])


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
    if op == 'https':                   # https://<ім'я>.ts.net — панель, :8443 — VidBox (для встановлення як апки)
        if ts_status().get('state') != 'Running':
            raise Fail('Спершу підключи Tailscale')
        ts_serve(443, 'http://127.0.0.1:80')
        ts_serve(8443, 'http://127.0.0.1:8800')
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
        threading.Timer(3, quit_gazda).start()   # systemd підніме gazda вже з новим кодом
        return {'changed': True, 'from': before[:7], 'version': git_version()}


def quit_gazda():
    """Вийти так, щоб ТО дописало буфер замірів і свій стан (інакше після оновлення губились останні хвилини)."""
    try:
        if HEALTH is not None:
            import health
            health.stop()
    except Exception as e:
        print('gazda: ТО не встигло зберегтись:', repr(e), flush=True)
    os._exit(0)


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
    """Останні рядки журналу служб Hata й події ТО (диски, USB, світло, інтернет…) — для блоку «журнал» у панелі.
    src: '' — усе; назва служби — лише її; 'події' — лише події ТО."""
    n = min(max(int(a.get('n') or 14), 1), 300)
    src = a.get('src') or ''
    if src and src not in JOURNAL_UNITS and src != 'події':
        raise Fail('Невідоме джерело журналу')
    lines = [] if src == 'події' else journal_lines(n, [src] if src else JOURNAL_UNITS)
    if HEALTH is not None and src in ('', 'події'):
        try:
            import health
            HEALTH.flush()
            evs = health.events(HEALTH, '1y', None, n)
            lines = [l for l in lines if not (l['unit'] == 'gazda' and 'заснув після' in l['msg'])]
            lines += [{'t': e['ts'], 'unit': 'події', 'msg': e['text'], 'lvl': e['lvl'], 'kind': e['kind']} for e in evs]
        except Exception as e:
            print('gazda: події ТО для журналу:', repr(e), flush=True)
    lines.sort(key=lambda l: l['t'])
    return {'lines': lines[-n:]}


def journal_lines(n, units):
    cmd = ['journalctl', '--no-pager', '-o', 'json', '-n', str(n)]
    for u in units:
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
                      'msg': str(msg or '')[:1000], 'lvl': 'red' if str(j.get('PRIORITY', '6')) <= '3' else 'yel' if str(j.get('PRIORITY', '6')) == '4' else ''})
    return lines


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


# ───────────────────────── здоров'я дисків (SMART), сон ─────────────────────────
# smartctl читаємо з -n standby: якщо диск спить, не будимо (лише кнопка «Оновити» будить).
# Сон HDD з даними — один з режимів:
#   -1 «як є»   — Хата не втручається: диск чи док засинають за своїм таймером;
#    0 «ніколи» — тримати розкрученим;
#    N хв       — не давати заснути раніше, а після N хв без читань/записів приспати самим (smartctl -s standby,now).
# Для 0 і N: власний таймер диска вимикаємо (standby,off; apm,254 — щоб 2,5" не паркували головки щосекунди),
# а таймер контролера в доці (його з Linux не вимкнути, у MAIWO — ~3 хв) перебиваємо крихітним читанням раз на 50 с.

SMART = {}        # пристрій → останнє прочитане (з часом)
DISK_IO = {}      # sda → [ознака активності, з якого часу без змін, чи вже приспали]
SMART_EVERY = 300
SLEEP_CHOICES = (-1, 0, 10, 20, 30, 60, 120)
KEEPALIVE_EVERY = 50
TUNED = {}        # sda → (серійник, чи прийняв диск команду) — кому вже вимкнули власний таймер
PINGED = {}       # sda → коли востаннє «торкались»
TOUCHED = {}      # sda → скільки секторів прочитали ми самі (ТО не рахує це чужою роботою)
LC_HIST = {}      # пристрій → [(час, паркувань головок)] за останні ~2 год — щоб бачити, чи паркування вщухло


def lc_note(dev, s):
    if s.get('load_cycles') is None:
        return
    h = [x for x in LC_HIST.get(dev, []) if x[0] > time.time() - 7200]
    if not h or h[-1][1] != s['load_cycles'] or time.time() - h[-1][0] > 600:
        h.append((time.time(), s['load_cycles']))
    LC_HIST[dev] = h


def lc_rate(dev):
    """Паркувань за годину за останні 30–120 хв (None, якщо замало даних)."""
    h = LC_HIST.get(dev) or []
    if len(h) < 2 or h[-1][0] - h[0][0] < 1800:
        return None
    return round((h[-1][1] - h[0][1]) / (h[-1][0] - h[0][0]) * 3600)


def lsblk_tree():
    r = run(['lsblk', '-J', '-b', '-o', 'NAME,PATH,TYPE,TRAN,MODEL,SERIAL,SIZE,ROTA,MOUNTPOINT,FSTYPE'], 20)
    try:
        return json.loads(r.stdout or '{}').get('blockdevices', [])
    except ValueError:
        return []


def phys_disks():
    """Фізичні диски Хати: системний і ті, що підключені в /srv/disks (з усіма їхніми розділами)."""
    out = []
    for d in lsblk_tree():
        mounts = []

        def walk(n):
            if n.get('mountpoint'):
                mounts.append(n['mountpoint'])
            for c in n.get('children') or []:
                walk(c)
        walk(d)
        system = any(m in ('/', '/boot', '/boot/efi') for m in mounts)
        ours = [os.path.basename(m) for m in mounts if m.startswith(DISKS + '/')]
        if not system and not ours:
            continue
        out.append({'dev': d.get('path'), 'kname': d.get('name'), 'names': (['система'] if system else []) + ours,
                    'model': (d.get('model') or '').strip(), 'serial': (d.get('serial') or '').strip(),
                    'size': int(d.get('size') or 0), 'rot': str(d.get('rota')) in ('1', 'True', 'true'),
                    'usb': d.get('tran') == 'usb', 'system': system, 'loop': d.get('type') == 'loop'})
    return out


ATTR = {5: 'realloc', 9: 'hours', 12: 'cycles', 193: 'load_cycles', 187: 'uncorrect_rep', 188: 'timeout', 194: 'temp', 190: 'temp_air',
        196: 'realloc_ev', 197: 'pending', 198: 'uncorrect', 199: 'crc', 177: 'wear_level', 231: 'life_left', 233: 'media_wear'}


def parse_smart(j):
    s = {'state': 'active', 'model': j.get('model_name') or j.get('model_family') or '', 'serial': j.get('serial_number') or '',
         'firmware': j.get('firmware_version') or '', 'rpm': j.get('rotation_rate'),
         'passed': (j.get('smart_status') or {}).get('passed'), 'temp': (j.get('temperature') or {}).get('current'),
         'hours': (j.get('power_on_time') or {}).get('hours'), 'cycles': j.get('power_cycle_count'),
         'form': (j.get('form_factor') or {}).get('name')}
    for a in (j.get('ata_smart_attributes') or {}).get('table') or []:
        k = ATTR.get(a.get('id'))
        if not k:
            continue
        raw = (a.get('raw') or {}).get('value')
        if k in ('temp', 'temp_air'):
            raw = raw & 0xFF if isinstance(raw, int) else raw     # у старших байтах — мін/макс
            if s['temp'] is None:
                s['temp'] = raw
            continue
        if k in ('wear_level', 'life_left', 'media_wear'):
            s['life'] = a.get('value')                # нормалізоване 100 → 0
            continue
        s[k] = raw
        if a.get('when_failed'):
            s.setdefault('failing', []).append(a.get('name'))
    nv = j.get('nvme_smart_health_information_log')
    if nv:
        s.update(temp=s['temp'] if s['temp'] is not None else nv.get('temperature'), hours=nv.get('power_on_hours', s['hours']),
                 cycles=nv.get('power_cycles', s['cycles']), life=100 - int(nv.get('percentage_used') or 0),
                 media_errors=nv.get('media_errors'), spare=nv.get('available_spare'), critical=nv.get('critical_warning'))
    return s


def smart_read(dev, wake=False):
    """Прочитати SMART. Повертає словник зі state: active | standby | none (недоступно) і причиною."""
    msgs, empty = '', None
    for extra in ([], ['-d', 'sat'], ['-d', 'sat,12']):     # sat,12 — для частини мостів ASMedia/JMicron
        cmd = ['smartctl', '-j', '-a'] + ([] if wake else ['-n', 'standby']) + extra + [dev]
        try:
            r = run(cmd, 60)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {'state': 'none', 'why': 'smartctl не запустився: %s' % e}
        try:
            j = json.loads(r.stdout or '{}')
        except ValueError:
            j = {}
        sc = j.get('smartctl') or {}
        ex = sc.get('exit_status', r.returncode)
        msgs = ' '.join(m.get('string', '') for m in sc.get('messages') or []).strip()
        if re.search(r'STANDBY|SLEEP', msgs, re.I):
            return {'state': 'standby'}
        if ex & 3 and not (j.get('smart_status') or j.get('ata_smart_attributes') or j.get('nvme_smart_health_information_log')):
            continue                     # не відкрився або не той тип — пробуємо як SAT (USB-адаптери)
        s = parse_smart(j)
        if s['passed'] is None and s['temp'] is None and s['hours'] is None:
            empty = {'state': 'none', 'why': msgs or 'SMART вимкнено або не підтримується', 'model': s['model']}
            continue                     # міст відповів, але без даних — пробуємо інший спосіб
        return s
    if empty:
        return empty
    return {'state': 'none', 'why': msgs or 'SMART недоступний (адаптер не передає дані диска)'}


def disk_io(kname):
    for line in read('/proc/diskstats').splitlines():
        p = line.split()
        if len(p) > 9 and p[2] == kname:
            return (p[5], p[9])          # прочитано й записано секторів
    return None


def sleep_key(d):
    return d['serial'] or d['dev']


def sleep_mode(sleep, d):
    v = sleep.get(sleep_key(d))
    return -1 if v is None else int(v)


def smartctl_set(dev, *sets):
    args = [x for v in sets for x in ('-s', v)]
    r = run(['smartctl'] + args + [dev], 30)
    if r.returncode & 3:
        r = run(['smartctl', '-d', 'sat'] + args + [dev], 30)
    return not r.returncode & 7         # 4 — диск не прийняв якусь із команд


def touch_disk(dev, size):
    """Прочитати 4 КБ з випадкового місця напряму з диска (повз кеш), щоб док бачив роботу."""
    buf = mmap.mmap(-1, 4096)           # вирівняний буфер для O_DIRECT
    fd = os.open(dev, os.O_RDONLY | getattr(os, 'O_DIRECT', 0))
    try:
        os.preadv(fd, [buf], random.randrange(0, max(1, size // 4096 - 1)) * 4096)
    finally:
        os.close(fd)
        buf.close()


def disk_care(now):
    """Раз на 20 с з keeper: SMART раз на 5 хв (не будячи), приспати бездіяльні HDD."""
    sleep = load_state().get('sleep') or {}
    disks = phys_disks()
    for k in set(TUNED) - {d['kname'] for d in disks}:      # диск зник — при поверненні налаштуємо знову
        TUNED.pop(k, None)
    for d in disks:
        dev, kname = d['dev'], d['kname']
        io = disk_io(kname)
        st = DISK_IO.setdefault(kname, [io, now, False])
        if io != st[0]:
            DISK_IO[kname] = st = [io, now, False]
            if (SMART.get(dev) or {}).get('state') == 'standby':
                SMART[dev]['state'] = 'active'
        cache = SMART.get(dev) or {}
        if not d['loop'] and now - cache.get('at', 0) > SMART_EVERY:
            got = smart_read(dev)
            if got.get('state') == 'standby' and cache.get('state') not in (None, 'none'):
                cache = dict(cache, state='standby', at=now)        # спить — лишаємо останні значення
            else:
                cache = dict(got, at=now)
                lc_note(dev, cache)
            SMART[dev] = cache
        mins = sleep_mode(sleep, d)
        if not d['rot'] or d['system'] or d['loop'] or mins < 0:
            TUNED.pop(kname, None)
            continue
        if (TUNED.get(kname) or (None,))[0] != d['serial']:
            ok = smartctl_set(dev, 'standby,off', 'apm,254')
            TUNED[kname] = (d['serial'], ok)
            print('gazda: диск %s — власний таймер сну %s' % ('/'.join(d['names']), 'вимкнено' if ok else 'вимкнути не вдалося (тримаю читанням)'), flush=True)
        if (mins == 0 or not st[2] and now - st[1] < mins * 60) and now - PINGED.get(kname, 0) >= KEEPALIVE_EVERY:
            PINGED[kname] = now
            try:
                touch_disk(dev, d['size'])
                TOUCHED[kname] = TOUCHED.get(kname, 0) + 8
                st[0] = disk_io(kname)            # своє читання за роботу не рахуємо
                if (SMART.get(dev) or {}).get('state') == 'standby':
                    SMART[dev]['state'] = 'active'
            except OSError as e:
                if KEEPER_SAID.get(dev) != str(e):
                    print('gazda: не вдалося торкнутись диска %s: %s' % (dev, e), flush=True)
                    KEEPER_SAID[dev] = str(e)
        if mins and not st[2] and now - st[1] >= mins * 60:
            r = run(['smartctl', '-s', 'standby,now', dev], 30)
            if r.returncode & 3:
                r = run(['smartctl', '-d', 'sat', '-s', 'standby,now', dev], 30)
            st[2] = True
            if not r.returncode & 3:
                SMART.setdefault(dev, {})['state'] = 'standby'
                print('gazda: диск %s заснув після %d хв без роботи' % ('/'.join(d['names']), mins), flush=True)


def do_disk_health(a):
    op = a.get('op') or 'status'
    disks = {d['dev']: d for d in phys_disks()}
    if op == 'refresh':                  # кнопка «Оновити»: читаємо зараз, навіть якщо диск спить
        dev = a.get('dev')
        if dev not in disks:
            raise Fail('Диск не знайдено')
        if disks[dev]['loop']:
            raise Fail('Це не фізичний диск — SMART тут немає')
        SMART[dev] = dict(smart_read(dev, wake=True), at=time.time())
        lc_note(dev, SMART[dev])
        DISK_IO[disks[dev]['kname']] = [disk_io(disks[dev]['kname']), time.time(), False]
    elif op == 'sleep':
        dev, mins = a.get('dev'), a.get('minutes')
        if dev not in disks:
            raise Fail('Диск не знайдено')
        if mins not in SLEEP_CHOICES:
            raise Fail('Невідомий час')
        if disks[dev]['system'] or not disks[dev]['rot']:
            raise Fail('Засинання — лише для жорстких дисків з даними')
        with LOCK:
            st = load_state()
            if mins < 0:
                st.setdefault('sleep', {}).pop(sleep_key(disks[dev]), None)
            else:
                st.setdefault('sleep', {})[sleep_key(disks[dev])] = mins
            save_state(st)
        if disks[dev]['kname'] in DISK_IO:
            DISK_IO[disks[dev]['kname']][2] = False
    elif op != 'status':
        raise Fail('Невідома дія')
    sleep = load_state().get('sleep') or {}
    now = time.time()
    out = []
    for d in disks.values():
        io = DISK_IO.get(d['kname'])
        sm = dict(SMART.get(d['dev']) or {})
        if d['loop']:
            sm = {'state': 'none', 'why': 'віртуальний диск (файл) — SMART немає'}
        elif lc_rate(d['dev']) is not None:
            sm['lc_rate'] = lc_rate(d['dev'])
        tuned = TUNED.get(d['kname'])
        out.append(dict(d, smart=sm, sleep=sleep_mode(sleep, d), tuned=tuned[1] if tuned else None,
                        idle=int(now - io[1]) if io else None, sleepable=d['rot'] and not d['system'] and not d['loop'],
                        usage={n: usage(os.path.join(DISKS, n)) for n in d['names'] if n != 'система'}))
    out.sort(key=lambda d: (not d['system'], d['names']))
    return {'disks': out, 'choices': list(SLEEP_CHOICES)}


KEEPER_SAID = {}


def do_health(a):
    """ТО: зведення, графіки, події, таблиця за період, пороги, експорт (core/health.py)."""
    import health
    if HEALTH is None:
        raise Fail('ТО ще запускається — спробуй за хвилину')
    op = a.get('op') or 'summary'
    if op == 'set_limits':
        with LOCK:
            st = load_state()
            if a.get('reset'):
                st.pop('health_limits', None)
            else:
                st['health_limits'] = dict(st.get('health_limits') or {}, **health.clean_limits(a.get('limits')))
            save_state(st)
        op = 'limits'
    try:
        return health.handle(HEALTH, dict(a, op=op), sys.modules[__name__])
    except ValueError as e:
        raise Fail(str(e))


# Режим продуктивності на час субтитрів ШІ: VidBox у режимі «максимальна швидкість» кладе файл з PID розпізнавання;
# поки цей процес живий — профіль Asus «performance» (якщо є), EPP процесора «performance» і вентилятори на 100 %
# (asus-nb-wmi: pwm1_enable 0 — на повну, 2 — авто); потім — як було. Попередні значення зберігаємо в стані gazda,
# щоб повернути їх і після перезапуску gazda посеред розпізнавання.
BOOST_FLAG = '/var/lib/hata/vidbox/whisper/boost'
BOOST = {'on': None}


def boost_targets():
    """[(файл, значення на час розпізнавання)] — лише те, що є на цьому ноутбуці."""
    out = []
    pp = '/sys/firmware/acpi/platform_profile'
    if os.path.exists(pp) and 'performance' in read(pp + '_choices').split():
        out.append((pp, 'performance'))
    out += [(p, 'performance') for p in sorted(glob.glob('/sys/devices/system/cpu/cpu[0-9]*/cpufreq/energy_performance_preference'))]
    for h in glob.glob('/sys/class/hwmon/hwmon*'):
        if read(h + '/name') == 'asus' and os.path.exists(h + '/pwm1_enable'):
            out.append((h + '/pwm1_enable', '0'))
    return out


def boost_write(p, v):
    try:
        with open(p, 'w') as f:
            f.write(v)
        return True
    except OSError:
        return False


def boost_care():
    want = False
    try:
        pid = int(read(BOOST_FLAG) or 0)
        want = pid > 0 and 'whisper_worker' in read('/proc/%d/cmdline' % pid)
    except ValueError:
        pass
    if want == BOOST['on']:
        return
    with LOCK:
        st = load_state()
        saved = st.get('boost_saved') or {}
        if want and not saved:
            done = []
            for p, v in boost_targets():
                old = read(p)
                if old and boost_write(p, v):
                    saved[p] = old
                    done.append('вентилятори 100 %' if p.endswith('pwm1_enable') else os.path.basename(p))
            st['boost_saved'] = saved
            save_state(st)
            print('gazda: субтитри ШІ — режим продуктивності (%s)' % ', '.join(sorted(set(done))), flush=True)
        elif not want and saved:
            for p, v in saved.items():
                boost_write(p, v)
            st.pop('boost_saved', None)
            save_state(st)
            print('gazda: субтитри ШІ — режим продуктивності вимкнено, усе як було', flush=True)
    BOOST['on'] = want


def keeper():
    """Фонова турбота, раз на 20 с:
    - диск з fstab з'явився пізніше за завантаження (USB, док без живлення) — підмонтувати;
    - енергозбереження Wi-Fi знову ввімкнулось (після перепідключення) — вимкнути: серверу воно лише ріже швидкість;
    - SMART дисків раз на 5 хв (не будячи сплячих) і сон бездіяльних HDD."""
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
            if shutil.which('smartctl'):
                disk_care(time.time())
            boost_care()
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


# ───────────────────────── постійна адреса вдома ─────────────────────────
# Кабельному підключенню — фіксована адреса (Wi-Fi лишається на DHCP як запасний).
# Файл 90-… читається останнім, тож перекриває dhcp4 з файлу інсталятора Ubuntu для того ж інтерфейсу.

STATIC_NETPLAN = '/etc/netplan/90-hata-static.yaml'


def ip_json(*args):
    try:
        return json.loads(run(['ip', '-j', *args], 10).stdout or '[]')
    except ValueError:
        return []


def static_status():
    t = read(STATIC_NETPLAN, '')
    m = re.search(r'^    (\S+):\n(?:.*\n)*?      addresses: \[([\d.]+)/(\d+)\]', t, re.M)
    return {'iface': m.group(1), 'ip': m.group(2)} if m else {}


def do_static_ip(a):
    op = a.get('op') or 'status'
    if op == 'status':
        return {'static': static_status()}
    if op == 'clear':
        with LOCK:
            if os.path.exists(STATIC_NETPLAN):
                os.remove(STATIC_NETPLAN)
            run(['netplan', 'apply'], 90)
        return {'static': {}}
    if op != 'set':
        raise Fail('Невідома дія')
    iface, want = str(a.get('iface') or ''), str(a.get('ip') or '')
    if not re.fullmatch(r'[\w.-]{1,15}', iface) or not os.path.exists('/sys/class/net/' + iface):
        raise Fail('Невідоме підключення')
    if os.path.isdir('/sys/class/net/%s/wireless' % iface):
        raise Fail('Постійну адресу ставимо кабелю; Wi-Fi лишається запасним на DHCP')
    cur = next((x for i in ip_json('-4', 'addr', 'show', 'dev', iface) for x in i.get('addr_info', [])), None)
    gw = next((r.get('gateway') for r in ip_json('route', 'show', 'default', 'dev', iface) if r.get('gateway')), None)
    if not cur or not gw:
        raise Fail('Кабель зараз без адреси від роутера — підключи його й спробуй ще раз')
    plen = int(cur['prefixlen'])
    try:
        import ipaddress
        net = ipaddress.ip_network('%s/%d' % (cur['local'], plen), strict=False)
        addr = ipaddress.ip_address(want)
    except ValueError:
        raise Fail('Незрозуміла адреса: %s' % want)
    if addr not in net or addr in (net.network_address, net.broadcast_address) or str(addr) == gw:
        raise Fail('Адреса має бути в домашній мережі %s і не збігатися з роутером' % net)
    if str(addr) != cur['local']:
        # зайнята? телефони часто не відповідають на ping, тож дивимось ще й таблицю сусідів (ARP)
        pong = run(['ping', '-c', '2', '-W', '1', str(addr)], 10).returncode == 0
        neigh = 'lladdr' in run(['ip', 'neigh', 'show', str(addr)], 5).stdout
        if pong or neigh:
            raise Fail('%s уже зайнята іншим пристроєм — вибери іншу' % addr)
    text = ('# Записано Hata (панель → мережа → постійна адреса). Змінюй через панель.\nnetwork:\n  version: 2\n  ethernets:\n'
            f'    {iface}:\n      dhcp4: false\n      optional: true\n      addresses: [{addr}/{plen}]\n'
            f'      routes:\n        - to: default\n          via: {gw}\n          metric: 1024\n'
            f'      nameservers:\n        addresses: [{gw}, 1.1.1.1]\n')
    with LOCK:
        fd = os.open(STATIC_NETPLAN + '.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        os.replace(STATIC_NETPLAN + '.tmp', STATIC_NETPLAN)
        r = run(['netplan', 'apply'], 90)
        ok = r.returncode == 0
        for _ in range(15):          # чи працює: роутер відповідає з нової адреси
            if ok and run(['ping', '-c', '1', '-W', '1', '-I', str(addr), gw], 5).returncode == 0:
                return {'static': static_status()}
            time.sleep(1)
        os.remove(STATIC_NETPLAN)    # не вийшло — повертаємо як було, щоб не лишитись без мережі
        run(['netplan', 'apply'], 90)
    raise Fail('З адресою %s роутер не відповідає — повернув як було. %s' % (addr, (r.stderr or '').strip()[-200:]))


# ───────────────────────── спільні папки (Samba) ─────────────────────────
# Кожен диск Хати — окрема спільна папка: \\hata\<диск> у Windows, smb://hata.local у Finder.
# Вхід — користувач hata з паролем панелі (той самий, що на всьому). Лише вдома й через Tailscale.

SMB_CONF = '/etc/samba/smb.conf'
AVAHI_SMB = '/etc/avahi/services/hata-smb.service'


def hata_disks():
    return sorted({os.path.basename(l.split()[1]) for l in read(FSTAB).splitlines()
                   if l.endswith(FSTAB_MARK) and len(l.split()) > 1})


def write_smb_conf():
    host = socket.gethostname()
    shares = ''.join(f'''
[{n}]
   comment = Диск {n} (Хата)
   path = {DISKS}/{n}
   valid users = hata
   force user = hata
   force group = hata
   read only = no
   browseable = yes
   create mask = 0664
   directory mask = 0775
''' for n in hata_disks())
    text = f'''# Записано Hata (панель → файли → спільні папки). Змінюй через панель — ручні зміни буде перезаписано.
[global]
   workgroup = WORKGROUP
   server string = Хата
   netbios name = {host.upper()[:15]}
   server role = standalone server
   map to guest = never
   server min protocol = SMB2
   hosts allow = 127. 10. 172.16.0.0/12 192.168. 100.64.0.0/10 fd7a:115c:a1e0::/48
   hosts deny = 0.0.0.0/0
   load printers = no
   printing = bsd
   printcap name = /dev/null
   disable spoolss = yes
   log file = /var/log/samba/log.%m
   max log size = 1000
   veto files = /._*/.DS_Store/Thumbs.db/
   delete veto files = yes
{shares}'''
    if os.path.exists(SMB_CONF) and not os.path.exists(SMB_CONF + '.orig') and 'Записано Hata' not in read(SMB_CONF):
        shutil.copy2(SMB_CONF, SMB_CONF + '.orig')
    with open(SMB_CONF + '.tmp', 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(SMB_CONF + '.tmp', SMB_CONF)
    if os.path.isdir('/etc/avahi/services'):     # щоб Хата з'являлась у бічній панелі Finder
        with open(AVAHI_SMB, 'w') as f:
            f.write('<?xml version="1.0" standalone="no"?>\n<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
                    '<service-group><name replace-wildcards="yes">%h</name>'
                    '<service><type>_smb._tcp</type><port>445</port></service>'
                    '<service><type>_device-info._tcp</type><port>0</port><txt-record>model=Xserve</txt-record></service>'
                    '</service-group>\n')


def share_on():
    return bool(load_state().get('share'))


def share_reload():
    """Диски змінились — оновити список спільних папок (якщо вони ввімкнені)."""
    if share_on() and shutil.which('smbd'):
        write_smb_conf()
        run(['systemctl', 'reload-or-restart', 'smbd'], 60)


def do_share(a):
    op = a.get('op') or 'status'
    if op == 'status':
        on = share_on()
        active = run(['systemctl', 'is-active', 'smbd'], 10).stdout.strip() == 'active' if shutil.which('smbd') else False
        return {'enabled': on, 'active': active, 'installed': bool(shutil.which('smbd')), 'user': 'hata',
                'shares': [{'name': n, 'path': f'{DISKS}/{n}'} for n in hata_disks()] if on else []}
    if op == 'enable':
        pw = str(a.get('password') or '')
        if len(pw) < 6:
            raise Fail('Потрібен пароль панелі')
        ensure_pkgs('samba')
        try:
            ensure_pkgs('wsdd')          # щоб Хата сама з'являлась у «Мережі» Windows (є не в кожній версії Ubuntu)
        except Fail:
            pass
        with LOCK:
            write_smb_conf()
            r = subprocess.run(['smbpasswd', '-a', '-s', 'hata'], input=f'{pw}\n{pw}\n', text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            if r.returncode:
                raise Fail('Не вдалося задати пароль Samba: ' + (r.stderr or r.stdout).strip()[-200:])
            run(['smbpasswd', '-e', 'hata'], 30)
            for svc in ('smbd', 'nmbd', 'wsdd'):
                if run(['systemctl', 'cat', svc], 10).returncode == 0:
                    run(['systemctl', 'enable', '--now', svc], 60)
            run(['systemctl', 'restart', 'smbd'], 60)
            run(['systemctl', 'try-restart', 'avahi-daemon'], 30)
            if shutil.which('ufw') and 'Status: active' in run(['ufw', 'status'], 10).stdout:
                run(['ufw', 'allow', 'Samba'], 30)
            st = load_state()
            st['share'] = True
            save_state(st)
        return do_share({'op': 'status'})
    if op == 'disable':
        with LOCK:
            for svc in ('wsdd', 'nmbd', 'smbd'):
                run(['systemctl', 'disable', '--now', svc], 60)
            if os.path.exists(AVAHI_SMB):
                os.remove(AVAHI_SMB)
                run(['systemctl', 'try-restart', 'avahi-daemon'], 30)
            st = load_state()
            st['share'] = False
            save_state(st)
        return do_share({'op': 'status'})
    raise Fail('Невідома дія зі спільними папками')


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
    'timezone': do_timezone,
    'static_ip': do_static_ip,
    'share': do_share,
    'disk_health': do_disk_health,
    'health': do_health,
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
        try:
            self.wfile.write((json.dumps(res, ensure_ascii=False) + '\n').encode())
        except (BrokenPipeError, ConnectionResetError):
            pass    # панель не дочекалась (довга дія) — результат уже застосовано, просто нема кому сказати


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def sync_units():
    """Оновлення Hata міняє лише код у /opt/hata/src, а служби systemd лежать копіями в /etc — звіряємо при старті gazda
    (а він перезапускається після кожного оновлення) і перезапускаємо ті служби, чиї файли змінились."""
    src_dir = os.path.join(SRC, 'core', 'systemd')
    changed = []
    for name in sorted(os.listdir(src_dir)) if os.path.isdir(src_dir) else []:
        if not name.endswith('.service'):
            continue
        new, dst = read(os.path.join(src_dir, name)), os.path.join('/etc/systemd/system', name)
        if new and new != read(dst):
            with open(dst + '.tmp', 'w', encoding='utf-8') as f:
                f.write(new)
            os.chmod(dst + '.tmp', 0o644)
            os.replace(dst + '.tmp', dst)
            changed.append(name)
    if changed:
        run(['systemctl', 'daemon-reload'], 60)
        for name in changed:
            if name != 'gazda.service':          # себе не перезапускаємо: нове застосується з наступним стартом
                run(['systemctl', 'try-restart', name], 60)
        print('gazda: оновив служби', ', '.join(changed), flush=True)


def serve():
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    if os.path.exists(SOCK):
        os.remove(SOCK)
    try:
        sync_units()
    except Exception as e:
        print('gazda: не вдалося звірити служби:', repr(e), flush=True)
    st = load_state()
    if st.get('battery_limit'):
        apply_battery_limit(st['battery_limit'])
    threading.Thread(target=keeper, daemon=True).start()
    global HEALTH
    try:
        import health
        HEALTH = health.start(sys.modules[__name__])

        signal.signal(signal.SIGTERM, lambda *_: quit_gazda())     # вимкнення/перезапуск: дописати буфер ТО
    except Exception as e:     # без ТО gazda однаково має працювати
        print('gazda: ТО не запустилось:', repr(e), flush=True)
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
