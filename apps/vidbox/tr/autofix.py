"""Безпечні автоматичні виправлення перекладу без моделі (застосовуються до кожного кандидата перед перевіркою):
русизми й часті описки з `qa/uk_autofix.txt`, японські гоноративи після імен, звертання «Нее-чан» → «сестричко»,
уламки латиниці всередині кириличного слова, «мою грудь» → «мої груди»."""
import os
import re

from .lexicon import QA_DIR, _read_lines

KIN = [(re.compile(r"\b[НнОо]-[Оо]?[Нн]е{1,2}-?(чан|сан|тян)\b"), 'С-сестричко'),
       (re.compile(r"\b[НнОо]-[Оо]?[Нн]і[ії]?-?(чан|сан|тян)\b"), 'Б-братику'),
       (re.compile(r"\b[Оо]?[Нн]е{1,2}-?(чан|сан|тян)\b"), 'сестричко'),
       (re.compile(r"\b[Оо]?[Нн]і[ії]?-?(чан|сан|тян)\b"), 'братику')]
HON = re.compile(r"\b([А-ЯІЇЄҐ][а-яіїєґʼ'’]+)-(?:(?:сан|кун|чан|тян|сама|доно)(?:е|у|а|ом|ові|і)?|ні|нії|нее)\b")
BREAST = re.compile(r"(?i)\b(мою|твою|свою) груд[ьи]\b")
WORD = re.compile(r"[^\W\d_]+(?:['’ʼ-][^\W\d_]+)*")


def case_like(src, new):
    return new[:1].upper() + new[1:] if src[:1].isupper() else new


class AutoFix:
    _inst = None

    def __init__(self, path=None):
        self.words, self.stems = {}, []
        for ln in _read_lines(path or os.path.join(QA_DIR, 'uk_autofix.txt')):
            if '=' not in ln:
                continue
            a, b = [x.strip() for x in ln.split('=', 1)]
            if a.endswith('*') and b.endswith('*'):
                self.stems.append((re.compile(r'(?i)\b' + re.escape(a[:-1])), b[:-1]))
            elif a:
                self.words[a.lower()] = b

    @classmethod
    def get(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def __call__(self, t):
        if not t:
            return t
        for rx, rep in KIN:
            t = rx.sub(lambda m: rep if rep[1:2] == '-' else case_like(m.group(0), rep), t)
        t = HON.sub(r'\1', t)
        t = BREAST.sub(lambda m: case_like(m.group(1), {'мою': 'мої', 'твою': 'твої', 'свою': 'свої'}[m.group(1).lower()])
                       + ' груди', t)
        t = WORD.sub(lambda m: case_like(m.group(0), self.words[m.group(0).lower()])
                     if m.group(0).lower() in self.words else m.group(0), t)
        for rx, rep in self.stems:
            t = rx.sub(lambda m: case_like(m.group(0), rep), t)

        def mixed(m):                     # «самиdep» → «сами»: латинський уламок у кириличному слові
            w = m.group(0)
            if re.search('[А-Яа-яІіЇїЄєҐґ]', w) and re.search('[A-Za-z]', w):
                return re.sub('[A-Za-z]+', '', w).strip('-') or w
            return w
        t = WORD.sub(mixed, t)
        return re.sub(r'  +', ' ', t).strip()


def autofix(t):
    return AutoFix.get()(t)
