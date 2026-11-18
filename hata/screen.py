#!/usr/bin/env python3
"""Екран ноутбука (tty1): замість логіна — статус Hata і QR-код адреси панелі.

До налаштування: «Hata майже готова» + QR для майстра. Після: стан сервера.
Нічого не натискаємо — тільки дивимось. Оновлюється кожні 10 секунд.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time

CFG = '/var/lib/hata/hata.json'
C = {'acc': '\033[1;36m', 'mute': '\033[0;37m', 'ok': '\033[1;32m', 'bad': '\033[1;31m', 'b': '\033[1m', 'r': '\033[0m'}
LOGO = r'''
   _           _
  | |__   __ _| |_ __ _
  | '_ \ / _` | __/ _` |
  | | | | (_| | || (_| |
  |_| |_|\__,_|\__\__,_|
'''


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


def qr(text):
    try:
        return subprocess.run(['qrencode', '-t', 'ANSI', '-m', '2', text], stdout=subprocess.PIPE,
                              timeout=10, text=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def size(b):
    for u in ('Б', 'КБ', 'МБ', 'ГБ', 'ТБ'):
        if b < 1024 or u == 'ТБ':
            return ('%.0f' if b >= 100 or u in ('Б', 'КБ', 'МБ') else '%.1f') % b + ' ' + u
        b /= 1024


def setup_done():
    try:
        with open(CFG) as f:
            return bool(json.load(f).get('setup_done'))
    except (OSError, ValueError):
        return False


def frame():
    host = socket.gethostname()
    addr = ip()
    url = 'http://%s/' % (addr or host + '.local')
    out = [C['acc'] + LOGO + C['r']]
    if not setup_done():
        out += ['', C['b'] + '  Hata майже готова.' + C['r'],
                '  Відскануй код телефоном або відкрий у браузері:', '',
                '    ' + C['acc'] + url + C['r'] + ('   або  http://%s.local/' % host), '']
        out.append(qr(url))
        return '\n'.join(out)
    st = gazda({'do': 'status'})
    ts = gazda({'do': 'tailscale', 'op': 'status'})
    up = st.get('uptime', 0)
    out += ['  %s%s%s · працює %d д %d год · %s' % (C['b'], host, C['r'], up // 86400, up % 86400 // 3600, st.get('os', '')),
            '  панель   %s%s%s' % (C['acc'], url, C['r']),
            '  vidbox   http://%s:8800/' % (addr or host + '.local')]
    if ts.get('state') == 'Running':
        out.append('  tailscale %s' % ts.get('name', ''))
    t = st.get('temp')
    m = st.get('mem') or {}
    out += ['', '  температура %s   пам\'ять %s з %s' % ('%.0f °C' % t if t else '—', size(m.get('total', 0) - m.get('avail', 0)), size(m.get('total', 0)))]
    b = st.get('battery')
    if b:
        out.append('  батарея     %d%% %s' % (b['pct'], 'від мережі' if b['ac'] else 'ВІД БАТАРЕЇ'))
    out.append('')
    for d in st.get('disks') or []:
        if d.get('mounted'):
            used = d['total'] - d['free']
            bar = int(30 * used / d['total']) if d.get('total') else 0
            out.append('  %-10s [%s%s] вільно %s' % (d['name'], '#' * bar, '.' * (30 - bar), size(d['free'])))
        else:
            out.append('  %-10s %sне підключено%s' % (d['name'], C['bad'], C['r']))
    out.append('')
    for name, state in (st.get('services') or {}).items():
        out.append('  %s●%s %s' % (C['ok'] if state == 'active' else C['bad'], C['r'], name))
    return '\n'.join(out)


def main():
    signal.signal(signal.SIGHUP, signal.SIG_IGN)   # tty1 перехоплюємо в getty — не падати від «відбою» термінала
    sys.stdout.write('\033[9;1]')     # гасити екран через хвилину без натискань
    while True:
        try:
            text = frame()
        except Exception as e:   # екран не має падати через одну помилку
            text = 'Hata: %s' % e
        sys.stdout.write('\033[2J\033[H\033[?25l' + text + '\n')
        sys.stdout.flush()
        time.sleep(10)


if __name__ == '__main__':
    main()
