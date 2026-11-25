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
    kind: str = 'dialog'    # 'dialog' | 'sign' (напис, табличка) | 'song' | 'credits' (подяки — не перекладаємо)
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


CREDITS = re.compile(r'(?i)\b(translated by|translation by|subtitles by|subbed by|encoded by|encoding|typeset|'
                     r'timing by|special thanks|upscaled by|raws? by|a [\w.-]+ project)\b')


def _kind(text, overlap):
    if CREDITS.search(text):
        return 'credits'
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
