"""CI: проходимо майстер Hata в справжньому браузері на щойно встановленій системі."""
import json
import os
import subprocess
import sys
import time
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
    m.screenshot(path=f'{OUT}/{n[0] + 1:02d}-panel-phone.png', full_page=True)
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
assert not errs, errs
open(f'{OUT}/OK', 'w').write('ok\n')
print('OK')
