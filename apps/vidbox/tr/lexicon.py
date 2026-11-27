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
            added = bool(venv_dir) and add_site_packages(venv_dir)   # спершу шлях до venv ШІ, потім імпорт
            if cls._inst is None or (not cls._inst.ok and added):
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


UK_ABC = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя'"


def _edits1(w):
    splits = [(w[:i], w[i:]) for i in range(len(w) + 1)]
    return {a + b[1:] for a, b in splits if b} | \
        {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1} | \
        {a + c + b[1:] for a, b in splits if b for c in UK_ABC} | \
        {a + c + b for a, b in splits for c in UK_ABC}


def suggest(lex, word, limit=3):
    """Справжні слова, що відрізняються від `word` на одну правку (вставка, пропуск, заміна, перестановка літер);
    для коротких — на дві. Для підказки моделі: «висоності» → «високості», «завагірніла» → «завагітніла»."""
    if not lex.ok:
        return []
    w = norm_apos(word.lower())
    if len(w) < 4:
        return []
    known = lambda x: x != w and lex.morph.word_is_known(x)
    e1 = _edits1(w)
    out = sorted({x for x in e1 if known(x)}, key=lambda x: (abs(len(x) - len(w)), x))
    if not out and len(w) <= 8:
        out = sorted({y for x in e1 for y in _edits1(x) if known(y)}, key=lambda x: (abs(len(x) - len(w)), x))
    res = []
    for x in out:
        x = x[:1].upper() + x[1:] if word[:1].isupper() else x
        if x not in res:
            res.append(x)
        if len(res) >= limit:
            break
    return res
