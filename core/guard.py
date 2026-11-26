"""Сторож дисків Хати: запобігти відвалам USB-дисків і оживити диск, якщо він усе ж відвалився.

Працює всередині gazda (root), викликається з keeper раз на 20 с. g — модуль gazda.

Запобігання:
  - правило udev: USB-пристрої не присипляти (autosuspend рве зв'язок з дешевими мостами SATA↔USB),
    USB-дискам — тайм-аут команд 90 с замість 30 (повільний міст під час розкрутки не вважається мертвим);
    те саме застосовуємо й одразу, без перепідключення;
  - поки VidBox робить субтитри ШІ, диски з бібліотекою не засинають (менше розкручувань і пускових струмів);
  - таймер паркування головок WD (idle3) — подивитись і змінити кнопкою на картці диска.

Відновлення:
  - змонтований диск, що перестав відповідати (пристрій зник або «offline»), — відмонтувати, щоб не висіли процеси;
  - диск з fstab зник — до трьох спроб оживити його міст: перепідключити програмно (unbind/bind) або
    вимкнути-ввімкнути живлення USB-порту; далі змонтує keeper, а VidBox сам помітить диск і продовжить чергу;
  - не вийшло — подія «перепідключи диск або перевір живлення доку». Хаби й пристрої з мережею не чіпаємо ніколи.
"""
import glob
import json
import os
import re
import time

UDEV_RULES = '/etc/udev/rules.d/90-hata-usb-disks.rules'
RULES = '''# Хата (gazda): USB-диски й мости не присипляти й дати їм більше часу на відповідь.
# Файл перезаписується gazda при старті — правити в core/guard.py.
ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", TEST=="power/control", ATTR{power/control}="on"
ACTION=="add|change", SUBSYSTEM=="block", ENV{DEVTYPE}=="disk", ENV{ID_BUS}=="usb", KERNEL=="sd*", RUN+="/bin/sh -c 'echo 90 > /sys%p/device/timeout'"
'''
SCSI_TIMEOUT = 90
TRIES = (60, 180, 420)          # через скільки секунд після зникнення — спроби оживити
VB_DATA = '/var/lib/hata/vidbox'
ACTIVE = ('audio', 'model', 'recog', 'context', 'translate')

G = {'cared': {}, 'gone': {}, 'said': {}, 'ai': None, 'ai_disks': set(), 'ai_at': 0}


def fread(p, default=''):
    try:
        with open(p) as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return default


def fwrite(p, v):
    try:
        with open(p, 'w') as f:
            f.write(str(v))
        return True
    except OSError:
        return False


def event(g, kind, subj, lvl, text):
    print('gazda сторож: ' + text, flush=True)
    try:
        if getattr(g, 'HEALTH', None) is not None:
            g.HEALTH.event(time.time(), kind, subj, lvl, text)
    except Exception:
        pass


# ───────────────────────── запобігання ─────────────────────────

def ensure_udev(g):
    """Записати правило udev, якщо його немає чи воно старе (оновлення Хати інсталятор не запускає)."""
    if fread(UDEV_RULES) == RULES.strip():
        return False
    try:
        with open(UDEV_RULES + '.tmp', 'w') as f:
            f.write(RULES)
        os.replace(UDEV_RULES + '.tmp', UDEV_RULES)
    except OSError as e:
        print('gazda сторож: не вдалося записати правило udev:', e, flush=True)
        return False
    g.run(['udevadm', 'control', '--reload'], 30)
    print('gazda сторож: правило udev для USB-дисків записано', flush=True)
    return True


def usb_dev_path(kname):
    """Тека sysfs USB-пристрою (мосту), через який підключено диск, або None."""
    p = os.path.realpath('/sys/block/%s/device' % kname)
    while p and p != '/' and '/usb' in p:
        if os.path.exists(p + '/idVendor') and os.path.exists(p + '/speed'):
            return p
        p = os.path.dirname(p)
    return None


def usb_care(g, disks):
    """Для кожного нового USB-диска: тайм-аут 90 с і без автосну для мосту й хабів над ним."""
    seen = set()
    for d in disks:
        if not d.get('usb') or d.get('loop'):
            continue
        k = d['kname']
        seen.add(k)
        if G['cared'].get(k) == d.get('serial'):
            continue
        done = []
        tp = '/sys/block/%s/device/timeout' % k
        try:
            if int(fread(tp, '0') or 0) < SCSI_TIMEOUT and fwrite(tp, SCSI_TIMEOUT):
                done.append('тайм-аут %d с' % SCSI_TIMEOUT)
        except ValueError:
            pass
        p = usb_dev_path(k)
        n = 0
        while p and os.path.exists(p + '/idVendor'):
            if fread(p + '/power/control') == 'auto' and fwrite(p + '/power/control', 'on'):
                n += 1
            p = os.path.dirname(p)
        if n:
            done.append('без USB-автосну')
        G['cared'][k] = d.get('serial')
        if done:
            print('gazda сторож: диск %s — %s' % ('/'.join(d['names']) or k, ', '.join(done)), flush=True)
    for k in set(G['cared']) - seen:
        G['cared'].pop(k, None)


def vb_library_disks():
    """Назви дисків (/srv/disks/<назва>), на яких лежить бібліотека VidBox."""
    try:
        with open(os.path.join(VB_DATA, 'config.json'), encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return set()
    out = set()
    for p in list(cfg.get('folders') or []) + [cfg.get('anime_folder') or '']:
        m = re.match(r'^/srv/disks/([^/]+)', str(p or ''))
        if m:
            out.add(m.group(1))
    return out


def ai_keep(g, now):
    """Які диски тримати розкрученими через субтитри ШІ (кеш на 30 с). Порожньо, якщо вимкнено або черга стоїть."""
    if now - G['ai_at'] < 30:
        return G['ai_disks']
    G['ai_at'] = now
    on = (g.load_state().get('ai_awake', True) is not False)
    busy = False
    if on:
        try:
            with open(os.path.join(VB_DATA, 'aisubs', 'queue.json'), encoding='utf-8') as f:
                q = json.load(f)
            busy = any(isinstance(x, dict) and (x.get('state') in ACTIVE or x.get('state') == 'queued' and (x.get('wait') or 0) <= now)
                       for x in q if isinstance(q, list))
        except (OSError, ValueError):
            busy = False
    disks = vb_library_disks() if busy else set()
    if bool(disks) != bool(G['ai_disks']):
        print('gazda сторож: %s' % ('субтитри ШІ в роботі — диски %s не засинатимуть' % ', '.join(sorted(disks)) if disks
                                    else 'черга субтитрів ШІ порожня — диски знову засинають за своїм налаштуванням'), flush=True)
    G['ai'] = busy
    G['ai_disks'] = disks
    return disks


# ───────────────────────── WD idle3 ─────────────────────────

def idle3_text(v):
    if v is None:
        return 'невідомо'
    if v == 0:
        return 'вимкнено'
    s = v / 10 if v <= 128 else (v - 128) * 30
    return '%g с' % s if s < 90 else '%g хв' % (s / 60)


def idle3(g, dev, value=None):
    """Прочитати або змінити таймер паркування головок WD. Спершу idle3ctl (лише прямий SATA), а через USB-мости —
    hdparm -J: він говорить з диском через SAT, як і smartctl."""
    g.ensure_pkgs('idle3-tools', 'hdparm')
    res = idle3_ctl(g, dev, value)
    if res is None:
        res = idle3_hdparm(g, dev, value)
    v = res
    return {'idle3': v, 'idle3Text': idle3_text(v), 'changed': value is not None,
            'note': 'Нове значення діє після повного вимкнення диска: вимкни док з розетки на 10 с (перезавантаження Хати не досить).' if value is not None else ''}


def idle3_ctl(g, dev, value):
    """idle3ctl: None — не вміє через цей міст (HDIO), тоді пробуємо hdparm."""
    if value is not None:
        r = g.run(['idle3ctl', '-d', dev] if value == 'off' else ['idle3ctl', '-s', str(int(value)), dev], 60)
        if r.returncode:
            return None if re.search(r'HDIO|Invalid argument|Inappropriate ioctl', r.stderr + r.stdout) else fail(g, 'Диск не прийняв зміну', r)
    r = g.run(['idle3ctl', '-g', dev], 60)
    out = (r.stdout + r.stderr).strip()
    if r.returncode:
        return None if re.search(r'HDIO|Invalid argument|Inappropriate ioctl', out) else fail(g, 'Не вдалося прочитати таймер', r)
    if re.search(r'disabled', out, re.I):
        return 0
    m = re.search(r'set to (\d+)', out)
    return int(m.group(1)) if m else None


def idle3_hdparm(g, dev, value):
    if value is not None:
        secs = 0 if value == 'off' else (int(value) / 10 if int(value) <= 128 else (int(value) - 128) * 30)
        # hdparm вимагає цей прапорець для всіх команд, специфічних для виробника; сама дія — та сама, що в idle3ctl
        r = g.run(['hdparm', '-J', '%g' % secs, '--please-destroy-my-drive', dev], 60)
        if r.returncode:
            fail(g, 'Диск не прийняв зміну', r)
    r = g.run(['hdparm', '-J', dev], 60)
    out = (r.stdout + r.stderr).strip()
    m = re.search(r'wdidle3\s*=\s*(\S+)\s*(\w*)', out)
    if r.returncode or not m:
        fail(g, 'Не вдалося прочитати таймер', r)
    if m.group(1).lower().startswith(('disabled', 'off')):
        return 0
    try:
        n = float(m.group(1))
    except ValueError:
        fail(g, 'Незрозуміла відповідь диска', r)
    secs = n * 60 if m.group(2).lower().startswith('min') else n
    return int(round(secs * 10)) if secs <= 12.8 else 128 + int(round(secs / 30))


def fail(g, what, r):
    raise g.Fail('%s: %s (через деякі USB-мости idle3 недоступний)' % (what, ((r.stderr or '') + (r.stdout or '')).strip()[-200:]))


# ───────────────────────── відновлення ─────────────────────────

def mounts():
    out = {}
    for line in fread('/proc/mounts').splitlines():
        p = line.split()
        if len(p) > 2:
            out[p[1].replace('\\040', ' ')] = p[0]
    return out


def base_kname(part):
    """sdb1 → sdb (через sysfs); None, якщо пристрою вже немає."""
    p = '/sys/class/block/%s' % part
    if not os.path.exists(p):
        return None
    if os.path.exists(p + '/partition'):
        return os.path.basename(os.path.dirname(os.path.realpath(p)))
    return part


def safe_to_reset(path, ours):
    """Не чіпаємо хаби, пристрої з мережею (USB-Ethernet у доці!) і мости, на яких висять інші змонтовані диски."""
    if fread(path + '/bDeviceClass') == '09':
        return False
    mounted = {os.path.basename(s) for s in mounts().values() if s.startswith('/dev/')}
    for root, dirs, _ in os.walk(path):
        if 'net' in dirs:
            return False
        if os.path.basename(root) == 'block':
            for b in dirs:
                if b not in ours and any(m == b or re.fullmatch(re.escape(b) + r'\d+', m) for m in mounted):
                    return False
        if root.count('/') - path.count('/') > 8:
            dirs[:] = []
    return True


def port_disable_path(port):
    """Файл «вимкнути порт» для USB-порту '1-2' або '1-2.3'."""
    if '.' in port:
        parent, n = port.rsplit('.', 1)
        return '/sys/bus/usb/devices/%s:1.0/%s-port%s/disable' % (parent, parent, n)
    bus, n = port.split('-', 1)
    return '/sys/bus/usb/devices/%s-0:1.0/usb%s-port%s/disable' % (bus, bus, n)


def revive(g, name, info, attempt):
    """Одна спроба оживити міст диска. Повертає, що зроблено (для журналу), або ''."""
    port = info.get('port')
    if not port or not re.fullmatch(r'\d+-[\d.]+', port):
        return ''
    path = '/sys/bus/usb/devices/' + port
    if os.path.exists(path + '/idVendor'):
        vp = '%s:%s' % (fread(path + '/idVendor'), fread(path + '/idProduct'))
        if info.get('vp') and vp != info['vp']:
            return ''                       # у порту вже інший пристрій — не наш міст
        if not safe_to_reset(path, info.get('knames') or []):
            return ''
        if attempt < 2:
            if fwrite('/sys/bus/usb/drivers/usb/unbind', port):
                time.sleep(3)
                fwrite('/sys/bus/usb/drivers/usb/bind', port)
                return 'перепідключив міст програмно'
    dp = port_disable_path(port)
    if os.path.exists(dp) and (not os.path.exists(path + '/idVendor') or safe_to_reset(path, info.get('knames') or [])):
        if fwrite(dp, '1'):
            time.sleep(4)
            fwrite(dp, '0')
            return 'вимкнув і ввімкнув живлення USB-порту %s' % port
    return ''


def remember(g, disks):
    """Для змонтованих USB-дисків запам'ятати їхній міст (порт, vendor:product) — знадобиться, коли диск зникне."""
    st = g.load_state()
    known = st.get('guard_usb') or {}
    new = dict(known)
    for d in disks:
        if not d.get('usb') or d.get('loop'):
            continue
        p = usb_dev_path(d['kname'])
        if not p:
            continue
        info = {'port': os.path.basename(p), 'vp': '%s:%s' % (fread(p + '/idVendor'), fread(p + '/idProduct')),
                'name': (fread(p + '/manufacturer') + ' ' + fread(p + '/product')).strip(), 'knames': [d['kname']]}
        for n in d['names']:
            if n != 'система':
                new[n] = info
    if new != known:
        with g.LOCK:
            st = g.load_state()
            st['guard_usb'] = new
            g.save_state(st)
    return new


def watch(g, now, disks):
    """Раз на 20 с: зламані монтування, зниклі диски, спроби оживити, повернення."""
    known = remember(g, disks)
    mt = mounts()
    for line in fread(g.FSTAB).splitlines():
        if not line.endswith(g.FSTAB_MARK) or not line.startswith('UUID='):
            continue
        uuid, point = line.split()[0][5:], line.split()[1]
        name = os.path.basename(point)
        src = mt.get(point)
        if src and src.startswith('/dev/'):
            part = os.path.basename(os.path.realpath(src))
            k = base_kname(part)
            broken = k is None or fread('/sys/block/%s/device/state' % k) == 'offline'
            if broken:
                r = g.run(['umount', '-l', point], 30)
                event(g, 'guard', name, 'red', 'Диск %s перестав відповідати — відмонтував його%s; пробую оживити' % (
                    name, '' if r.returncode == 0 else ' (не вдалося: %s)' % r.stderr.strip()[-120:]))
                G['gone'][name] = {'at': now, 'tries': 0, 'said': False}
                continue
            if name in G['gone']:
                info = G['gone'].pop(name)
                event(g, 'guard', name, 'acc', 'Диск %s знову на місці — не було %s%s' % (
                    name, dur(now - info['at']), ', допомогла спроба %d' % info['tries'] if info['tries'] else ''))
            continue
        if os.path.ismount(point):
            continue
        gone = G['gone'].setdefault(name, {'at': now, 'tries': 0, 'said': False})
        info = known.get(name)
        if not info:
            continue                        # не USB чи міст невідомий — оживляти нічого
        if gone['tries'] < len(TRIES) and now - gone['at'] >= TRIES[gone['tries']]:
            gone['tries'] += 1
            did = revive(g, name, info, gone['tries'] - 1)
            if did:
                event(g, 'guard', name, 'yel', 'Диск %s не повертається — %s (спроба %d з %d, міст %s)' % (
                    name, did, gone['tries'], len(TRIES), info.get('name') or info.get('port')))
        elif gone['tries'] >= len(TRIES) and not gone['said'] and now - gone['at'] >= TRIES[-1] + 120:
            gone['said'] = True
            event(g, 'guard', name, 'red', 'Диск %s не повернувся після %d спроб. Перепідключи кабель диска або перевір живлення доку '
                  '(док — лише від свого блока живлення). VidBox чекає на диск і продовжить сам.' % (name, len(TRIES)))


def dur(s):
    s = int(s)
    return '%d с' % s if s < 90 else '%d хв' % round(s / 60) if s < 5400 else '%d год %d хв' % (s // 3600, s % 3600 // 60)


def care(g, now):
    """Усе разом — з keeper."""
    disks = g.phys_disks()
    usb_care(g, disks)
    watch(g, now, disks)
    return disks
