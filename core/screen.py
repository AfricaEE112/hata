#!/usr/bin/env python3
"""Екран ноутбука (tty1): замість логіна — статус Hata і QR-код адреси панелі.

До налаштування: «Хата майже готова» + QR для майстра. Після: стан сервера.
Нічого не натискаємо — тільки дивимось. Оновлюється кожні 10 секунд.
Кольори — з тієї ж схеми, що вибрана в панелі (палітра консолі переналаштовується).
"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time

CFG = '/var/lib/hata/hata.json'
# Кольори консолі: жирний = яскравий варіант, тож 1;3x бере палітру 8–15, яку ми задаємо зі схеми.
C = {'acc': '\033[1;36m', 'dim': '\033[1;30m', 'ok': '\033[1;32m', 'bad': '\033[1;31m', 'yel': '\033[1;33m',
     'vio': '\033[1;35m', 'b': '\033[1;37m', 'r': '\033[0m'}
# фон, текст, приглушений, акцент, жовтий, червоний, бузковий — ті самі, що в hata.css
SCHEMES = {
    'чай': ('191713', 'ece4d2', 'a39a86', '7cc6b1', 'e3c16f', 'e2785c', 'c79bd8'),
    'ніч': ('1e1e2e', 'cdd6f4', 'a6adc8', '89b4fa', 'f9e2af', 'f38ba8', 'cba6f7'),
    'lain': ('1c1e25', 'dfe3ee', '9aa1b4', 'b4c3f0', 'd9dce6', 'e8a0b4', '9fb0d9'),
    'ягода': ('2a1022', 'f6dcec', 'c99bb8', 'f4a6d7', 'f3c9a0', 'ff7aa8', 'c9a4f5'),
    'nothing': ('000000', 'f2f2f2', 'a3a3a3', 'f2f2f2', 'bdbdbd', 'e8352f', 'd0d0d0'),
    'папір': ('e9e1cf', '2a261f', '655b4b', '2f7d6d', '946a0c', 'bb4a2a', '7a5797'),
}
# Точкові цифри 5×7, як годинник у панелі.
FONT = {'0': '01110100011001110101110011000101110', '1': '00100011000010000100001000010001110',
        '2': '01110100010000100010001000100011111', '3': '11110000010000101110000010000111110',
        '4': '00010001100101010010111110001000010', '5': '11111100001111000001000011000101110',
        '6': '00110010001000011110100011000101110', '7': '11111000010001000100010000100001000',
        '8': '01110100011000101110100011000101110', '9': '01110100011000101111000010001001100', ':': '0010100'}


def gazda(req):
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(20)
        s.connect('/run/hata/gazda.sock')
        s.sendall((json.dumps(req) + '\n').encode())
        data = b''
        while not data.endswith(b'\n'):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        s.close()
        return json.loads(data or b'{}')
    except (OSError, ValueError):
        return {}


def ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        a = s.getsockname()[0]
        s.close()
        return a
    except OSError:
        return ''


def term():
    try:
        t = os.get_terminal_size(1)
        return t.columns, t.lines
    except OSError:
        return 80, 25


def rows():
    return term()[1]


def qr(text, compact=False):
    """Звичайний QR — з пробілів із кольоровим фоном (будь-який шрифт); компактний — з півблоків, удвічі нижчий."""
    try:
        return subprocess.run(['qrencode', '-t', 'ANSIUTF8' if compact else 'ANSI', '-m', '1' if compact else '2', text],
                              stdout=subprocess.PIPE, timeout=10, text=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def size(b):
    for u in ('Б', 'КБ', 'МБ', 'ГБ', 'ТБ'):
        if b < 1024 or u == 'ТБ':
            return ('%.0f' if b >= 100 or u in ('Б', 'КБ', 'МБ') else '%.1f') % b + ' ' + u
        b /= 1024


def conf():
    try:
        with open(CFG, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def palette(name):
    """Escape-послідовності Linux-консолі (ESC ] P n rrggbb), що перефарбовують 16 кольорів під схему."""
    bg, fg, dim, acc, yel, red, vio = SCHEMES.get(name) or SCHEMES['чай']
    cols = [bg, red, acc, yel, acc, vio, acc, fg, dim, red, acc, yel, acc, vio, acc, fg]
    return ''.join('\033]P%x%s' % (i, c) for i, c in enumerate(cols))


# ───────────────────────── малювання ─────────────────────────
# Лише символи, які точно є в консольному шрифті Terminus (Uni2 = латиниця, кирилиця, псевдографіка CP437):
# ┌─┐│└┘ рамки, ▌ сегменти смужок, ■ і · точки годинника.

ANSI = re.compile(r'\033\[[0-9;]*m')
DAYS = ('ПОНЕДІЛОК', 'ВІВТОРОК', 'СЕРЕДА', 'ЧЕТВЕР', "П'ЯТНИЦЯ", 'СУБОТА', 'НЕДІЛЯ')
MONTHS = ('січня', 'лютого', 'березня', 'квітня', 'травня', 'червня', 'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня')


def vis(t):
    return len(ANSI.sub('', t))


def pad(t, w):
    return t + ' ' * max(0, w - vis(t))


def col(name, t):
    return C[name] + t + C['r']


def clock():
    """Точковий годинник 5×7, як у панелі: ■ — світиться, · — ні; двокрапка блимає."""
    t = time.strftime('%H') + (':' if int(time.time()) % 20 < 10 else ' ') + time.strftime('%M')
    lines = []
    for r in range(7):
        parts = []
        for ch in t:
            bits = FONT.get(ch, '0000000')
            w = len(bits) // 7
            parts.append(''.join(col('b', '■ ') if b == '1' else col('dim', '· ') for b in bits[r * w:(r + 1) * w]))
        lines.append('  '.join(parts))
    return lines


def segs(pct, n):
    """Сегментована смужка: до 60% — акцент, до 85% — жовтий, далі — червоний."""
    out = ''
    for i in range(n):
        f = (i + .5) / n
        out += col('dim', '▌') if f > pct / 100 else col('ok' if f < .6 else 'yel' if f < .85 else 'bad', '▌')
    return out


def box(title, color, rows_, w):
    """Рамка з назвою в лінії, як у панелі: ┌─ диски ──────┐"""
    head = col('dim', '┌─ ') + col(color, title) + col('dim', ' ' + '─' * max(1, w - len(title) - 5) + '┐')
    body = [col('dim', '│ ') + pad(r, w - 4)[:10000] + col('dim', ' │') for r in rows_]
    return [head] + body + [col('dim', '└' + '─' * (w - 2) + '┘')]


def meter(label, pct, value, w, lw=6):
    """Рядок «назва ▌▌▌▌▌▌▌▌    значення» рівно на w символів; значення вирівняні праворуч."""
    vw = 17
    n = max(8, w - lw - vw - 1)
    return pad(col('dim', label), lw) + segs(pct, n) + ' ' * (1 + vw - vis(value)) + value


def net_rows():
    out = []
    try:
        addrs = {i['ifname']: [a['local'] for a in i.get('addr_info', [])]
                 for i in json.loads(subprocess.run(['ip', '-j', '-4', 'addr'], stdout=subprocess.PIPE, text=True, timeout=5).stdout or '[]')}
        route = (json.loads(subprocess.run(['ip', '-j', 'route', 'get', '1.1.1.1'], stdout=subprocess.PIPE, text=True,
                                           timeout=5).stdout or '[{}]') or [{}])[0].get('dev', '')
    except (OSError, ValueError, subprocess.SubprocessError):
        return out
    for n, ips in sorted(addrs.items()):
        if n == 'lo' or not ips or n.startswith(('docker', 'veth', 'br-', 'virbr')):
            continue
        kind = 'wi-fi' if os.path.isdir('/sys/class/net/%s/wireless' % n) else 'tailscale' if n.startswith('tailscale') else 'кабель'
        out.append('%s %s %s%s' % (col('ok', '●'), pad(kind, 9), ips[0], '  ' + col('acc', 'інтернет') if n == route else ''))
    return out


def center(lines, W, H):
    width = max([vis(l) for l in lines] or [0])
    left = ' ' * max(0, (W - width) // 2)
    top = max(0, (H - len(lines)) // 2)
    return '\n' * top + '\n'.join(left + l for l in lines)


def room_temp():
    """Остання температура від плати RoomMonitor (розділ «Будинок»), якщо свіжа."""
    try:
        import sqlite3
        con = sqlite3.connect('file:/var/lib/hata/house.db?mode=ro', uri=True, timeout=1)
        r = con.execute("SELECT value FROM readings WHERE key='temp.room' AND ts>? ORDER BY ts DESC LIMIT 1",
                        (int(time.time()) - 600,)).fetchone()
        con.close()
        return r[0] if r else None
    except Exception:
        return None


def frame():
    time.tzset()                     # часовий пояс могли щойно змінити з панелі
    W, H = term()
    host = socket.gethostname()
    addr = ip()
    url = 'http://%s/' % (addr or host + '.local')
    who = col('acc', 'хата') + col('dim', '@') + col('b', host) + col('acc', '▌')
    if not conf().get('setup_done'):
        small = H < 42
        head = [] if small else clock() + ['']
        head += [who, '', col('b', 'Хата майже готова.'), 'Відскануй код телефоном або відкрий у браузері:', '',
                 col('acc', url) + col('dim', '   або  http://%s.local/' % host), '']
        q = qr(url, compact=small).rstrip('\n').split('\n')
        return center(head + q, W, H)

    st = gazda({'do': 'status'})
    ts = gazda({'do': 'tailscale', 'op': 'status'})
    now = time.localtime()
    up = st.get('uptime', 0)
    left = clock() + ['', ' '.join(DAYS[now.tm_wday]), col('dim', '%d %s %d' % (now.tm_mday, MONTHS[now.tm_mon - 1], now.tm_year)),
                      '', who, '',
                      pad(col('yel', 'панель'), 11) + col('acc', url),
                      pad(col('yel', 'vidbox'), 11) + 'http://%s:%s/' % (addr or host + '.local', (st.get('vidbox') or {}).get('port', 8800))]
    if ts.get('state') == 'Running':
        left.append(pad(col('yel', 'tailscale'), 11) + ts.get('name', ''))
    rt = room_temp()
    if rt is not None:
        left.append(pad(col('yel', 'кімната'), 11) + ('%.1f °C' % rt).replace('.', ','))
    lw = max(vis(l) for l in left)

    rw = max(52, min(68, W - lw - 12))
    iw = rw - 4
    m = st.get('mem') or {}
    used = m.get('total', 0) - m.get('avail', 0)
    try:
        load = float(open('/proc/loadavg').read().split()[0])
    except (OSError, ValueError):
        load = 0
    cpu = min(100, round(100 * load / max(1, st.get('cpus') or 1)))
    t = st.get('temp')
    sysrows = [meter('cpu', cpu, '%d%%' % cpu, iw),
               meter('ram', 100 * used / m['total'] if m.get('total') else 0, '%s / %s' % (size(used), size(m.get('total', 0))), iw)]
    if t:
        sysrows.append(meter('t°', min(100, t), '%.0f °C' % t, iw))
    b = st.get('battery')
    if b:
        sysrows.append(meter('бат', b['pct'], '%d%% %s' % (b['pct'], 'мережа' if b['ac'] else col('bad', 'БАТАРЕЯ')), iw))
    sysrows.append(col('dim', 'працює ') + '%d д %d год · %s' % (up // 86400, up % 86400 // 3600, st.get('os', '')))

    drows = []
    root = st.get('root') or {}
    for d in [dict(root, name='система', mounted=True)] + (st.get('disks') or []):
        if d.get('mounted') and d.get('total'):
            u = d['total'] - d['free']
            drows.append(meter(d['name'][:9], 100 * u / d['total'], '%s / %s' % (size(u), size(d['total'])), iw, lw=10))
        else:
            drows.append(pad(col('dim', d['name'][:9]), 10) + col('bad', 'не підключено'))

    srows = []
    for name, state in (st.get('services') or {}).items():
        on = state == 'active'
        srows.append('%s %s %s' % (col('ok' if on else 'dim', '●' if on else '○'), pad(name, 14), col('ok', 'працює') if on else col('dim', state)))
    srows.append('%s %s %s' % (col('yel', '●'), pad('gazda', 14), col('yel', 'завжди')))

    right = box('система', 'acc', sysrows, rw) + [''] + box('диски', 'yel', drows, rw) + [''] + \
        box('служби', 'bad', srows, rw) + ([''] + box('мережа', 'vio', net_rows(), rw) if net_rows() else [])

    if W >= lw + rw + 10:            # широкий екран: годинник ліворуч, рамки праворуч
        h = max(len(left), len(right))
        lt = (h - len(left)) // 3
        left = [''] * lt + left + [''] * (h - len(left) - lt)
        right = right + [''] * (h - len(right))
        lines = [pad(a, lw) + ' ' * 6 + b for a, b in zip(left, right)]
    else:                            # вузький: усе одне під одним; на малому екрані без великого годинника
        if len(left) + len(right) + 1 > H:
            left = left[8:]
        lines = left + [''] + right
    return center(lines, W, H)


def main():
    signal.signal(signal.SIGHUP, signal.SIG_IGN)   # tty1 перехоплюємо в getty — не падати від «відбою» термінала
    print('hata-screen: старт, stdout=%s' % os.ttyname(1) if os.isatty(1) else 'hata-screen: stdout не термінал',
          file=sys.stderr, flush=True)
    first = True
    while True:
        try:
            text = frame()
        except Exception as e:   # екран не має падати через одну помилку
            print('hata-screen: помилка кадру:', repr(e), file=sys.stderr, flush=True)
            text = 'Hata: %s' % e
        try:
            c = conf()   # до налаштування — темна схема, щоб QR-код не вийшов інвертованим
            pal = palette(c.get('scheme') if c.get('setup_done') else None)
            sys.stdout.write(('\033[9;1]' if first else '') + pal + '\033[0m\033[2J\033[H\033[?25l' + text + '\n')   # 9;1 — гасити екран через хвилину
            sys.stdout.flush()
            first = False
        except OSError as e:
            print('hata-screen: не вдалося писати на екран:', repr(e), file=sys.stderr, flush=True)
        time.sleep(10)


if __name__ == '__main__':
    main()
