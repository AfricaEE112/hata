"""Репліки субтитрів для нового ядра перекладу.

Головне правило: репліка — це номер `n` з незмінними таймінгами й оригіналом. Етапи перекладу лише додають
кандидатів (`Line.cands`), приймає їх тільки `validate`. Кількість і порядок реплік ніколи не змінюються,
тому зсув перекладу відносно часу неможливий за побудовою.
"""
import re
from dataclasses import dataclass, field

SCENE_GAP = 5.0        # пауза, з якої починається нова сцена, с
SCENE_MAX = 30         # найбільша сцена (= пакет для моделі)
SCENE_MIN = 6          # меншу сцену не відокремлювати — злити з сусідньою


@dataclass
class Issue:
    code: str               # 'spelling', 'russism', 'shift', 'gender_who', ...
    sev: str                # 'block' — кандидат не приймається; 'warn' — приймається, але йде у звіт
    msg: str                # пояснення українською (іде і в підказку моделі, і у звіт)
    words: tuple = ()

    def as_dict(self):
        return {'code': self.code, 'sev': self.sev, 'msg': self.msg, 'words': list(self.words)}


@dataclass
class Line:
    n: int
    start: float
    end: float
    en: str
    kind: str = 'dialog'    # 'dialog' | 'sign' | 'song' | 'credits' (подяки) | 'jp' (японська, ромадзі) — останні два не перекладаємо
    scene: int = 0
    cont: bool = False      # речення продовжується в наступній репліці
    who: str = ''           # мовець (ім'я персонажа з аналізу або від моделі)
    to: str = ''            # до кого звертаються
    uk: str = ''            # прийнятий переклад
    cands: list = field(default_factory=list)   # [{'uk', 'stage', 'issues'}] — усі спроби, для звіту
    issues: list = field(default_factory=list)  # проблеми прийнятого перекладу (warn) або причини відмов
    status: str = 'new'     # 'new' | 'ok' | 'warn' | 'failed'

    @property
    def dur(self):
        return max(0.0, self.end - self.start)


def clean_src(t):
    t = re.sub(r'<[^>]+>', '', str(t or ''))           # теги VTT/SRT
    t = re.sub(r'\{\\[^}]*\}', '', t)                   # теги ASS
    return re.sub(r'[ \t]+', ' ', t.replace('\\N', '\n')).strip()


CREDITS = re.compile(r'(?i)\b(translated by|translation by|translation:|subtitles by|subbed by|encoded by|encoding|'
                     r'typeset|timing by|special thanks|upscaled by|raws? by|a [\w.-]+ project|brought to you by|'
                     r'proofread(ing)?\s*(by|:)|editing:|edited by|qc:|ts:)|[\w-]+subs\.(com|net|org)\b')


JP_SCRIPT = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]')
ROMAJI_WORD = re.compile(r"^(?:(?:[kgsztdnhbpmyrwfjv]|sh|ch|ts|ky|gy|ny|hy|my|ry|by|py)?[aiueo]|n|-)+$", re.I)
ENGLISH_HINT = re.compile(r"(?i)\b(the|you|and|is|are|my|your|this|that|will|with|of|to|in|it|me|be|so|on)\b")


def is_japanese(text):
    """Рядок японською (кана/кандзі) або ромадзі (karaoke пісні: «iki o tometa kono sekai») — не перекладаємо."""
    if JP_SCRIPT.search(text):
        return True
    words = re.findall(r"[A-Za-z'-]+", text)
    if len(words) < 2 or ENGLISH_HINT.search(text):
        return False
    good = sum(1 for w in words if ROMAJI_WORD.match(w.replace("'", '')))
    return good / len(words) >= 0.85


def _kind(text, overlap):
    if CREDITS.search(text):
        return 'credits'
    if is_japanese(text):
        return 'jp'
    if '♪' in text or '♫' in text:
        return 'song'
    letters = [c for c in text if c.isalpha()]
    words = text.split()
    caps = letters and sum(c.isupper() for c in letters) / len(letters) > 0.8 and len(letters) >= 3
    if caps and len(words) <= 6:
        return 'sign'
    if overlap and len(words) <= 4 and not re.search(r'[.!?…,]$', text):
        return 'sign'
    return 'dialog'


def prepare(segs):
    """segs — [(start, end, text)] у порядку часу (як з read_vtt/Whisper). Повертає [Line] з n від 0.
    Порожні репліки лишаються (з порожнім en) — щоб номери збігалися з вихідним файлом."""
    lines = []
    for i, s in enumerate(segs):
        st, en_, txt = float(s[0]), float(s[1]), clean_src(s[2])
        lines.append(Line(n=i, start=st, end=en_, en=txt))
    for i, ln in enumerate(lines):
        prev_ = lines[i - 1] if i else None
        next_ = lines[i + 1] if i + 1 < len(lines) else None
        overlap = bool((prev_ and prev_.end > ln.start + 0.05) or (next_ and next_.start < ln.end - 0.05))
        ln.kind = _kind(ln.en, overlap) if ln.en else 'dialog'
        if next_ and ln.en and next_.en and ln.kind == next_.kind == 'dialog':
            ends = re.search(r'[.!?…]["»”)]*$', ln.en)
            ln.cont = bool(not ends and next_.start - ln.end < 1.0 and
                           (re.search(r'[,—–-]$|\.\.\.$', ln.en) or next_.en[:1].islower()))
    split_scenes(lines)
    return lines


def split_scenes(lines):
    """Ділить на сцени за паузами; задовгі сцени — по найбільшій паузі всередині, не розриваючи `cont`."""
    if not lines:
        return []
    groups, cur = [], [lines[0]]
    for a, b in zip(lines, lines[1:]):
        if b.start - a.end >= SCENE_GAP and not a.cont:
            groups.append(cur)
            cur = []
        cur.append(b)
    groups.append(cur)

    def cut(g):
        if len(g) <= SCENE_MAX:
            return [g]
        best, bi = -1.0, None
        lo, hi = SCENE_MIN, len(g) - SCENE_MIN
        for i in range(lo, hi):
            if g[i - 1].cont:
                continue
            gap = g[i].start - g[i - 1].end
            if gap > best:
                best, bi = gap, i
        if bi is None:
            bi = len(g) // 2
        return cut(g[:bi]) + cut(g[bi:])

    out = []
    for g in groups:
        out.extend(cut(g))
    merged = []
    for g in out:                      # дрібні шматки — до попередньої сцени, якщо влазить
        if merged and len(g) < SCENE_MIN and len(merged[-1]) + len(g) <= SCENE_MAX:
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    for si, g in enumerate(merged):
        for ln in g:
            ln.scene = si
    return merged


def scenes(lines):
    out = {}
    for ln in lines:
        out.setdefault(ln.scene, []).append(ln)
    return [out[k] for k in sorted(out)]


def wrap(text, width=42):
    """Довга репліка в один рядок → два рядки для екрана (≤ width, розрив біля середини: спершу після розділового знака,
    інакше на пробілі). Уже розбиті й короткі не чіпаємо; задовга навіть у два рядки — лишається як є (у звіті too_long)."""
    t = str(text or '').strip()
    if '\n' in t or len(t) <= width:
        return t
    mid = len(t) / 2
    best = None
    for m in re.finditer(r' ', t):
        i = m.start()
        a, b = t[:i].rstrip(), t[i + 1:].lstrip()
        if not a or not b or max(len(a), len(b)) > width + 6:
            continue
        punct = a[-1] in ',.;:!?…—–'
        short = len(b.split()) == 1 or len(a.split()) == 1          # не лишати одне слово на рядку
        score = abs(i - mid) - (8 if punct else 0) + (12 if short else 0)
        if best is None or score < best[0]:
            best = (score, a, b)
    return '%s\n%s' % (best[1], best[2]) if best else t
