"""Розділ «Копії»: щоночі — налаштування й бази Хати та вибрані теки на інший диск.

Кожна копія — тека «Копії Хати/2026-11-21 03-30» на вибраному диску. Незмінені файли не копіюються
вдруге, а стають жорсткими посиланнями на попередню копію (як rsync --link-dest): кожна копія виглядає
повною, а місця займає лише змінене. На exFAT посилань немає — там кожна копія повна, тож тримаємо менше.

Бази SQLite (VidBox, «Будинок») копіюються через їхній власний механізм резервування, щоб не зняти
файл посеред запису. Кеші (кадри, обкладинки, копії відео для телефона) не копіюються — вони відтворюються самі.
"""
import json
import os
import shutil
import sqlite3
import threading
import time

ROOT_NAME = 'Копії Хати'
SKIP_DIRS = {'thumbs', 'sprites', 'frames', 'prepared', 'demo-disks', '__pycache__', '.Trash-1000', '$RECYCLE.BIN',
             'System Volume Information', ROOT_NAME}
SKIP_SUFFIX = ('-wal', '-shm', '.part', '.tmp', '.hata-part', '-journal')
JOB = {'running': False}
LOCK = threading.Lock()


class Error(Exception):
    pass


def snap_dir(target):
    return os.path.join(target, ROOT_NAME)


def snapshots(target):
    """Готові копії, від нових до старих (незавершені мають .part у назві)."""
    try:
        names = [n for n in os.listdir(snap_dir(target)) if not n.endswith('.part') and os.path.isdir(os.path.join(snap_dir(target), n))]
    except OSError:
        return []
    out = []
    for n in sorted(names, reverse=True):
        info = {}
        try:
            with open(os.path.join(snap_dir(target), n, '.копія.json'), encoding='utf-8') as f:
                info = json.load(f)
        except (OSError, ValueError):
            pass
        out.append(dict(info, name=n, path=os.path.join(snap_dir(target), n)))
    return out


def _skip(name):
    return name in SKIP_DIRS or name.endswith(SKIP_SUFFIX) or name.startswith('.~')


def _copy_tree(src, dst, prev, st, links_ok):
    """Копіює src → dst; незмінене (той самий розмір і час) — посиланням на prev."""
    os.makedirs(dst, exist_ok=True)
    try:
        entries = list(os.scandir(src))
    except OSError as e:
        st['errors'].append('%s: %s' % (src, e.strerror or e))
        return links_ok
    for e in entries:
        if _skip(e.name):
            continue
        s, d, p = e.path, os.path.join(dst, e.name), os.path.join(prev, e.name) if prev else None
        try:
            if e.is_dir(follow_symlinks=False):
                links_ok = _copy_tree(s, d, p, st, links_ok)
                continue
            if not e.is_file(follow_symlinks=False):
                continue
            sst = e.stat()
            st['files'] += 1
            st['bytes'] += sst.st_size
            if e.name.endswith('.db'):            # SQLite — знімок через backup(), а не копія файла
                tmp = d + '.part'
                con = sqlite3.connect('file:%s?mode=ro' % s, uri=True, timeout=30)
                out = sqlite3.connect(tmp)
                with out:
                    con.backup(out)
                con.close()
                out.close()
                os.replace(tmp, d)
                st['copied'] += sst.st_size
                continue
            if links_ok and p:
                try:
                    pst = os.stat(p)
                    if pst.st_size == sst.st_size and int(pst.st_mtime) == int(sst.st_mtime):
                        os.link(p, d)
                        st['linked'] += 1
                        continue
                except FileNotFoundError:
                    pass
                except OSError:
                    links_ok = False            # файлова система без посилань (exFAT) — далі просто копіюємо
            shutil.copy2(s, d)
            st['copied'] += sst.st_size
        except (OSError, sqlite3.Error) as err:
            st['errors'].append('%s: %s' % (s, getattr(err, 'strerror', None) or err))
        if st['errors'] and len(st['errors']) > 200:
            raise Error('забагато помилок, зупиняю')
    return links_ok


MOUNTED = True     # у демо-режимі «диски» — звичайні теки


def run(target, sources, keep, progress=None):
    """Одна копія. sources — [(назва в копії, шлях)]. Повертає підсумок."""
    if not os.path.isdir(target) or (MOUNTED and not os.path.ismount(target)):
        raise Error('Диск для копій не підключено: %s' % target)
    t0 = time.time()
    name = time.strftime('%Y-%m-%d %H-%M')
    base = snap_dir(target)
    os.makedirs(base, exist_ok=True)
    readme = os.path.join(base, 'ПРОЧИТАЙ.txt')
    if not os.path.exists(readme):
        with open(readme, 'w', encoding='utf-8') as f:
            f.write('Копії Хати. Кожна тека — копія на певний день: налаштування й бази Хати (hata) та вибрані теки.\n'
                    'Незмінені файли між копіями — ті самі файли на диску (жорсткі посилання), тож місця займають раз.\n'
                    'Відновити: скопіюй потрібне назад (у панелі — розділ «Файли»).\n')
    prev = next((s['path'] for s in snapshots(target)), None)
    dst = os.path.join(base, name + '.part')
    shutil.rmtree(dst, ignore_errors=True)
    st = {'files': 0, 'bytes': 0, 'copied': 0, 'linked': 0, 'errors': []}
    links_ok = True
    for label, src in sources:
        if progress:
            progress(label)
        if not os.path.isdir(src):
            st['errors'].append('%s: теки немає' % src)
            continue
        links_ok = _copy_tree(src, os.path.join(dst, label), os.path.join(prev, label) if prev else None, st, links_ok)
    info = {'at': int(t0), 'took': round(time.time() - t0, 1), 'files': st['files'], 'bytes': st['bytes'], 'copied': st['copied'],
            'linked': st['linked'], 'errors': len(st['errors']), 'sources': [l for l, _ in sources], 'links': links_ok}
    with open(os.path.join(dst, '.копія.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False)
    final = os.path.join(base, name)
    if os.path.exists(final):            # дві копії за хвилину — старішу замінюємо
        shutil.rmtree(final, ignore_errors=True)
    os.replace(dst, final)
    # старі копії — геть; без посилань (exFAT) кожна повна, тож тримаємо не більше трьох
    keep = max(1, keep if links_ok else min(keep, 3))
    for old in snapshots(target)[keep:]:
        shutil.rmtree(old['path'], ignore_errors=True)
    info['name'] = name
    info['errorList'] = st['errors'][:20]
    return info


def start(target, sources, keep, done):
    """Копія у фоні. done(info|None, error|None) — коли закінчилась."""
    with LOCK:
        if JOB['running']:
            return False
        JOB.update(running=True, started=time.time(), step='', target=target)

    def go():
        try:
            info = run(target, sources, keep, progress=lambda s: JOB.update(step=s))
            done(info, None)
        except Exception as e:
            done(None, str(e))
        finally:
            JOB.update(running=False, step='')
    threading.Thread(target=go, daemon=True).start()
    return True
