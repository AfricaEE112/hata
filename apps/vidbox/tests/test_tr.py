"""Тести нового ядра перекладу, крок 1: репліки/сцени, автовиправлення, `validate`.

Запуск: `python apps/vidbox/tests/test_tr.py` (або pytest). Потрібні pymorphy3 і pymorphy3-dicts-uk;
без них тести словника пропускаються, а перевіряється, що все працює й без словника.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tr import Ctx, Lexicon, Line, accept, autofix, check_line, echo_ok, prepare, validate  # noqa: E402
from tr.validate import check_all  # noqa: E402

LEX = Lexicon.get()
HAVE_DICT = LEX.ok
CHARS = [{'en': 'Aika', 'uk': 'Айка', 'gender': 'femn'},
         {'en': 'Taku', 'uk': 'Таку', 'gender': 'masc', 'aliases': ['Takuya']},
         {'en': 'Daisuke', 'uk': 'Дайсуке', 'gender': 'masc'},
         {'en': 'Daiki', 'uk': 'Дайкі', 'gender': 'masc'},
         {'en': 'Customer', 'uk': 'Клієнт', 'gender': 'masc'}]
GLOSS = [['thug', 'хуліган / гопник', 'розмовне', 'не «шльондра»'], ['doujinshi', 'доджінші', '', '']]
import re  # noqa: E402
FORBID = [re.compile(x, re.I) for x in ['фініш', 'кічк']]


def ctx(**kw):
    return Ctx(chars=CHARS, gloss=GLOSS, forbid=FORBID, **kw)


def L(en, n=5, who='', to='', **kw):
    return Line(n=n, start=n * 3.0, end=n * 3.0 + 2, en=en, who=who, to=to, **kw)


def codes(iss):
    return {i.code for i in iss}


def blocks(iss):
    return {i.code for i in iss if i.sev == 'block'}


# ---------------- репліки й сцени ----------------
def test_prepare_scenes_and_kinds():
    segs = [(0, 2, 'Hello.'), (2.2, 4, 'How are you,'), (4.3, 6, 'my dear?'),
            (20, 22, 'HEAVY TITS'), (20.5, 23, 'Another scene starts.')]
    segs += [(30 + i * 3, 32 + i * 3, 'Line %d.' % i) for i in range(70)]
    segs += [(400, 405, 'A SakuraCircle Project / Translated by: X')]
    ls = prepare(segs)
    assert [l.n for l in ls] == list(range(len(segs))), 'номери незмінні'
    assert ls[1].cont and not ls[0].cont, 'речення через дві репліки'
    assert ls[3].kind == 'sign', 'CAPS-напис'
    assert ls[-1].kind == 'credits'
    assert ls[0].scene == ls[2].scene and ls[5].scene > ls[2].scene, 'пауза ділить сцени (дрібна сцена зливається)'
    sizes = {}
    for l in ls:
        sizes[l.scene] = sizes.get(l.scene, 0) + 1
    assert max(sizes.values()) <= 30, 'сцена не більша за пакет'


def test_prepare_keeps_empty_and_tags():
    ls = prepare([(0, 1, '<i>Hi</i>'), (1, 2, ''), (2, 3, '{\\an8}Top')])
    assert [l.en for l in ls] == ['Hi', '', 'Top'] and len(ls) == 3


# ---------------- автовиправлення ----------------
def test_autofix():
    assert autofix('Тобі не соромно перед Дайсуке-саном?') == 'Тобі не соромно перед Дайсуке?'
    assert autofix('Н-Нее-чан!') == 'С-сестричко!'
    assert autofix('Ладно, такой купальник') == 'Гаразд, такий купальник'
    assert autofix('Моя пізда') == 'Моя пизда'
    assert autofix('з самиdep глибини') == 'з сами глибини'
    assert autofix('Торкнися мою грудь') == 'Торкнися мої груди'
    assert autofix('Ти смоктаєш') == 'Ти смокчеш'


# ---------------- перевірка однієї репліки ----------------
def test_spelling_catches_invented_words():
    if not HAVE_DICT:
        return
    c = ctx()
    for uk, word in [('Що вона завагірніла від третьої дитини.', 'завагірніла'),
                     ('Ці стогніння мене зводять з розуму.', 'стогніння'),
                     ('Я така спрагшла!', 'спрагшла'),
                     ('Ти так на мене витрічався.', 'витрічався'),
                     ('Я ж застужуся!', None)]:
        iss = check_line(L('Something long enough here.'), uk, c)
        if word:
            assert 'spelling' in blocks(iss), (uk, iss)
            assert any(word in i.words for i in iss), (uk, iss)
    # «застужуся» виправляє autofix, тож через accept проходить
    ln = L('I\'m gonna catch a cold!')
    ok, _ = accept(ln, 'Я ж застужуся!', c, [ln])
    assert ok and ln.uk == 'Я ж застуджуся!'


def test_spelling_no_false_positives():
    if not HAVE_DICT:
        return
    c = ctx()
    for uk in ['А-ах! С-сестричко, М-м-м... Е-ей! Н-ні!', 'Уфф... Хм. Гм, ну-ну.',
               'Я кінчаю! Твоя пизда така тісна, кицька!', 'Айка, Таку, Дайсуке, Таку-у!',
               'Вже пізно, теж немає часу. Добраніч.', 'Г-га-а-аразд, я йду!', 'Т-Таку, ти вже тут?',
               'Ти мене дражниш, бляха-муха.', 'Це доджінші!']:
        iss = check_line(L('Something long enough here.'), uk, c)
        assert 'spelling' not in codes(iss), (uk, [i.msg for i in iss])


def test_russisms_and_scripts():
    c = ctx()
    assert 'russism' in blocks(check_line(L('Want a sip?'), 'Хочеш теж глотнути?', c))
    assert 'russism' in blocks(check_line(L('Yes'), 'Конечно, ты прав', c))
    assert 'latin' in blocks(check_line(L('I will moan'), 'Я зараз почну moan-ити', c)) or \
        'mixed_script' in blocks(check_line(L('I will moan'), 'Я зараз почну moan-ити', c))
    assert 'mixed_script' in blocks(check_line(L('deep'), 'з самиdep глибини', c))
    assert 'mixed_script' in blocks(check_line(L('compare'), 'Ти 비교є', c))
    assert 'untranslated' in blocks(check_line(L('Oh, is that a doujinshi?'), 'Oh, is that a doujinshi?', c))
    assert not blocks(check_line(L('Is it OK?'), 'Це OK?', c))


def test_glossary_and_forbid():
    c = ctx()
    iss = check_line(L('Who\'d look at a thug like you!'), 'Хто б дивився на таку шльондру, як ти!', c)
    assert 'gloss_forbid' in blocks(iss)
    assert 'forbid' in blocks(check_line(L('I\'m gonna finish'), 'Я зараз фінішую', c))


def test_honorific_and_names():
    c = ctx()
    assert 'honorific' in blocks(check_line(L("Daisuke-san"), 'Дайсуке-сан', c))
    iss = check_line(L("Don't you feel bad for Daisuke-san?"), 'Тобі не соромно перед Дайкі?', c)
    assert 'name_not_in_src' in codes(iss), iss
    assert 'name_not_in_src' not in codes(check_line(L('Hey, Taku... Are you okay?'), 'Гей, Таку... Ти як?', c))
    assert 'name_not_in_src' not in codes(check_line(L('Who would look at you!'), 'Хто б дивився на таку, як ти!', c))
    assert 'name_not_in_src' not in codes(check_line(L('The customers are staring!'), 'Клієнти так дивляться!', c))


def test_gender():
    if not HAVE_DICT:
        return
    c = ctx()
    assert 'gender_who' in blocks(check_line(L('I knew it', who='Aika'), 'Я так і знав!', c))
    assert 'gender_who' in blocks(check_line(L('I got loose too', who='Aika'), 'Я теж розпустився.', c))
    assert not blocks(check_line(L('I knew it', who='Aika'), 'Я так і знала!', c))
    assert 'gender_who' in blocks(check_line(L("I'm ready", who='Taku'), 'Я вже готова!', c))
    assert 'gender_to' in blocks(check_line(L("Aren't you hungry?", to='Aika'), 'Ти що, не голодний?', c))
    assert not blocks(check_line(L("Aren't you hungry?", to='Aika'), 'Ти що, не голодна?', c))
    assert not blocks(check_line(L('I knew it'), 'Я так і знав!', c)), 'мовець невідомий — не судимо'
    assert not blocks(check_line(L('We knew it', who='Aika'), 'Ми так і знали!', c))
    assert not blocks(check_line(L('A week', who='Aika'), 'Я цілий тиждень не відчувала члена.', c))
    assert not blocks(check_line(L('brat', to='Taku'), 'Яка ж ти нестерпна розпещена дитина!', c))
    assert 'gender_to' in blocks(check_line(L('brat', to='Taku'), 'Ти така нестерпна!', c))
    assert 'gender_who' in blocks(check_line(L("I'm so happy", who='Taku'), 'Я така щаслива!', c))


def test_sex_context():
    c = ctx(sex_ranges=[(100, 200)])
    iss = check_line(L('Thanks for finishing!', n=3), 'Дякую, що кінчив!', c)
    assert 'sex_context' in codes(iss) and not blocks(iss)
    assert 'sex_context' not in codes(check_line(L('I\'m coming!', n=150), 'Я кінчаю!', c))
    assert 'sex_context' not in codes(check_line(L('Thanks for finishing!', n=3), 'Дякую, що кінчив!', ctx()))


def test_length():
    c = ctx()
    assert 'too_short' in codes(check_line(L('Well, you can\'t go to the office in that state.'), 'Га?', c))


# ---------------- прийняття кандидатів, зсув, echo ----------------
def test_accept_shift_and_echo():
    c = ctx()
    ls = [L('I can\'t hold back anymore!', n=0), L('Me neither!', n=1), L('Good.', n=2)]
    assert accept(ls[0], 'Я більше не можу стримуватися!', c, ls, echo='I can\'t')[0]
    ok, iss = accept(ls[1], 'Я більше не можу стримуватися!', c, ls, echo='Me neither')
    assert not ok and 'shift' in blocks(iss) and ls[1].uk == ''
    ok, iss = accept(ls[1], 'Я теж!', c, ls, echo='Good')
    assert not ok and 'echo' in blocks(iss), 'відповідь для іншої репліки'
    ok, _ = accept(ls[1], 'Я теж!', c, ls, echo='Me neither')
    assert ok and ls[1].uk == 'Я теж!' and ls[1].status == 'ok'
    assert len(ls[1].cands) == 3, 'усі спроби в історії'
    assert not echo_ok('', 'Hello there') and echo_ok('hello', 'Hello there') and echo_ok('L-Like', 'Like you')


def test_validate_report():
    c = ctx()
    ls = prepare([(0, 2, 'Hello.'), (3, 5, 'Hi.'), (6, 8, 'Translated by: someone'), (9, 10, 'Bye.')])
    ls[0].uk, ls[1].uk, ls[3].uk = 'Привіт.', '', 'Бувай.'
    rep = validate(ls, c)
    assert rep['total'] == 3 and rep['failed'] == 1
    assert rep['lines'][0]['n'] == 1 and rep['lines'][0]['issues'][0]['code'] == 'empty'
    assert ls[2].status == 'ok', 'подяки не перекладаємо'
    assert 'dict_ok' in rep['meta']


def test_consistency_papa_tato():
    if not HAVE_DICT:
        return
    c = ctx()
    ls = prepare([(0, 2, 'Dad!'), (3, 5, 'Dad, wait.')])
    ls[0].uk, ls[1].uk = 'Папо!', 'Тату, зачекай.'
    out = check_all(ls, c)
    assert 0 in out and out[0][0].code == 'inconsistent'


def test_without_dictionary():
    lex = Lexicon.__new__(Lexicon)
    lex.__dict__.update(LEX.__dict__)
    lex.ok, lex.morph, lex.why = False, None, 'тест без словника'
    lex._cache = {}
    c = Ctx(chars=CHARS, lex=lex)
    iss = check_line(L('Something long enough here.', who='Aika'), 'Вона завагірніла. Я так і знав!', c)
    assert 'spelling' not in codes(iss) and 'gender_who' not in codes(iss)
    assert 'russism' in codes(check_line(L('Yes'), 'Конечно', c)), 'русизми працюють і без словника'
    rep = validate([L('Hi.', n=0, uk='Привіт.')], c)
    assert rep['meta']['dict_ok'] is False


# ---------------- тест якості (benchmark) ----------------
def test_benchmark_file_is_sane():
    from tr import bench
    b = bench.load()
    ids = set()
    for c in b['cases']:
        assert c['id'] not in ids and 'kyonyuu' not in (c['id'] + c.get('title', '')).lower()
        ids.add(c['id'])
        names = {ch['en'] for ch in c['chars']}
        for ln in c['lines']:
            for k in ('any', 'all', 'none'):
                for p in ln.get(k) or []:
                    re.compile(p)
            for k in ('who', 'to'):
                assert not ln.get(k) or ln[k] in names, (c['id'], ln)
        for a, z in c.get('sex') or []:
            assert 0 <= a <= z < len(c['lines'])
    assert sum(len(c['lines']) for c in b['cases']) >= 150


def test_bench_scoring():
    from tr import bench
    case = {'id': 't', 'chars': [{'en': 'Aika', 'uk': 'Айка', 'gender': 'f'}], 'sex': [],
            'lines': [{'en': 'I knew it!', 'who': 'Aika', 'any': ['знала'], 'none': [r'знав\b']},
                      {'en': 'Me neither!', 'any': ['теж']},
                      {'en': 'Thanks for finishing!', 'none': [r'\bкінч']}]}
    r = bench.score_case(case, ['Я так і знала!', 'Я теж!', 'Дякую, що закінчив!'])
    assert r['passed'] == 3, r
    r = bench.score_case(case, ['Я так і знав!', 'Я так і знав!', 'Дякую, що кінчив!'])
    assert r['passed'] == 0, r
    assert r['lines'][1]['expect'], 'немає «теж»'
    r = bench.score_case(case, ['Я так і знала!'])        # модель повернула менше рядків
    assert r['passed'] == 1 and not r['lines'][2]['ok']
    rep = bench.run(lambda c: ['Я так і знала!', 'Я теж!', 'Дякую!'], bench={'cases': [case, dict(case, id='u')]})
    assert rep['score'] == 100.0 and rep['meta']['finished']

    def boom(c):
        raise RuntimeError('ПК вимкнений')
    rep = bench.run(boom, bench={'cases': [case]})
    assert rep['score'] == 0 and rep['cases'][0]['error'] == 'ПК вимкнений'


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('ok  ', name)
            except Exception as e:      # noqa: BLE001
                fails += 1
                print('FAIL', name, '—', repr(e))
    print('словник:', 'є' if HAVE_DICT else 'нема (%s)' % LEX.why)
    sys.exit(1 if fails else 0)
