#!/usr/bin/env python3
"""Екран ноутбука (tty1): замість логіна — статус Hata і QR-код адреси панелі.

До налаштування: «Хата майже готова» + QR для майстра. Після: стан сервера.
Нічого не натискаємо — тільки дивимось. Оновлюється кожні 10 секунд.
Кольори — з тієї ж схеми, що вибрана в панелі (палітра консолі переналаштовується).
"""
import json
import os
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


def rows():
    try:
        return os.get_terminal_size(1).lines
    except OSError:
        return 25


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


def clock():
    """Великий точковий годинник з повних блоків — лише для великого екрана."""
    t = time.strftime('%H:%M')
    lines = []
    for r in range(7):
        parts = []
        for ch in t:
            bits = FONT[ch]
            w = len(bits) // 7
            parts.append(''.join('██' if b == '1' else '  ' for b in bits[r * w:(r + 1) * w]))
        lines.append('  ' + C['b'] + '  '.join(parts) + C['r'])
    return lines


def rule(title, width=60):
    return '  %s──%s %s %s%s' % (C['dim'], C['r'] + C['acc'], title, C['r'] + C['dim'], '─' * max(4, width - len(title)) + C['r'])


def segs(pct, n=30):
    on = round(n * pct / 100)
    col = C['ok'] if pct < 60 else C['yel'] if pct < 85 else C['bad']
    return col + '█' * on + C['dim'] + '░' * (n - on) + C['r']


def frame():
    host = socket.gethostname()
    addr = ip()
    url = 'http://%s/' % (addr or host + '.local')
    small = rows() < 42          # малий екран: без годинника і з компактним QR
    who = '  %sхата%s%s@%s%s' % (C['acc'], C['r'], C['dim'], C['r'] + C['b'] + host, C['r'])
    out = [''] + ([] if small else clock() + ['']) + [who, '']
    if not conf().get('setup_done'):
        out += ['  ' + C['b'] + 'Хата майже готова.' + C['r'],
                '  Відскануй код телефоном або відкрий у браузері:', '',
                '    ' + C['acc'] + url + C['r'] + ('   або  http://%s.local/' % host), '']
        out.append(qr(url, compact=small))
        return '\n'.join(out)
    st = gazda({'do': 'status'})
    ts = gazda({'do': 'tailscale', 'op': 'status'})
    up = st.get('uptime', 0)
    out += ['  працює %d д %d год · %s' % (up // 86400, up % 86400 // 3600, st.get('os', '')),
            '  %sпанель%s    %s%s%s' % (C['yel'], C['r'], C['acc'], url, C['r']),
            '  %svidbox%s    http://%s:8800/' % (C['yel'], C['r'], addr or host + '.local')]
    if ts.get('state') == 'Running':
        out.append('  %stailscale%s %s' % (C['yel'], C['r'], ts.get('name', '')))
    t = st.get('temp')
    m = st.get('mem') or {}
    used = m.get('total', 0) - m.get('avail', 0)
    out += ['', rule('система'),
            '  ram  %s %s / %s' % (segs(100 * used / m['total'] if m.get('total') else 0), size(used), size(m.get('total', 0))),
            '  t°   %s %s' % (segs(min(100, t or 0)), '%.0f °C' % t if t else '—')]
    b = st.get('battery')
    if b:
        out.append('  бат  %s %d%% %s' % (segs(b['pct']), b['pct'], 'від мережі' if b['ac'] else C['bad'] + 'ВІД БАТАРЕЇ' + C['r']))
    out += ['', rule('диски')]
    for d in st.get('disks') or []:
        if d.get('mounted') and d.get('total'):
            used = d['total'] - d['free']
            out.append('  %-10s %s вільно %s' % (d['name'][:10], segs(100 * used / d['total']), size(d['free'])))
        else:
            out.append('  %-10s %sне підключено%s' % (d['name'][:10], C['bad'], C['r']))
    out += ['', rule('служби')]
    for name, state in (st.get('services') or {}).items():
        out.append('  %s●%s %-12s %s%s%s' % (C['ok'] if state == 'active' else C['dim'], C['r'], name,
                                            C['dim'], 'працює' if state == 'active' else state, C['r']))
    return '\n'.join(out)


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
