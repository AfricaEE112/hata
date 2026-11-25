"""Словники для перевірки перекладу: орфографія й морфологія української (VESUM через pymorphy3),
білий список субтитрів, русизми.

pymorphy3 + pymorphy3-dicts-uk ставляться у venv ШІ разом з Whisper. Пакети чисто пітонівські, тож VidBox
підхоплює їх з site-packages цього venv навіть на іншій версії Python. Немає словника — перевірки, що від нього
залежать, вимикаються, а не падають (`Lexicon.ok` = False, причина в `Lexicon.why`).
"""
import glob
import os
import re
import sys
import threading

QA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'qa')

CYR = 'А-ЯІЇЄҐа-яіїєґЁёЫыЭэЪъ'
APOS = "'’ʼ"
WORD_RE = re.compile(r"[^\W\d_]+(?:[%s-][^\W\d_]+)*" % APOS)


def norm_apos(w):
    return re.sub('[’ʼ`]', "'", w)


def is_cyr(w):
    letters = [ch for ch in w if ch.isalpha()]
    return bool(letters) and all('Ѐ' <= ch <= 'ӿ' for ch in letters)


def _read_lines(path):
    try:
        with open(path, encoding='utf-8') as f:
            return [x.strip() for x in f if x.strip() and not x.lstrip().startswith('#')]
    except OSError:
        return []


def add_site_packages(venv_dir):
    """Додати site-packages venv ШІ до sys.path (для pymorphy3). Повертає True, якщо щось додано."""
    added = False
    for p in glob.glob(os.path.join(venv_dir, 'lib', 'python3*', 'site-packages')) + \
            glob.glob(os.path.join(venv_dir, 'Lib', 'site-packages')):
        if p not in sys.path:
            sys.path.append(p)
            added = True
    return added


class Lexicon:
    """Один екземпляр на процес (`Lexicon.get()`); потокобезпечний для читання."""
    _inst = None
    _lock = threading.Lock()

    def __init__(self, extra_paths=()):
        self.morph, self.ok, self.why = None, False, ''
        try:
            import pymorphy3
            try:
                import pymorphy3_dicts_uk
                self.morph = pymorphy3.MorphAnalyzer(path=pymorphy3_dicts_uk.get_path(), lang='uk')
            except ImportError:
                self.morph = pymorphy3.MorphAnalyzer(lang='uk')
            self.ok = True
        except Exception as e:          # нема пакета чи словника — працюємо без орфографії й роду
            self.why = 'словник української недоступний: %s' % e
        self.extra, self.extra_pre = set(), []
        for p in (os.path.join(QA_DIR, 'uk_extra.dic'),) + tuple(extra_paths):
            for w in _read_lines(p):
                w = norm_apos(w.lower())
                (self.extra_pre.append(w[:-1]) if w.endswith('*') else self.extra.add(w))
        self.ru_words = {w.lower() for w in _read_lines(os.path.join(QA_DIR, 'ru_words.txt'))}
        stems = _read_lines(os.path.join(QA_DIR, 'ru_stems.txt'))
        self.ru_stems = re.compile('^(%s)' % '|'.join(stems), re.I) if stems else None
        self._cache = {}

    @classmethod
    def get(cls, venv_dir=None):
        with cls._lock:
            if cls._inst is None or (not cls._inst.ok and venv_dir and add_site_packages(venv_dir)):
                cls._inst = cls()
            return cls._inst

    # ---- слова ----
    def whitelisted(self, w):
        w = norm_apos(w.lower())
        return w in self.extra or any(w.startswith(p) for p in self.extra_pre)

    def known(self, w):
        """Чи є слово в словнику (VESUM або білий список). None — словника нема, судити не можна."""
        w = norm_apos(w.lower())
        if self.whitelisted(w):
            return True
        if not self.ok:
            return None
        r = self._cache.get(w)
        if r is None:
            r = self.morph.word_is_known(w) or (
                "'" in w and self.morph.word_is_known(w.replace("'", '’'))) or (
                '-' in w and all(self.morph.word_is_known(p) or self.whitelisted(p) for p in w.split('-') if p))
            self._cache[w] = r
        return r

    def russism(self, w):
        wl = w.lower()
        return bool(re.search('[ыэъёЫЭЪЁ]', w) or wl in self.ru_words or (self.ru_stems and self.ru_stems.match(wl)))

    def parses(self, w):
        return self.morph.parse(norm_apos(w.lower())) if self.ok else []

    def lemmas(self, w):
        """Множина початкових форм слова (для порівняння з глосарієм: «сестро» ~ «сестра»)."""
        ps = self.parses(w)
        return {p.normal_form for p in ps if p.score > 0} or {norm_apos(w.lower())}

    def gender(self, w, pos=('VERB', 'ADJF', 'ADJS', 'PRTF', 'PRTS', 'NPRO')):
        """'masc'/'femn', якщо ВСІ розбори слова-«ознаки» (дієслово мин. часу, прикметник у називному однини)
        однозначно мають цей рід; інакше None."""
        ps = self.parses(w)
        ps = [p for p in ps if getattr(p, 'is_known', True)] or ps
        gs = set()
        for p in ps:
            t = p.tag
            if t.POS not in pos:
                continue
            if t.POS == 'VERB' and t.tense != 'past':
                continue
            if t.POS in ('ADJF', 'PRTF', 'NPRO') and (t.case != 'nomn' or t.number == 'plur'):
                continue
            if t.gender in ('masc', 'femn'):
                gs.add(t.gender)
            elif t.number == 'sing':
                gs.add('?')
        return gs.pop() if len(gs) == 1 and '?' not in gs else None
