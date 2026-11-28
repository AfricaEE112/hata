"""Конвеєр нового ядра (крок 3): переклад по сценах → `accept` → адресні виправлення → фінальний `validate` → звіт.

Модель передається функцією `chat(system, user, schema, temp) -> str` (текст JSON-відповіді), тож конвеєр не знає
про LM Studio чи Gemini і тестується фейковою моделлю. Помилки зв'язку з моделлю кидає сама `chat` — їх не ловимо:
VidBox вирішує, відкласти серію (TrWait) чи взяти іншого перекладача.
"""
import json
import re
import time

from .lines import Issue, scenes
from .validate import SHIFT_MIN, accept, check_all, sim, validate

KEEP = ('credits', 'jp')   # лишаються як в оригіналі: подяки фансабу, японська й ромадзі (караоке)
PREV_CONTEXT = 8        # скільки вже перекладених попередніх реплік показувати моделі (узгодженість звертань)
FIX_GROUP = 6           # скільки проблемних реплік в одному запиті виправлення
FIX_TEMPS = (0.3, 0.6, 0.9)

ITEM = {'type': 'object', 'required': ['n', 'src', 'who', 'to', 'uk'], 'properties': {
    'n': {'type': 'integer'}, 'src': {'type': 'string'}, 'who': {'type': 'string'}, 'to': {'type': 'string'},
    'uk': {'type': 'string'}}}


def schema(count, scene_flag=False):
    props = {'lines': {'type': 'array', 'minItems': count, 'maxItems': count, 'items': ITEM}}
    req = ['lines']
    if scene_flag:
        props = dict({'sexual': {'type': 'boolean'}}, **props)    # спершу оцінка сцени, потім переклад
        req = ['sexual', 'lines']
    return {'type': 'object', 'required': req, 'properties': props}


RULES = ('For every item: "src" — copy the first two words of line n exactly as written (proof that you are on the '
         'right line; translate THAT line, not a neighbour); "who" — who says it, "to" — who it is said to (names from '
         'the character list, or "man" / "woman" / "?"); then "uk" — the speaker\'s own forms by "who", «ти»-forms and '
         'vocatives by "to". Never merge, split, skip or repeat lines: if a sentence goes on in the next line, '
         'translate each part in its own line. Lines marked "sign" are on-screen text (titles, signs): translate them '
         'briefly, as a sign.')


REVIEW_BATCH = 35
REVIEW_SCHEMA = {'type': 'object', 'required': ['errors'], 'properties': {'errors': {'type': 'array', 'items': {
    'type': 'object', 'required': ['n', 'src', 'issue', 'uk'], 'properties': {
        'n': {'type': 'integer'}, 'src': {'type': 'string'}, 'issue': {'type': 'string'}, 'uk': {'type': 'string'}}}}}}


def parse(txt):
    txt = re.sub(r'<think>.*?</think>', '', str(txt or ''), flags=re.S).strip()
    m = re.search(r'\{.*\}', txt, re.S)
    try:
        j = json.loads(m.group(0) if m else txt)
    except (ValueError, TypeError):
        return {}
    return j if isinstance(j, dict) else {}


def _item(ln):
    d = {'n': ln.n, 'en': ln.en}
    if ln.kind == 'sign':
        d['kind'] = 'sign'
    if ln.cont:
        d['continues'] = True
    return d


def _done(lines, upto, k=PREV_CONTEXT):
    """Останні k уже прийнятих реплік перед номером upto — як приклади звертань і термінів."""
    out = [{'n': ln.n, 'en': ln.en, 'uk': ln.uk} for ln in lines[:upto] if ln.uk and ln.kind not in KEEP]
    return out[-k:]


def _apply(got, by_n, ctx, lines, stage, allowed):
    """Відповідь моделі → кандидати для своїх номерів. Повертає кількість прийнятих."""
    ok = 0
    seen = set()
    items = [g for g in got.get('lines') or [] if isinstance(g, dict)]
    dup = set()                     # той самий переклад для різних оригіналів у межах ±4 — модель з'їхала
    for a in range(len(items)):
        for b in range(a + 1, min(len(items), a + 5)):
            try:
                na, nb = int(items[a].get('n')), int(items[b].get('n'))
            except (TypeError, ValueError):
                continue
            ua, ub = str(items[a].get('uk') or ''), str(items[b].get('uk') or '')
            if na in by_n and nb in by_n and len(ua) >= SHIFT_MIN and sim(ua, ub) > 0.8 and \
                    sim(by_n[na].en, by_n[nb].en) < 0.6:
                dup.add(nb)
    for g in items:
        if not isinstance(g, dict):
            continue
        try:
            n = int(g.get('n'))
        except (TypeError, ValueError):
            continue
        if n not in allowed or n in seen or n not in by_n:
            continue
        seen.add(n)
        ln = by_n[n]
        who, to = str(g.get('who') or '').strip(), str(g.get('to') or '').strip()
        if who and who != '?':
            ln.who = who
        if to and to != '?':
            ln.to = to
        if n in dup:
            ln.cands.append({'uk': str(g.get('uk') or ''), 'stage': stage, 'ok': False, 'issues': [Issue(
                'shift', 'block', 'той самий переклад, що й у сусідньої репліки з іншим оригіналом — рядки переплутано'
            ).as_dict()]})
            continue
        if accept(ln, g.get('uk'), ctx, lines, stage=stage, echo=g.get('src', ''))[0]:
            ok += 1
    return ok


def _problem(ln, lex=None):
    """Чому останній кандидат відкинуто — текстом для підказки моделі (з підказками справжніх слів зі словника)."""
    if not ln.cands:
        return 'no translation was returned for this line'
    last = ln.cands[-1]
    msgs = [i['msg'] for i in last['issues'] if i['sev'] == 'block']
    bad = sorted({w for c in ln.cands for i in c['issues'] if i['code'] in ('spelling', 'russism') for w in i['words']})
    if bad and lex is not None:  # схожі справжні слова — модель часто знає слово, але пише з помилкою
        from .lexicon import suggest
        hints = ['«%s» → %s' % (w, ' / '.join('«%s»' % x for x in sg)) for w in bad
                 for sg in [suggest(lex, w)] if sg]
        if hints:
            msgs.append('можливо, малося на увазі (вибери за змістом або перефразуй): ' + '; '.join(hints))
    if bad:                     # модель вперто повторює ту саму форму — просимо обійти слово взагалі
        msgs.append('не вживай %s у жодній формі — заміни іншим простим загальновживаним словом або перебудуй '
                    'речення' % ', '.join('«%s»' % w for w in bad))
    return '; '.join(msgs) or 'rejected'


class Translator:
    def __init__(self, chat, ctx, system, hint='', ctx_text='', gloss_text=None, progress=None, rounds=3, log=None,
                 review=True, harden=None, state=None):
        self.chat, self.ctx, self.system = chat, ctx, system
        self.state = state               # шлях progress.json — продовження після обриву (світло, ПК заснув)
        self.resumed = 0
        self.review_on, self.harden = review, harden
        self.reviewed = self.hardened = 0
        self.hint, self.ctx_text = hint, ctx_text
        self.gloss_text = gloss_text or (lambda text: '')
        self.progress = progress or (lambda f: None)
        self.rounds = max(1, int(rounds))
        self.log = log if log is not None else []
        self.calls = 0

    def ask(self, user, sch, temp):
        self.calls += 1
        t = time.time()
        txt = self.chat(self.system, user, sch, temp)
        self.log.append({'secs': round(time.time() - t, 1), 'temp': temp})
        return parse(txt)

    def _head(self, text):
        g = self.gloss_text(text)
        return ((self.hint + '\n') if self.hint else '') + \
            (('\n' + self.ctx_text + '\n') if self.ctx_text else '') + \
            (('\nGlossary and notes from the viewer — follow them strictly (names, terms, how characters address each '
              'other):\n' + g + '\n') if g else '')

    # ---------- 1. переклад сцени ----------
    def scene(self, sc, lines):
        work = [ln for ln in sc if ln.en.strip() and ln.kind not in KEEP]
        for ln in sc:
            if ln.kind in KEEP:
                ln.uk, ln.status = ln.en, 'ok'
        if not work:
            return
        by_n = {ln.n: ln for ln in work}
        text = '\n'.join(ln.en for ln in work)
        user = ('Translate every item of "lines" into natural, spoken Ukrainian that fits the scene; keep names and the '
                'tone. First decide "sexual": true if this scene is sexual (sex, foreplay, masturbation), false '
                'otherwise — outside sexual scenes words like "come", "finish", "cream" keep their everyday meaning '
                '(«прийти», «закінчити»). Return JSON {"sexual": <bool>, "lines": [{"n", "src", "who", "to", "uk"}, …]} — '
                'exactly one item per input line, the same n, in the same order. %s\n"done" holds the previous lines '
                'already translated — keep names, forms of address and terms consistent with them; do not translate '
                'them again.\n%s\n%s'
                % (RULES, self._head(text),
                   json.dumps({'done': _done(lines, work[0].n), 'lines': [_item(ln) for ln in work]}, ensure_ascii=False)))
        got = self.ask(user, schema(len(work), True), 0.3)
        if isinstance(got.get('sexual'), bool):
            rng = (work[0].n, work[-1].n)
            if self.ctx.sex_ranges is None:
                self.ctx.sex_ranges = []
            if got['sexual']:
                self.ctx.sex_ranges.append(rng)
        _apply(got, by_n, self.ctx, lines, 'scene', set(by_n))

    # ---------- 2. адресні виправлення ----------
    def fix(self, bad, lines, temp, stage, fresh=False):
        by_n = {ln.n: ln for ln in bad}
        for i in range(0, len(bad), FIX_GROUP):
            grp = bad[i:i + FIX_GROUP]
            ns = {ln.n for ln in grp}
            near = sorted({k for ln in grp for k in range(ln.n - 2, ln.n + 3)} - ns)
            ctx_lines = [{'n': lines[k].n, 'en': lines[k].en, 'uk': lines[k].uk} for k in near
                         if 0 <= k < len(lines) and lines[k].en.strip()]
            items = []
            for ln in grp:
                d = _item(ln)
                if not fresh:            # незалежна спроба — без минулих невдач, щоб модель не «прилипала» до них
                    tried = [c['uk'] for c in ln.cands if c['uk']][-2:]
                    if tried:
                        d['rejected'] = tried
                    d['problem'] = _problem(ln, self.ctx.lex)
                if ln.who:
                    d['who'] = ln.who
                if ln.to:
                    d['to'] = ln.to
                items.append(d)
            text = '\n'.join(ln.en for ln in grp)
            if fresh:
                user = ('Translate each item of "lines" into correct, natural spoken Ukrainian, from scratch. Use only '
                        'real, common Ukrainian words (no invented words, no Russian, no English left over); keep names '
                        'and the tone of the scene. Return JSON {"lines": [{"n", "src", "who", "to", "uk"}, …]} — one '
                        'item per input item, the same n. %s\n"around" are neighbouring lines for context only.\n%s\n%s'
                        % (RULES, self._head(text), json.dumps({'around': ctx_lines, 'lines': items}, ensure_ascii=False)))
                got = self.ask(user, schema(len(grp)), temp)
                _apply(got, by_n, self.ctx, lines, stage, ns)
                continue
            user = ('These subtitle lines failed automatic checks. Translate each item again into correct, natural '
                    'Ukrainian, fixing exactly the "problem" (it is written in Ukrainian); "rejected" are earlier '
                    'attempts that must not be repeated. Use only real Ukrainian words (no invented words, no Russian, '
                    'no English left over). Return JSON {"lines": [{"n", "src", "who", "to", "uk"}, …]} — one item per '
                    'input item, the same n. %s\n"around" are neighbouring lines for context only.\n%s\n%s'
                    % (RULES, self._head(text),
                       json.dumps({'around': ctx_lines, 'lines': items}, ensure_ascii=False)))
            got = self.ask(user, schema(len(grp)), temp)
            _apply(got, by_n, self.ctx, lines, stage, ns)

    # ---------- 3. «жорсткіше» (пропозиції ззовні, напр. tr_harden у VidBox) ----------
    def harden_pass(self, lines):
        work = [ln for ln in lines if ln.uk and ln.kind not in KEEP]
        if not self.harden or not work:
            return
        cur = [ln.uk for ln in work]
        hard = self.harden([ln.en for ln in work], list(cur)) or cur
        for ln, old_uk, new_uk in zip(work, cur, hard):
            if new_uk and new_uk != old_uk:
                if accept(ln, new_uk, self.ctx, lines, stage='harden')[0]:
                    self.hardened += 1
                else:
                    ln.uk = old_uk

    # ---------- 4. рецензент змісту ----------
    def review(self, lines):
        """Модель перечитує пари оригінал → переклад і повертає лише репліки зі справжніми помилками сенсу.
        Виправлення приймається, лише якщо проходить accept і схоже на свій переклад більше, ніж на сусідні."""
        work = [ln for ln in lines if ln.uk and ln.en.strip() and ln.kind not in KEEP]
        for i in range(0, len(work), REVIEW_BATCH):
            grp = work[i:i + REVIEW_BATCH]
            by_n = {ln.n: ln for ln in grp}
            items = []
            for ln in grp:
                d = {'n': ln.n, 'en': ln.en, 'uk': ln.uk}
                if ln.who:
                    d['who'] = ln.who
                if ln.to:
                    d['to'] = ln.to
                if self.ctx.sex_ranges is not None:
                    d['sex_scene'] = self.ctx.in_sex(ln.n)
                warn = [x.msg for x in ln.issues if x.sev == 'warn' and x.code not in ('unknown_name', 'too_long')]
                if warn:
                    d['check'] = '; '.join(warn)
                items.append(d)
            text = '\n'.join(ln.en for ln in grp)
            user = ('You are the editor of these Ukrainian subtitles. Compare every "uk" with its English "en" in '
                    'context and report ONLY real errors: wrong meaning (a word taken in the wrong sense for this '
                    'scene: CPR is «штучне дихання», "finish the order" is «доробити / закінчити замовлення», "sip" '
                    'is «ковток»), sexual wording where the scene is not sexual ("sex_scene": false) or missing where '
                    'it is, wrong gender of the speaker ("who") or listener ("to"), a wrong name, a line that '
                    'translates its neighbour instead of itself, words that are not Ukrainian. Lines with "check" '
                    'were flagged by an automatic check — confirm and fix, or leave them if they are right. Do NOT '
                    'report style preferences and do NOT soften crude language. For each error return {"n", "src" '
                    '(first two words of that en line), "issue" (short, in Ukrainian), "uk" (the corrected full '
                    'line)}. If everything is right, return {"errors": []}.\n%s\n%s'
                    % (self._head(text), json.dumps({'lines': items}, ensure_ascii=False)))
            got = self.ask(user, REVIEW_SCHEMA, 0.2)
            seen = set()
            for e in got.get('errors') or []:
                if not isinstance(e, dict):
                    continue
                try:
                    n = int(e.get('n'))
                except (TypeError, ValueError):
                    continue
                ln = by_n.get(n)
                fix = str(e.get('uk') or '').strip()
                if not ln or n in seen or not fix or fix == ln.uk:
                    continue
                seen.add(n)
                own = sim(fix, ln.uk)
                near = [o.uk for o in lines[max(0, n - 3):n + 4] if o.n != n and o.uk]
                if near and max(sim(fix, x) for x in near) > own and own < 0.5:
                    ln.cands.append({'uk': fix, 'stage': 'review', 'ok': False, 'issues': [Issue(
                        'shift', 'block', 'виправлення рецензента схоже на сусідню репліку').as_dict()]})
                    continue
                old_uk = ln.uk
                ok, _ = accept(ln, fix, self.ctx, lines, stage='review', echo=e.get('src', ''))
                if ok:
                    ln.cands[-1]['why'] = str(e.get('issue') or '')[:200]
                    self.reviewed += 1
                else:
                    ln.uk = old_uk

    def pending(self, lines):
        return [ln for ln in lines if ln.en.strip() and ln.kind not in KEEP and not ln.uk]

    # ---------- продовження після обриву ----------
    def _key(self, lines):
        import hashlib
        return hashlib.sha1('\n'.join(ln.en for ln in lines).encode('utf-8')).hexdigest()[:16]

    def save(self, lines, stage):
        if not self.state:
            return
        import os
        data = {'key': self._key(lines), 'stage': stage, 'at': time.time(),
                'sex': [list(x) for x in self.ctx.sex_ranges] if self.ctx.sex_ranges is not None else None,
                'lines': [{'n': ln.n, 'uk': ln.uk, 'who': ln.who, 'to': ln.to, 'echo': getattr(ln, 'echo_ok', False),
                           'cands': ln.cands[-4:]} for ln in lines if ln.uk or ln.cands]}
        try:
            with open(self.state + '.tmp', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(self.state + '.tmp', self.state)
        except OSError:
            pass

    def load(self, lines):
        """Уже прийняті переклади з минулої спроби тієї самої серії (той самий оригінал) — щоб не перекладати знову."""
        if not self.state:
            return 0
        try:
            with open(self.state, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return 0
        if data.get('key') != self._key(lines):
            return 0
        by_n = {ln.n: ln for ln in lines}
        k = 0
        for d in data.get('lines') or []:
            ln = by_n.get(d.get('n'))
            if not ln:
                continue
            ln.who, ln.to, ln.cands = d.get('who', ''), d.get('to', ''), list(d.get('cands') or [])
            if d.get('uk'):
                ln.uk, ln.echo_ok = d['uk'], bool(d.get('echo'))
                ln.status = 'ok'
                k += 1
        if data.get('sex') is not None:
            self.ctx.sex_ranges = [tuple(x) for x in data['sex']]
        return k

    def run(self, lines):
        sc = scenes(lines)
        total = len(sc) + self.rounds + 2
        self.resumed = self.load(lines)
        for i, s in enumerate(sc):
            work = [ln for ln in s if ln.en.strip() and ln.kind not in KEEP]
            if self.resumed and work and all(ln.uk or ln.cands for ln in work):
                continue                 # цю сцену вже перекладено до обриву
            self.scene(s, lines)
            self.save(lines, 'scene%d' % i)
            self.progress((i + 1) / total)
        for r in range(self.rounds):
            bad = self.pending(lines)
            if not bad:
                break
            self.fix(bad, lines, FIX_TEMPS[min(r, len(FIX_TEMPS) - 1)], 'fix%d' % (r + 1))
            self.save(lines, 'fix%d' % (r + 1))
            self.progress((len(sc) + r + 1) / total)
        # зсув між уже прийнятими репліками (A прийнято раніше, B — пізніше з тим самим текстом)
        cross = check_all(lines, self.ctx)
        again = [ln for ln in lines if any(i.code == 'shift' and i.sev == 'block' for i in cross.get(ln.n, []))]
        for ln in again:
            ln.cands.append({'uk': ln.uk, 'stage': 'final', 'ok': False,
                             'issues': [i.as_dict() for i in cross[ln.n]]})
            ln.uk = ''
        if again:
            self.fix(again, lines, FIX_TEMPS[-1], 'fix-shift')
        for ln in self.pending(lines):           # нічого не пройшло — найменш погана спроба, інакше оригінал
            best = sorted((c for c in ln.cands if c['uk']), key=lambda c: (
                any(i['code'] in ('shift', 'echo', 'empty') for i in c['issues']),
                sum(i['sev'] == 'block' for i in c['issues'])))
            ln.uk = best[0]['uk'] if best else ln.en
        self.harden_pass(lines)
        if self.review_on:
            validate(lines, self.ctx)            # свіжі warn — рецензенту як «check»
            self.review(lines)
        self.progress(1.0)
        return validate(lines, self.ctx)


def refix(lines, ctx, chat, system, skip=(), **kw):
    """Довиправлення готової серії: `lines` з уже записаним `uk`. Перевіряє все поточними правилами; що не проходить —
    перекладає незалежно з нуля, потім ще раз з підказкою причини. Що так і не вийшло — лишається як було.
    Повертає (звіт, скільки виправлено)."""
    t = Translator(chat, ctx, system, review=False, **kw)
    validate(lines, ctx)
    bad = [ln for ln in lines if ln.status == 'failed' and ln.en.strip() and ln.kind not in KEEP and ln.n not in skip]
    old = {ln.n: ln.uk for ln in bad}
    for ln in bad:
        ln.uk = ''
    if bad:
        t.fix(bad, lines, 0.5, 'refix', fresh=True)
        more = t.pending(lines)
        if more:
            t.fix(more, lines, 0.8, 'refix2')
    fixed = 0
    for ln in bad:
        if ln.uk:
            fixed += 1
        else:
            ln.uk = old[ln.n]                # не вийшло — лишається попередній текст
    rep = validate(lines, ctx)
    rep['meta'].update(core='new', calls=t.calls)
    return rep, fixed


def translate(lines, ctx, chat, system, **kw):
    """Перекласти репліки (`Line`, з `prepare`) на місці. Повертає звіт для qa.json."""
    t = Translator(chat, ctx, system, **kw)
    t0 = time.time()
    rep = t.run(lines)
    if t.state:
        import os
        try:
            os.remove(t.state)               # готово — продовжувати нічого
        except OSError:
            pass
    rep['meta'].update(core='new', calls=t.calls, secs=round(time.time() - t0, 1), reviewed=t.reviewed, resumed=t.resumed,
                       hardened=t.hardened, review=t.review_on,
                       accepted_first=sum(1 for ln in lines if ln.cands and ln.cands[0]['ok']),
                       sexual=[list(x) for x in ctx.sex_ranges or []])
    return rep
