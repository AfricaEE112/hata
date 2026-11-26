"""CI: проходимо майстер Hata в справжньому браузері на щойно встановленій системі."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

OUT = sys.argv[1] if len(sys.argv) > 1 else 'hata-out'
os.makedirs(OUT, exist_ok=True)
PW = 'hata-ci-pass'


def sh(cmd):
    print('+', cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width': 1100, 'height': 900})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    n = [0]

    def shot(name):
        pg.wait_for_timeout(600)
        n[0] += 1
        pg.screenshot(path=f'{OUT}/{n[0]:02d}-{name}.png', full_page=True)

    pg.goto('http://localhost/')
    pg.wait_for_selector('#next'); shot('hello')
    pg.click('#next'); pg.wait_for_selector('#p1')
    pg.fill('#p1', PW); pg.fill('#p2', PW); shot('password')
    pg.click('#next'); pg.wait_for_selector('.win .row', timeout=60000); shot('disks')
    uuid = pg.eval_on_selector('[data-mount]', 'e => e.dataset.mount') if pg.query_selector('[data-mount]') else None
    # шукаємо саме наш тестовий диск з міткою media
    row = pg.locator('.row', has_text='media').first
    row.locator('input[type=text]').fill('media')
    row.locator('[data-mount]').click()
    pg.wait_for_selector('.tag.ok', timeout=60000); shot('disks-mounted')

    # диск підключено → кладемо на нього тестові відео (як користувач скопіював би фільми)
    sh('sudo mkdir -p "/srv/disks/media/Фільми" "/srv/disks/media/Аніме/Cowboy Bebop"')
    for i, d in enumerate(['/srv/disks/media/Фільми/Тестовий фільм.mp4', '/srv/disks/media/Аніме/Cowboy Bebop/Cowboy Bebop - 01.mp4',
                           '/srv/disks/media/Аніме/Cowboy Bebop/Cowboy Bebop - 02.mp4']):
        sh(f'sudo ffmpeg -nostdin -v error -y -f lavfi -i "testsrc2=s=640x360:r=25,noise=alls=20:allf=t" -t 6 -pix_fmt yuv420p "{d}"')
    # манга: тайтл з розділами-теками (webp) і тайтл-архів
    for ch in (1, 2):
        sh(f'sudo mkdir -p "/srv/disks/media/IMG.Manga/Тест/Chapter {ch:03d}"')
        for pgn in (1, 2, 3):
            sh(f'sudo ffmpeg -nostdin -v error -y -f lavfi -i "testsrc2=s=600x900" -frames:v 1 "/srv/disks/media/IMG.Manga/Тест/Chapter {ch:03d}/{pgn}.webp"')
    for v in (1, 2):    # томи в окремих теках — мають зібратись в один тайтл
        sh(f'sudo mkdir -p "/srv/disks/media/IMG.Manga/Серія Vol. 0{v}"')
        sh(f'sudo ffmpeg -nostdin -v error -y -f lavfi -i "testsrc2=s=600x900" -frames:v 1 "/srv/disks/media/IMG.Manga/Серія Vol. 0{v}/1.jpg"')
    sh('cd "/srv/disks/media/IMG.Manga/Тест/Chapter 001" && sudo python3 -c "import zipfile,glob; z=zipfile.ZipFile(\'/srv/disks/media/IMG.Manga/Архів.zip\',\'w\'); [z.write(f) for f in glob.glob(\'*.webp\')]"')

    pg.click('#next'); pg.wait_for_selector('[data-go]')
    def into(name, path):    # кнопки «Тут відео/аніме» є на кожному рівні — чекаємо, поки справді відкрилась потрібна тека
        pg.click(f'[data-go]:has-text("{name}")'); pg.wait_for_selector(f'.crumbs:text-is("{path}")')
    into('/srv/disks', '/srv/disks'); into('media/', '/srv/disks/media'); into('Фільми/', '/srv/disks/media/Фільми')
    pg.click('#asVideo'); pg.wait_for_selector('[data-rm="/srv/disks/media/Фільми"]')
    into('..', '/srv/disks/media'); into('Аніме/', '/srv/disks/media/Аніме')
    pg.click('#asAnime'); pg.wait_for_selector('[data-rma]'); shot('folders')
    pg.click('#next'); pg.wait_for_selector('#tsUp'); shot('tailscale')
    pg.click('#next'); pg.wait_for_selector('.win .row'); shot('laptop')
    pg.click('#next'); pg.wait_for_selector('.kv'); shot('summary')
    pg.click('#next'); pg.wait_for_selector('#upd', timeout=90000); shot('panel')
    m = b.new_page(viewport={'width': 390, 'height': 844}, device_scale_factor=2)
    m.context.add_cookies(pg.context.cookies())
    m.goto('http://localhost/'); m.wait_for_selector('#upd'); m.wait_for_timeout(600)
    n[0] += 1
    m.screenshot(path=f'{OUT}/{n[0]:02d}-panel-phone.png', full_page=True)
    # Файли: завантаження з браузера на диск і видалення (ловить заборону писати в /srv/disks, як-от ProtectSystem)
    up = pg.evaluate("""async () => (await fetch('/api/files/upload?dir=/srv/disks/media&name=ci-upload.txt',
                       {method: 'PUT', body: 'hello from CI'})).json()""")
    assert up.get('ok'), up
    lst = pg.evaluate("async () => (await fetch('/api/files?path=/srv/disks/media')).json()")
    assert any(i['name'] == 'ci-upload.txt' for i in lst['items']), lst
    pg.keyboard.press('7'); pg.wait_for_selector('#fm .fm-row'); shot('files')
    rm = pg.evaluate("""async () => (await fetch('/api/files', {method: 'POST', headers: {'Content-Type': 'application/json'},
                       body: JSON.stringify({op: 'delete', paths: ['/srv/disks/media/ci-upload.txt']})})).json()""")
    assert rm.get('ok'), rm
    # Будинок: плата надсилає заміри з ключем (без пароля панелі), повтор пакета не дублюється
    hk = pg.evaluate("async () => (await fetch('/api/house/key')).json()")['key']
    pkt = json.dumps({'device': 'room', 'fw': 'ci', 'uptime_s': 100, 'temp_src': 'ntc',
                      'readings': [{'age_s': 15, 'values': {'temp.room': 22.4, 'internet': 1}},
                                   {'age_s': 0, 'values': {'temp.room': 22.5, 'internet': 1, 'rssi': -70}}],
                      'events': [{'age_s': 600, 'type': 'power_off'}, {'age_s': 30, 'type': 'power_on', 'duration_s': 570}]}).encode()
    def ingest(key):
        req = urllib.request.Request('http://localhost/api/house/ingest', data=pkt, headers={'Content-Type': 'application/json', 'X-Hata-Key': key})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None
    assert ingest('wrong')[0] == 401, 'ingest прийняв чужий ключ'
    c1, r1 = ingest(hk)
    c2, r2 = ingest(hk)
    assert c1 == 200 and r1['added'] == 7 and r2['added'] == 0, (r1, r2)
    hn = pg.evaluate("async () => (await fetch('/api/house/now')).json()")
    room = hn['devices'][0]
    assert room['device'] == 'room' and room['online'] and room['values']['temp.room']['v'] == 22.5, hn
    ev = pg.evaluate("async () => (await fetch('/api/house/events?range=24h')).json()")
    assert ev['gaps'] and ev['gaps'][0]['kind'] == 'power', ev
    pg.keyboard.press('8'); pg.wait_for_selector('#hchart svg'); pg.wait_for_timeout(500); shot('house')
    # Диски й копії: SMART на тестовому диску (файл) недоступний, але сторінка відкривається; копія на той самий диск робиться
    hh = pg.evaluate("async () => (await fetch('/api/disks/health')).json()")
    print('disk health:', [(d['names'], d['smart'].get('state')) for d in hh.get('disks', [])])
    assert hh.get('ok') and any('media' in d['names'] for d in hh['disks']), hh
    bk = pg.evaluate("""async () => (await fetch('/api/backup', {method: 'POST', headers: {'Content-Type': 'application/json'},
                       body: JSON.stringify({op: 'save', target: 'media', folders: ['/srv/disks/media/IMG.Manga'], time: '03:30', keep: 3})})).json()""")
    assert bk.get('ok'), bk
    assert pg.evaluate("async () => (await fetch('/api/backup', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{\"op\": \"run\"}'})).json()")['ok']
    for i in range(60):
        st = pg.evaluate("async () => (await fetch('/api/backup')).json()")
        if not st['job'].get('running') and (st['conf'].get('last') or {}).get('at'):
            break
        time.sleep(1)
    print('backup:', st['conf'].get('last'), [s['name'] for s in st['snapshots']])
    assert st['conf']['last'].get('error') is None and st['snapshots'] and st['conf']['last']['files'] > 5, st['conf']['last']
    pg.keyboard.press('2'); pg.wait_for_selector('#bk'); pg.wait_for_timeout(500); shot('disks')
    # ТО: gazda щохвилини збирає заміри; подія з журналу ядра (відвал USB) має стати подією ТО й рядком журналу
    jget = lambda u: pg.evaluate("async u => (await fetch(u)).json()", u)
    for i in range(40):
        ks = jget('/api/health?op=keys&range=24h')
        if ks.get('ok') and {'cpu.load', 'mem.used', 'net.rx'} <= set(ks.get('keys', [])):
            break
        time.sleep(5)
    print('ТО keys:', ks.get('keys'))
    assert {'cpu.load', 'mem.used', 'net.rx'} <= set(ks['keys']), ks
    sh('echo "usb 9-9: USB disconnect, device number 7" | sudo tee /dev/kmsg >/dev/null')
    for i in range(40):
        ev = jget('/api/health?op=events&range=24h&kinds=usb_off')
        if any(e['subj'] == '9-9' for e in ev.get('events', [])):
            break
        time.sleep(5)
    print('ТО events:', ev)
    assert any(e['subj'] == '9-9' for e in ev['events']), ev
    jl = jget('/api/journal?n=60&src=' + urllib.parse.quote('події'))
    assert any('9-9' in l['msg'] for l in jl['lines']), jl
    assert jget('/api/journal?n=20&src=gazda').get('lines'), 'журнал gazda порожній'
    sm = jget('/api/health?op=summary')
    tb = jget('/api/health?op=table&range=24h')
    print('ТО summary:', sm.get('level'), sm.get('items'))
    assert sm.get('ok') and 'level' in sm and tb.get('ok') and tb['system'].get('mem.used'), (sm, tb)
    se = jget('/api/health?op=series&range=6h&keys=cpu.load,mem.used')
    assert se['series']['mem.used']['points'], se
    li = pg.evaluate("""async () => (await fetch('/api/health', {method: 'POST', headers: {'Content-Type': 'application/json'},
                       body: JSON.stringify({op: 'set_limits', limits: {disk_temp: 47}})})).json()""")
    assert li['limits']['disk_temp'] == 47, li
    csv = pg.evaluate("async () => (await fetch('/api/health/export?range=24h&fmt=csv')).text()")
    assert 'показник' in csv and 'cpu.load' in csv, csv[:300]
    # сторож дисків: правило udev (USB без автосну, тайм-аут 90 с), перемикач «не засинати під час субтитрів ШІ»
    rules = open('/etc/udev/rules.d/90-hata-usb-disks.rules').read()
    assert 'power/control' in rules and 'device/timeout' in rules, rules
    v = subprocess.run('udevadm verify /etc/udev/rules.d/90-hata-usb-disks.rules', shell=True, capture_output=True, text=True)
    print('udevadm verify:', v.returncode, (v.stdout + v.stderr).strip()[-300:])
    assert v.returncode == 0 or 'verify' in (v.stderr or '') and 'Unknown' in (v.stderr or ''), v.stderr
    post_j = lambda d: pg.evaluate("""async d => (await fetch('/api/disks/health', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                   body: JSON.stringify(d)})).json()""", d)
    assert post_j({'op': 'ai_awake', 'on': False}).get('aiAwake') is False
    assert post_j({'op': 'ai_awake', 'on': True}).get('aiAwake') is True
    pg.keyboard.press('9'); pg.wait_for_selector('#toChart svg', timeout=60000); pg.wait_for_timeout(800); shot('to')
    pg.click('[data-tg="load"]'); pg.wait_for_timeout(800); shot('to-load')
    pg.keyboard.press('1'); pg.wait_for_selector('#sys')
    pg.click('details.schemes summary'); pg.click('.schemes button[data-scheme="папір"]'); shot('panel-paper')
    pg.click('details.schemes summary'); pg.click('.schemes button[data-scheme="чай"]')
    lp = b.new_context(viewport={'width': 1100, 'height': 800}).new_page()
    lp.on('pageerror', lambda e: errs.append(str(e)))
    lp.goto('http://localhost/'); lp.wait_for_selector('#pw'); lp.wait_for_timeout(600)
    n[0] += 1
    lp.screenshot(path=f'{OUT}/{n[0]:02d}-login.png')
    lp.fill('#pw', PW); lp.click('#lf button'); lp.wait_for_selector('#upd', timeout=30000)
    print('JS errors:', errs)
    b.close()

# VidBox запустився з тим самим паролем і бачить диск?
def get(url, data=None, cookie=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json', **({'Cookie': cookie} if cookie else {})})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

for i in range(60):
    try:
        get('http://localhost:8800/api/hello'); break
    except Exception:
        time.sleep(2)
tok = get('http://localhost:8800/api/login', {'password': PW})['token']
ck = f'vb={tok}'
for i in range(30):
    lib = get('http://localhost:8800/api/library', cookie=ck)
    anime = get('http://localhost:8800/api/anime', cookie=ck)
    if lib['videos'] and anime['titles']:
        break
    time.sleep(2)
print('VidBox library:', [v['file'] for v in lib['videos']])
print('VidBox anime:', [(t['title'], t['n']) for t in anime['titles']])
assert [v['file'] for v in lib['videos']] == ['Тестовий фільм.mp4'], 'бібліотека VidBox неправильна'
assert anime['titles'] and anime['titles'][0]['n'] == 2, 'аніме не підхопилось'
# манга: папку пропонує сам (IMG.Manga), додаємо її, читаємо сторінку й зберігаємо прогрес
st = get('http://localhost:8800/api/settings', cookie=ck)
print('VidBox manga suggest:', st.get('mangaSuggest'))
assert '/srv/disks/media/IMG.Manga' in st.get('mangaSuggest', []), 'теку з мангою не запропоновано'
assert get('http://localhost:8800/api/settings', {'manga_folder': '/srv/disks/media/IMG.Manga'}, cookie=ck)['ok']
for i in range(20):
    manga = get('http://localhost:8800/api/manga', cookie=ck)
    if len(manga['titles']) == 3:
        break
    time.sleep(1)
print('VidBox manga:', [(t['title'], t['n'], t['pages']) for t in manga['titles']])
assert sorted((t['title'], t['n'], t['pages']) for t in manga['titles']) == [('Архів', 1, 3), ('Серія', 2, 2), ('Тест', 2, 6)], 'манга не підхопилась'
t = next(x for x in manga['titles'] if x['title'] == 'Тест')
mt = get('http://localhost:8800/api/manga/t/' + t['tid'], cookie=ck)
cid = mt['chapters'][1]['cid']
req = urllib.request.Request('http://localhost:8800/manga/page/%s/2' % cid, headers={'Cookie': ck})
with urllib.request.urlopen(req, timeout=10) as r:
    assert r.headers['Content-Type'] == 'image/webp' and r.read(4) == b'RIFF', 'сторінка манги не віддається'
req = urllib.request.Request('http://localhost:8800/manga/cover/' + t['tid'], headers={'Cookie': ck})
with urllib.request.urlopen(req, timeout=60) as r:
    assert r.status == 200 and r.read(2) == b'\xff\xd8', 'обкладинка з першої сторінки не зробилась'
assert get('http://localhost:8800/api/manga/progress', {'cid': cid, 'page': 2}, cookie=ck)['ok']
t = next(x for x in get('http://localhost:8800/api/manga', cookie=ck)['titles'] if x['title'] == 'Тест')
assert t['cont'] and t['cont']['cid'] == cid and t['cont']['page'] == 2, t
assert not errs, errs
open(f'{OUT}/OK', 'w').write('ok\n')
print('OK')
