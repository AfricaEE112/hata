"""Hata: файли на дисках сервера — перегляд, завантаження з браузера, перенесення, перейменування, видалення.

Працює лише всередині ROOT (/srv/disks — диски, які підключила Hata), від імені користувача hata.
Великі перенесення між дисками йдуть у фоні (копіювання з прогресом), панель питає про стан.
"""
import os
import shutil
import threading
import time
import uuid

ROOT = '/srv/disks'
CHUNK = 1 << 20                      # 1 МБ — і для завантаження, і для копіювання
JOBS, JOBS_LOCK = {}, threading.Lock()
BAD = set('\\/:*?"<>|\0')             # символи, які не люблять NTFS і Windows


class Error(Exception):
    """Помилка, яку можна показати людині як є."""


def inside(path, must_exist=True):
    """Справжній шлях, лише якщо він усередині ROOT (без виходу через .. чи посилання)."""
    p = os.path.realpath(path or ROOT)
    root = os.path.realpath(ROOT)
    if p != root and not p.startswith(root + os.sep):
        raise Error('Тут можна працювати лише з дисками Хати (%s)' % ROOT)
    if must_exist and not os.path.exists(p):
        raise Error('Такого вже немає — можливо, його перенесли чи видалили')
    return p


def clean_name(name):
    name = (name or '').strip()
    if not name or name in ('.', '..') or any(c in BAD for c in name) or len(name.encode()) > 240:
        raise Error('Назва не підходить: без символів \\ / : * ? " < > | і не довша за 240 байт')
    return name


def free_name(folder, name):
    """«Фільм.mkv» → «Фільм (2).mkv», якщо таке вже є."""
    base, ext = os.path.splitext(name)
    cand, k = name, 2
    while os.path.exists(os.path.join(folder, cand)):
        cand, k = '%s (%d)%s' % (base, k, ext), k + 1
    return cand


def kind(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in ('.mkv', '.mp4', '.avi', '.mov', '.m4v', '.webm', '.ts', '.wmv', '.flv', '.mpg', '.mpeg'):
        return 'video'
    if ext in ('.srt', '.ass', '.ssa', '.vtt', '.sub'):
        return 'subs'
    if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
        return 'image'
    if ext in ('.mp3', '.flac', '.m4a', '.ogg', '.wav', '.opus'):
        return 'audio'
    if ext in ('.zip', '.rar', '.7z', '.tar', '.gz'):
        return 'archive'
    return 'file'


def listing(path):
    root = os.path.realpath(ROOT)
    if not os.path.isdir(root):
        return {'path': root, 'root': root, 'items': [], 'disks': []}
    p = inside(path)
    if not os.path.isdir(p):
        raise Error('Це не тека')
    items = []
    try:
        names = os.listdir(p)
    except PermissionError:
        raise Error('Немає доступу до цієї теки')
    for n in names:
        if n.startswith('.') or n in ('$RECYCLE.BIN', 'System Volume Information', 'lost+found'):
            continue
        f = os.path.join(p, n)
        try:
            st = os.stat(f)
        except OSError:
            continue
        d = os.path.isdir(f)
        if n.endswith('.hata-part'):
            continue                 # недокачане завантаження
        items.append({'name': n, 'dir': d, 'size': 0 if d else st.st_size, 'mtime': int(st.st_mtime),
                      'kind': 'dir' if d else kind(n)})
    items.sort(key=lambda i: (not i['dir'], i['name'].lower()))
    du = shutil.disk_usage(p)
    disks = []
    for n in sorted(os.listdir(root)):
        d = os.path.join(root, n)
        if os.path.ismount(d):
            u = shutil.disk_usage(d)
            disks.append({'name': n, 'path': d, 'free': u.free, 'total': u.total})
    return {'path': p, 'root': root, 'up': os.path.dirname(p) if p != root else '', 'items': items,
            'free': du.free, 'total': du.total, 'writable': os.access(p, os.W_OK), 'disks': disks}


def mkdir(folder, name):
    f = inside(folder)
    target = os.path.join(f, clean_name(name))
    if os.path.exists(target):
        raise Error('Тека «%s» уже є' % name)
    try:
        os.mkdir(target)
    except PermissionError:
        raise Error('Немає права писати в цю теку')
    return {'path': target}


def rename(path, name):
    src = inside(path)
    if src == os.path.realpath(ROOT) or os.path.dirname(src) == os.path.realpath(ROOT):
        raise Error('Диск перейменовується на сторінці «Диски»')
    dst = os.path.join(os.path.dirname(src), clean_name(name))
    if os.path.exists(dst) and os.path.normcase(dst) != os.path.normcase(src):
        raise Error('«%s» уже є в цій теці' % name)
    try:
        os.rename(src, dst)
    except PermissionError:
        raise Error('Немає права перейменувати')
    return {'path': dst}


def delete(paths):
    root = os.path.realpath(ROOT)
    for p in paths:
        p = inside(p)
        if p == root or os.path.dirname(p) == root:
            raise Error('Цілий диск так не видаляється')
    n = 0
    for p in paths:
        p = inside(p)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            n += 1
        except PermissionError:
            raise Error('Немає права видалити «%s»' % os.path.basename(p))
    return {'deleted': n}


# ───────────────────────── перенесення (у фоні) ─────────────────────────

def tree_size(p):
    if not os.path.isdir(p):
        return os.path.getsize(p)
    total = 0
    for dp, _, fs in os.walk(p):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def move(paths, folder):
    """Перенести в іншу теку. На тому ж диску — миттєво; між дисками — копіювання у фоні з прогресом."""
    dst_dir = inside(folder)
    if not os.path.isdir(dst_dir):
        raise Error('Куди переносити — має бути тека')
    srcs = [inside(p) for p in paths]
    for s in srcs:
        if dst_dir == s or dst_dir.startswith(s + os.sep):
            raise Error('Не можна перенести теку саму в себе')
    dev = os.stat(dst_dir).st_dev
    slow = [s for s in srcs if os.stat(s).st_dev != dev]
    fast = [s for s in srcs if s not in slow]
    for s in fast:
        if os.path.dirname(s) != dst_dir:
            os.rename(s, os.path.join(dst_dir, free_name(dst_dir, os.path.basename(s))))
    if not slow:
        return {'done': True}
    total = sum(tree_size(s) for s in slow)
    if total > shutil.disk_usage(dst_dir).free:
        raise Error('На диску призначення не вистачає місця')
    jid = uuid.uuid4().hex[:10]
    job = {'id': jid, 'total': total, 'done': 0, 'state': 'working', 'error': '', 'name': os.path.basename(slow[0]),
           'count': len(slow), 'started': time.time()}
    with JOBS_LOCK:
        JOBS[jid] = job
    threading.Thread(target=_move_job, args=(job, slow, dst_dir), daemon=True).start()
    return {'done': False, 'job': jid}


def _copy_file(src, dst, job):
    with open(src, 'rb') as a, open(dst, 'wb') as b:
        while True:
            buf = a.read(CHUNK)
            if not buf:
                break
            b.write(buf)
            job['done'] += len(buf)
    shutil.copystat(src, dst)


def _move_job(job, srcs, dst_dir):
    try:
        for s in srcs:
            job['name'] = os.path.basename(s)
            target = os.path.join(dst_dir, free_name(dst_dir, os.path.basename(s)))
            if os.path.isdir(s):
                for dp, dns, fs in os.walk(s):
                    rel = os.path.relpath(dp, s)
                    os.makedirs(os.path.join(target, rel), exist_ok=True)
                    for f in fs:
                        _copy_file(os.path.join(dp, f), os.path.join(target, rel, f), job)
                shutil.rmtree(s)
            else:
                _copy_file(s, target, job)
                os.remove(s)
        job['state'] = 'done'
    except Exception as e:           # місце, права, відключений диск — показуємо як є
        job.update(state='error', error=str(e)[-300:])
    job['finished'] = time.time()


def jobs():
    now = time.time()
    with JOBS_LOCK:
        for k in [k for k, j in JOBS.items() if j.get('finished') and now - j['finished'] > 600]:
            del JOBS[k]
        return [dict(j) for j in JOBS.values()]


# ───────────────────────── завантаження з браузера ─────────────────────────

def upload(folder, relname, length, stream):
    """Потокове завантаження: пишемо шматками в «.hata-part», у кінці перейменовуємо.
    relname може містити теки («Серіал/Сезон 1/01.mkv») — так перетягують цілу теку."""
    f = inside(folder)
    parts = [clean_name(x) for x in relname.replace('\\', '/').split('/') if x]
    if not parts:
        raise Error('Немає назви файла')
    target_dir = os.path.join(f, *parts[:-1])
    inside(target_dir, must_exist=False)
    if length + (64 << 20) > shutil.disk_usage(f).free:
        raise Error('На диску не вистачає місця: потрібно %.1f ГБ' % (length / (1 << 30)))
    try:
        os.makedirs(target_dir, exist_ok=True)
    except PermissionError:
        raise Error('Немає права писати в цю теку')
    name = free_name(target_dir, parts[-1])
    part = os.path.join(target_dir, '.' + name + '.hata-part')
    left = length
    try:
        with open(part, 'wb') as out:
            while left > 0:
                buf = stream.read(min(CHUNK, left))
                if not buf:
                    raise Error('З\'єднання обірвалось')
                out.write(buf)
                left -= len(buf)
        os.replace(part, os.path.join(target_dir, name))
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return {'path': os.path.join(target_dir, name), 'name': name}
