"""`validate` — єдина перевірка перекладу правилами, без моделі.

Нею користуються всі етапи нового ядра: кандидат від моделі приймається (`accept`), лише якщо в ньому
немає проблем рівня 'block'. Фінальний прохід (`validate`) проганяє її по всьому файлу ще раз, разом із
перевірками між репліками (зсув, дублі, узгодженість), і заповнює звіт.
"""
import difflib
import re
from dataclasses import dataclass, field

from .autofix import autofix
from .lexicon import Lexicon, WORD_RE, is_cyr, norm_apos
from .lines import Issue

PARTICLES = {'не', 'ні', 'вже', 'так', 'теж', 'також', 'ж', 'же', 'ще', 'просто', 'справді', 'тоді', 'аж', 'навіть',
             'лише', 'тільки', 'все', 'усе', 'б', 'би', 'було', 'дійсно', 'зовсім', 'аж', 'ось', 'теж', 'взагалі',
             'точно', 'що', 'майже', 'досі', 'знову', 'знов', 'колись', 'одразу', 'відразу', 'нарешті', 'й', 'і', 'та'}
INTERJ = set('аеєиіїоуюяхмгфвйнь')
EN_COMMON = {'The', 'And', 'But', 'You', 'Your', 'This', 'That', 'What', 'When', 'Why', 'How', 'Who', 'Mom', 'Dad',
             'Mommy', 'Daddy', 'Sis', 'Big', 'Little', 'Hey', 'Okay', 'Yes', 'Mister', 'Miss', 'Ma', 'Sir', 'Mr', 'Mrs',
             'God', 'Gosh', 'Oh', 'Wow', 'Please', 'Sorry', 'Thank', 'Thanks', 'Good', 'Well', 'Now', 'Then', 'Not',
             'Don', 'Can', 'Let', 'Wait', 'Stop', 'Come', 'Look', 'Huh', 'Uh', 'Um', 'Ah', 'Ugh', 'Man', 'Boss',
             'Teacher', 'Sensei', 'Senpai', 'Master', 'Lady', 'Princess', 'Queen', 'King', 'Lord', 'Ma\'am'}
LATIN_OK = {'ok', 'wi-fi', 'wifi', 'tv', 'sms', 'dj', 'vip', 'pc', 'cd', 'dvd', 'usb', 'id'}
HONORIFIC = re.compile(r"(?i)-(сан|кун|чан|тян|сама|доно|семпай|сенпай)(у|а|ом|ові|і|е|ом)?$")
SEX_STEMS = ('кінч', 'трах', 'дроч', 'сперм', 'мінет', 'кремпі', 'їба', 'єба')
GENDER_UK = {'masc': 'чоловік', 'femn': 'жінка'}
NOTE_FORBID = re.compile(r'не\s+[«"“]([^»"”]+)[»"”]', re.I)
NAME_STEM = re.compile(r'[аяеєиіїоуюй]$', re.I)


@dataclass
class Ctx:
    """Контекст серії для перевірок. chars: [{'en': 'Daisuke', 'uk': 'Дайсуке', 'gender': 'masc'|'femn'|None,
    'aliases': [...]}]; gloss: пункти глосарію [en, uk, reg, note]; forbid: скомпільовані регекси з наборів;
    sex_ranges: [(n1, n2)] сексуальних сцен або None (невідомо — правило не застосовується)."""
    chars: list = field(default_factory=list)
    gloss: list = field(default_factory=list)
    forbid: list = field(default_factory=list)
    sex_ranges: list = None
    lex: Lexicon = None

    def __post_init__(self):
        self.lex = self.lex or Lexicon.get()
        self._names = []                     # (стем у нижньому регістрі, персонаж)
        for c in self.chars:
            for nm in [c.get('uk')] + list(c.get('aliases_uk') or []):
                for part in re.split(r'[\s/]+', str(nm or '')):
                    p = part.lower()
                    if not p[:1].isalpha() or not part[:1].isupper() or self._common(p):
                        continue             # «Клієнт», «Мама» — не імена
                    stem = NAME_STEM.sub('', p) if len(p) > 4 else p
                    if len(stem) >= 2:
                        self._names.append((stem, c))
        self._gloss_words = set()
        for it in self.gloss:
            for v in re.split(r'\s*/\s*', str(it[1] if len(it) > 1 else '')):
                for w in WORD_RE.findall(v):
                    self._gloss_words.add(norm_apos(w.lower()))

    def _common(self, w):
        """Звичайне слово словника, а не ім'я («клієнт», «сестра»)."""
        if not self.lex.ok or not self.lex.known(w):
            return False
        return not any('Name' in str(p.tag) or 'Surn' in str(p.tag) for p in self.lex.parses(w))

    GENERIC = {'man': 'masc', 'boy': 'masc', 'male': 'masc', 'чоловік': 'masc', 'хлопець': 'masc',
               'woman': 'femn', 'girl': 'femn', 'female': 'femn', 'жінка': 'femn', 'дівчина': 'femn'}

    def gloss_fix(self, uk):
        """Англійський термін глосарію лишився латиницею («О, це що, doujinshi?») → перший варіант з глосарію."""
        if not re.search(r'[A-Za-z]{3,}', uk):
            return uk
        for it in self.gloss:
            en, tr = (it[0] if it else ''), (it[1] if len(it) > 1 else '')
            if not en or not tr or not re.fullmatch(r"[A-Za-z][A-Za-z' -]+", en):
                continue
            first = re.split(r'\s*/\s*', tr)[0].strip()
            if not first or re.search('[A-Za-z]', first):
                continue
            uk = re.sub(r'(?i)\b%s\b' % re.escape(en), lambda m: first[:1].upper() + first[1:]
                        if m.group(0)[:1].isupper() else first, uk)
        return uk

    def vocatives(self):
        """Кличні форми японських імен, яких не має бути: «Така» → «Тако», «Кадзуя» → «Кадзує», «Юкі» не змінюється."""
        out = {}
        for c in self.chars:
            uk = str(c.get('uk') or '').strip()
            if not uk or ' ' in uk or not uk[:1].isupper():
                continue
            if self.lex.ok and self.lex.known(uk) and \
                    any(p.tag.POS == 'NOUN' and 'Name' not in str(p.tag) for p in self.lex.parses(uk)):
                continue                 # «Клієнт», «Мама» — звичайні іменники, їх кличний правильний
            low = uk.lower()
            forms = set()
            if low.endswith('а'):
                forms |= {low[:-1] + 'о', low[:-1] + 'у'}
            elif low.endswith('я'):
                forms |= {low[:-1] + 'є', low[:-1] + 'ю'}
            elif low[-1:] not in 'аеєиіїоуюяь':
                forms |= {low + 'е', low + 'у'}
            for f in forms:
                out[f] = (uk, c)
        return out

    def char(self, name):
        """Персонаж за іменем від аналізу чи моделі: «Aika», «Айка», «Aika (Sis)», «Kazuya-kun»; «man»/«woman» —
        лише стать."""
        n = str(name or '').strip().lower()
        if not n or n == '?':
            return None
        if n in self.GENERIC:
            return {'en': n, 'uk': n, 'gender': self.GENERIC[n]}
        keys = {n} | set(re.split(r'[\s()/,-]+', n)) - {''}
        for c in self.chars:
            names = {str(c.get('en') or '').lower(), str(c.get('uk') or '').lower()} | \
                {str(a).lower() for a in (c.get('aliases') or []) + (c.get('aliases_uk') or [])}
            if keys & (names - {''}):
                return c
        return None

    def name_of(self, w):
        if not w[:1].isupper():          # «таку» (прикметник) — не «Таку»
            return None
        wl = w.lower()
        for stem, c in self._names:
            if wl.startswith(stem) and len(wl) - len(stem) <= 4:
                return c
        return None

    def in_sex(self, n):
        return any(a <= n <= b for a, b in self.sex_ranges or [])


def sim(a, b):
    return difflib.SequenceMatcher(None, str(a or '').lower(), str(b or '').lower()).ratio()


def echo_norm(x):
    x = re.sub(r'(?i)\b(\w{1,2})-(?=\1)', '', str(x or ''))       # заїкання «L-Like» → «Like»
    return re.sub(r'[\W_]+', '', x.lower())


def echo_ok(echo, en):
    """Чи `src` з відповіді моделі — справді початок оригіналу цієї репліки (захист від зсуву). Нестрого:
    модель може прибрати заїкання чи лапки. Порожнє echo — НЕ приймаємо (у новому ядрі воно обов'язкове)."""
    a, b = echo_norm(echo), echo_norm(en)
    if not b:
        return True
    if not a:
        return False
    return a[:6] in b[:16] or b[:6] in a[:16]


def _interj(w):
    parts = [re.sub(r'(.)\1+', r'\1', p) for p in w.lower().split('-') if p]
    return bool(parts) and all(len(p) <= 3 and set(p) <= INTERJ for p in parts)


def _destutter(w):
    """«С-сестро» → «сестро», «Се-сестро» → «сестро», «П-будь» → «будь»."""
    while '-' in w:
        a, b = w.split('-', 1)
        if b and len(a) <= 2 and (len(a) == 1 or b.lower().startswith(a.lower())):
            w = b
        else:
            break
    return w


def _word_ok(w, ctx):
    """True — слово правильне; False — нема в словнику; None — судити не можна (нема словника)."""
    if _interj(w) or ctx.name_of(w) or norm_apos(w.lower()) in ctx._gloss_words:
        return True
    w2 = _destutter(w)
    if w2 != w and (_interj(w2) or ctx.name_of(w2) or norm_apos(w2.lower()) in ctx._gloss_words):
        return True
    k = ctx.lex.known(w2)
    if k is False and '-' in w2:                       # розтягнуте «га-а-аразд», «Ні-і-і»
        joined = w2.replace('-', '')
        k = ctx.lex.known(re.sub(r'(.)\1+', r'\1', joined)) or ctx.lex.known(joined)
    return k


def _tokens(text):
    """[(слово, чи початок речення)]."""
    out = []
    for m in WORD_RE.finditer(text):
        before = text[:m.start()].rstrip(' "«“(\'')
        cut = text[m.end():m.end() + 1] in ('—', '–')        # обірване «Я кінч—»
        out.append((m.group(0), not before or before[-1] in '.!?…—–-\n', cut))
    return out


def check_line(ln, uk, ctx):
    """Проблеми одного кандидата `uk` для репліки `ln` (без сусідів)."""
    iss = []
    uk = str(uk or '').strip()
    if ln.kind == 'credits':
        return []
    if not uk:
        return [Issue('empty', 'block', 'порожній переклад')] if ln.en.strip() else []
    lex = ctx.lex
    toks3 = _tokens(uk)
    toks = [(w, f) for w, f, _ in toks3]
    cut = {w for w, _, c in toks3 if c}
    en_low = ln.en.lower()

    # --- мова: латиниця, інші абетки, російське ---
    latin = [w for w, _ in toks if any(c.isalpha() and c.isascii() for c in w)]
    letters = [c for c in uk if c.isalpha()]
    if letters and sum(c.isascii() for c in letters) / len(letters) > 0.5 and len(re.findall(r'[A-Za-z]{2,}', ln.en)) >= 2:
        iss.append(Issue('untranslated', 'block', 'репліку не перекладено (лишилась англійською)'))
    else:
        mixed = [w for w in latin if any('Ѐ' <= c <= 'ӿ' for c in w)]
        alien = [w for w, _ in toks if any(c.isalpha() and not c.isascii() and not ('Ѐ' <= c <= 'ӿ') for c in w)]
        stray = [w for w in latin if w not in mixed and w.lower() not in LATIN_OK and w.lower() not in en_low]
        if mixed or alien:
            iss.append(Issue('mixed_script', 'block', 'слова з літерами інших абеток: %s' % ', '.join(mixed + alien),
                             tuple(mixed + alien)))
        if stray:
            iss.append(Issue('latin', 'block', 'латиниця в перекладі: %s' % ', '.join(stray), tuple(stray)))
    rus = [w for w, _ in toks if is_cyr(w) and lex.russism(w)]
    if rus:
        iss.append(Issue('russism', 'block', 'російські слова чи русизми: %s — заміни українськими' % ', '.join(rus),
                         tuple(rus)))

    # --- заборони наборів глосаріїв ---
    bad = sorted({m.group(0) for rx in ctx.forbid for m in [rx.search(uk)] if m})
    if bad:
        iss.append(Issue('forbid', 'block', 'заборонений варіант: %s' % ', '.join(bad), tuple(bad)))
    for it in ctx.gloss:
        if len(it) < 4 or not it[0] or not re.search(r'(?i)\b%s\b' % re.escape(it[0]), ln.en):
            continue
        for x in NOTE_FORBID.findall(it[3] or ''):
            if x.strip() and re.search(r'(?i)\b%s' % re.escape(x.strip()[:max(4, len(x.strip()) - 2)]), uk):
                iss.append(Issue('gloss_forbid', 'block', '«%s» тут не «%s» (глосарій: %s)' % (it[0], x, it[1]), (x,)))

    # --- кличний відмінок японських імен («Тако» замість «Така») ---
    voc = ctx.vocatives()
    vbad = [(w, voc[w.lower()][0]) for w, _ in toks if w[:1].isupper() and w.lower() in voc
            and any(re.search(r'(?i)\b%s' % re.escape(p[:4]), ln.en) for p in re.findall(r'[A-Za-z]{3,}', str(
                voc[w.lower()][1].get('en') or '')))]
    if vbad:
        iss.append(Issue('name_form', 'block', 'японські імена не відмінюються в кличному: %s' % ', '.join(
            '«%s», а не «%s»' % (n, w) for w, n in vbad), tuple(w for w, _ in vbad)))

    # --- гоноративи ---
    hon = [w for w, _ in toks if HONORIFIC.search(w)]
    if hon:
        iss.append(Issue('honorific', 'block', 'японські суфікси (-сан, -кун, -чан) прибрати: %s' % ', '.join(hon),
                         tuple(hon)))

    # --- орфографія (словник) ---
    if lex.ok:
        typo, maybe_name = [], []
        # у оригіналі є імена (Matsuda-kun, Yoshi) або це титр/назва («Shinonome», «Nine-Tailed») — невідоме слово
        # з великої літери, найімовірніше, ім'я, а не описка
        en_names = re.findall(r"\b[A-Z][a-z]{2,}(?=-(?:kun|san|chan|sama|senpai|sensei)\b)", ln.en) or \
            [w for w in re.findall(r"(?<![.!?…]\s)(?<!^)\b[A-Z][a-z]{2,}", ln.en.strip()) if w not in EN_COMMON]
        title = len(ln.en.split()) <= 4 and not re.search(r'[.!?,]', ln.en) and \
            all(w[:1].isupper() for w in re.findall(r'[A-Za-z]+', ln.en))
        for w, first in toks:
            if not is_cyr(w) or w in hon or w in rus or w in cut:
                continue
            k = _word_ok(w, ctx)
            if k is False:
                (maybe_name if w[:1].isupper() and (not first or en_names or title) else typo).append(w)
        if typo:
            iss.append(Issue('spelling', 'block', '%s %s немає в українській — це описка чи вигадане слово'
                             % ('слова' if len(typo) == 1 else 'слів', ', '.join('«%s»' % w for w in typo)), tuple(typo)))
        if maybe_name:
            iss.append(Issue('unknown_name', 'warn', 'невідомі слова з великої літери: %s (ім\'я? додай у персонажі)'
                             % ', '.join(maybe_name), tuple(maybe_name)))

    # --- імена: укр. ім'я персонажа, якого нема в оригіналі ---
    for w, _ in toks:
        c = ctx.name_of(w)
        if not c:
            continue
        names_en = [c.get('en') or ''] + list(c.get('aliases') or [])
        parts = {p.lower() for n in names_en for p in re.findall(r'[A-Za-z]{3,}', str(n))}
        if parts and not any(re.search(r'(?i)\b%s' % re.escape(p[:4]), ln.en) for p in parts):
            iss.append(Issue('name_not_in_src', 'warn', 'в оригіналі немає імені %s — перевір, чи це той персонаж'
                             % (c.get('en') or c.get('uk')), (w,)))
            break

    # --- ім'я з оригіналу загубилось («Nine-Tailed Fox Courtesan: Ayame» → «Лисиця-куртизанка:») ---
    for c in ctx.chars:
        en_n = [p for p in re.findall(r'[A-Za-z]{3,}', str(c.get('en') or '')) if p[:1].isupper()]
        uk_n = str(c.get('uk') or '').split()
        if not en_n or not uk_n or not re.search(r'\b%s\b' % re.escape(en_n[0]), ln.en):
            continue
        stem = uk_n[0].lower()
        stem = NAME_STEM.sub('', stem) if len(stem) > 4 else stem
        if len(stem) >= 2 and not any(w.lower().startswith(stem) for w, _ in toks) and len(toks) >= 1:
            iss.append(Issue('name_missing', 'warn', 'в оригіналі є ім\'я %s, а в перекладі його немає' % uk_n[0],
                             (uk_n[0],)))
            break

    # --- рід: «я …» за мовцем, «ти …» за адресатом ---
    if lex.ok:
        low = [norm_apos(w.lower()) for w, _ in toks]
        for pron, who, label in (('я', ln.who, 'мовець'), ('ти', ln.to, 'адресат')):
            c = ctx.char(who)
            g = c and c.get('gender')
            if g not in ('masc', 'femn'):
                continue
            for i, w in enumerate(low):
                if w != pron:
                    continue
                j = i + 1
                while j < len(low) and low[j] in PARTICLES:
                    j += 1
                if j >= len(low):
                    continue
                g2 = lex.gender(low[j])
                if g2 and not any(p.tag.POS == 'VERB' for p in lex.parses(low[j])):
                    k = j + 1                   # «ти нестерпна розпещена дитина» — прикметники до іменника
                    while k < len(low) and k <= j + 3:
                        pos = {p.tag.POS for p in lex.parses(low[k])}
                        if 'NOUN' in pos and not pos & {'ADJF', 'ADJS', 'PRTF', 'ADVB', 'VERB'}:
                            g2 = None
                            break
                        if not pos & {'ADJF', 'PRTF'}:
                            break
                        k += 1
                if g2 and g2 != g:
                    iss.append(Issue('gender_' + ('who' if pron == 'я' else 'to'), 'block',
                                     '%s — %s (%s), а «%s %s» — %s рід' % (
                                         label, c.get('uk') or c.get('en'), GENDER_UK[g], pron, toks[j][0],
                                         'чоловічий' if g2 == 'masc' else 'жіночий'), (toks[j][0],)))
                    break

    # --- сексуальна лексика поза сексуальними сценами ---
    if ctx.sex_ranges is not None and not ctx.in_sex(ln.n):
        sx = [w for w, _ in toks if w.lower().startswith(SEX_STEMS)]
        if sx:
            iss.append(Issue('sex_context', 'warn', 'сексуальне слово поза сексуальною сценою: %s — перевір сенс '
                             '(finish/come тут можуть значити «закінчити»/«прийти»)' % ', '.join(sx), tuple(sx)))

    # --- довжина ---
    if len(ln.en) >= 12:
        r = len(uk) / len(ln.en)
        if r > 2.5:
            iss.append(Issue('too_long', 'warn', 'переклад у %.1f раза довший за оригінал' % r))
        elif r < 0.3:
            iss.append(Issue('too_short', 'warn', 'переклад набагато коротший за оригінал — щось пропущено?'))
    return iss


SHIFT_MIN = 20


def shift_against(ln, uk, others, both_verified=False):
    """Кандидат схожий на переклад сусідньої репліки з іншим оригіналом — модель переплутала рядки."""
    if len(uk) < SHIFT_MIN:             # «Я кінчаю!» кілька разів поспіль — нормально, не зсув
        return None
    for o in others:
        if o is ln or not o.uk or abs(o.n - ln.n) > 4:
            continue
        if both_verified and getattr(ln, 'echo_ok', False) and getattr(o, 'echo_ok', False):
            continue                     # обидві прийняті з правильним src — модель була на своїх рядках
        if sim(uk, o.uk) > 0.8 and sim(ln.en, o.en) < 0.6:
            return Issue('shift', 'block', 'переклад повторює репліку %d («%s») — схоже, рядки переплутано'
                         % (o.n, o.uk[:40]), (str(o.n),))
    return None


def accept(ln, uk, ctx, lines, stage='', echo=None):
    """Спробувати прийняти кандидата. Повертає (прийнято?, [Issue]). Усе записується в ln.cands."""
    uk = ctx.gloss_fix(autofix(str(uk or '').strip()))
    iss = []
    if echo is not None and not echo_ok(echo, ln.en):
        iss.append(Issue('echo', 'block', 'відповідь не для цієї репліки (src «%s»)' % str(echo)[:30]))
    iss += check_line(ln, uk, ctx)
    sh = shift_against(ln, uk, lines[max(0, ln.n - 4):ln.n + 5])
    if sh:
        iss.append(sh)
    ok = not any(i.sev == 'block' for i in iss)
    ln.cands.append({'uk': uk, 'stage': stage, 'ok': ok, 'issues': [i.as_dict() for i in iss]})
    if ok:
        ln.uk, ln.issues = uk, [i for i in iss if i.sev == 'warn']
        ln.echo_ok = echo is not None
        ln.status = 'warn' if ln.issues else 'ok'
    return ok, iss


def check_all(lines, ctx):
    """Перевірки між репліками на готовому файлі: {n: [Issue]}."""
    out = {}
    for ln in lines:
        if ln.uk:
            sh = shift_against(ln, ln.uk, lines[max(0, ln.n - 4):ln.n + 5], both_verified=True)
            if sh:
                out.setdefault(ln.n, []).append(sh)
    if ctx.lex.ok:                                  # «Папо!» і «тату» в одній серії
        papa = [ln for ln in lines if ln.uk and any('папа' in ctx.lex.lemmas(w) for w in WORD_RE.findall(ln.uk))]
        tato = [ln for ln in lines if ln.uk and any(l in ('тато', 'тат') for w in WORD_RE.findall(ln.uk)
                                                      for l in ctx.lex.lemmas(w))]
        if papa and tato:
            for ln in papa:
                out.setdefault(ln.n, []).append(Issue('inconsistent', 'warn', 'у серії є і «тато», і «папа» — '
                                                      'вибери одне (краще «тато»)'))
    return out


def validate(lines, ctx):
    """Фінальна перевірка всього файлу. Оновлює ln.issues/ln.status і повертає звіт (dict для qa.json)."""
    cross = check_all(lines, ctx)
    for ln in lines:
        if not ln.en.strip() or ln.kind == 'credits':
            ln.status, ln.issues = 'ok', []
            continue
        iss = (check_line(ln, ln.uk, ctx) if ln.uk else [Issue('empty', 'block', 'немає перекладу')]) + cross.get(ln.n, [])
        ln.issues = iss
        ln.status = 'failed' if any(i.sev == 'block' for i in iss) else ('warn' if iss else 'ok')
    return report(lines, ctx)


def _ts(t):
    t = int(t)
    return '%d:%02d:%02d' % (t // 3600, t // 60 % 60, t % 60)


def report(lines, ctx, meta=None):
    bad = [ln for ln in lines if ln.status in ('warn', 'failed')]
    codes = {}
    for ln in bad:
        for i in ln.issues:
            codes[i.code] = codes.get(i.code, 0) + 1
    return {
        'version': 1,
        'meta': dict(meta or {}, dict_ok=ctx.lex.ok, dict_why=ctx.lex.why),
        'total': sum(1 for ln in lines if ln.en.strip() and ln.kind != 'credits'),
        'failed': sum(1 for ln in bad if ln.status == 'failed'),
        'warn': sum(1 for ln in bad if ln.status == 'warn'),
        'codes': codes,
        'lines': [{'n': ln.n, 'time': _ts(ln.start), 'en': ln.en, 'uk': ln.uk, 'status': ln.status,
                   'who': ln.who, 'to': ln.to, 'tries': len(ln.cands),
                   'issues': [i.as_dict() for i in ln.issues]} for ln in bad],
    }
