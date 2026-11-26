"""Тест «Перевірити модель»: сталий набір реплік (`qa/benchmark.json`) → переклад будь-яким ядром → оцінка.

Репліка зарахована, якщо `validate` не знайшов блокувальних проблем (зсув, описки, русизми, рід, гоноративи…)
і виконано очікування набору: `any` — хоч один регекс знайдено, `all` — усі, `none` — жодного.
Оцінка = зараховані / усі, у відсотках. Результати зберігаються, щоб порівнювати ядра й моделі між собою.
"""
import json
import os
import re
import time

from .lexicon import QA_DIR
from .lines import prepare
from .validate import Ctx, validate

BENCH_PATH = os.path.join(QA_DIR, 'benchmark.json')
GENDER = {'m': 'masc', 'f': 'femn', 'masc': 'masc', 'femn': 'femn'}


def load(path=None):
    with open(path or BENCH_PATH, encoding='utf-8') as f:
        return json.load(f)


def case_chars(case):
    return [{'en': c.get('en', ''), 'uk': c.get('uk', ''), 'gender': GENDER.get(c.get('gender')),
             'aliases': list(c.get('aliases') or [])} for c in case.get('chars') or []]


def case_segs(case):
    """Синтетичні таймінги: репліки по 3 с з паузою 1 с — уся сцена одна, як у живій серії."""
    return [(i * 4.0, i * 4.0 + 3.0, ln['en']) for i, ln in enumerate(case['lines'])]


def expect_fails(spec, uk):
    out = []
    any_ = spec.get('any') or []
    if any_ and not any(re.search(p, uk, re.I) for p in any_):
        out.append('немає жодного з: %s' % ', '.join(any_[:6]))
    for p in spec.get('all') or []:
        if not re.search(p, uk, re.I):
            out.append('немає «%s»' % p)
    for p in spec.get('none') or []:
        m = re.search(p, uk, re.I)
        if m:
            out.append('є заборонене «%s»' % m.group(0))
    return out


def score_case(case, outs, gloss=(), forbid=(), diag=None):
    lines = prepare(case_segs(case))
    for ln, spec, uk in zip(lines, case['lines'], list(outs) + [''] * len(lines)):
        ln.who, ln.to, ln.uk = spec.get('who', ''), spec.get('to', ''), str(uk or '').strip()
    sex = case.get('sex')
    ctx = Ctx(chars=case_chars(case), gloss=list(gloss), forbid=list(forbid),
              sex_ranges=[tuple(x) for x in sex] if sex is not None else None)
    validate(lines, ctx)
    res = []
    for ln, spec in zip(lines, case['lines']):
        exp = expect_fails(spec, ln.uk) if ln.uk else []
        blocks = [i.msg for i in ln.issues if i.sev == 'block']
        warns = [i.msg for i in ln.issues if i.sev == 'warn']
        r = {'n': ln.n, 'en': ln.en, 'uk': ln.uk, 'ok': not blocks and not exp,
             'expect': exp, 'block': blocks, 'warn': warns, 'codes': [i.code for i in ln.issues],
             'why': spec.get('why', '')}
        if diag and ln.n < len(diag) and diag[ln.n]:    # що бачило ядро: мовець за моделлю, спроби, статус
            r['core'] = diag[ln.n]
        res.append(r)
    return {'id': case['id'], 'title': case.get('title', ''), 'lines': res,
            'passed': sum(r['ok'] for r in res), 'total': len(res)}


def summarize(results, meta=None):
    passed = sum(r['passed'] for r in results)
    total = sum(r['total'] for r in results)
    codes, exp_fail = {}, 0
    fails = []
    for r in results:
        for ln in r['lines']:
            for c in ln['codes']:
                codes[c] = codes.get(c, 0) + 1
            if ln['expect']:
                exp_fail += 1
            if not ln['ok']:
                fails.append(dict(ln, case=r['id']))
    return {'version': 1, 'meta': dict(meta or {}), 'score': round(100.0 * passed / total, 1) if total else 0.0,
            'passed': passed, 'total': total, 'expect_failed': exp_fail,
            'warn': sum(1 for r in results for ln in r['lines'] if ln['warn']),
            'codes': codes, 'cases': [{'id': r['id'], 'passed': r['passed'], 'total': r['total'],
                                       'secs': r.get('secs'), 'error': r.get('error')} for r in results],
            'fails': fails}


def run(translate, gloss_for=lambda case: ((), ()), bench=None, progress=None, meta=None, should_stop=None):
    """translate(case) → список перекладів у порядку `case['lines']`. gloss_for(case) → (пункти глосарію, forbid).
    Помилка перекладу сцени не зупиняє тест: сцена рахується проваленою, причина — у звіті."""
    bench = bench or load()
    cases = bench['cases']
    results, t0 = [], time.time()
    for i, case in enumerate(cases):
        if should_stop and should_stop():
            break
        t = time.time()
        err = None
        diag = None
        try:
            got = translate(case)
            if isinstance(got, dict):
                outs, diag = list(got.get('uk') or []), got.get('diag')
            else:
                outs = list(got)
        except Exception as e:          # noqa: BLE001 — модель недоступна, обрив тощо
            outs, err = [], str(e)[:300]
        gloss, forbid = gloss_for(case)
        r = score_case(case, outs, gloss, forbid, diag)
        r['secs'], r['error'] = round(time.time() - t, 1), err
        results.append(r)
        if progress:
            progress((i + 1) / len(cases))
    return summarize(results, dict(meta or {}, secs=round(time.time() - t0, 1), cases=len(cases),
                                   finished=len(results) == len(cases)))
