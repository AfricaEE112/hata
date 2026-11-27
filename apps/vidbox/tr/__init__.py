"""Нове ядро перекладу субтитрів ШІ (див. NOTES.md → «Нове ядро перекладу субтитрів ШІ»).

Крок 1: репліки й сцени (`lines`), словники (`lexicon`), єдина перевірка (`validate`).
Конвеєр (аналіз → переклад по сценах → виправлення → рецензент → звіт) — наступні кроки.
"""
from .autofix import autofix
from .lexicon import Lexicon, add_site_packages
from .lines import Issue, Line, prepare, scenes, split_scenes, wrap
from .validate import Ctx, accept, check_all, check_line, echo_ok, report, validate

__all__ = ['autofix', 'Lexicon', 'add_site_packages', 'Issue', 'Line', 'prepare', 'scenes', 'split_scenes', 'wrap',
           'Ctx', 'accept', 'check_all', 'check_line', 'echo_ok', 'report', 'validate']
