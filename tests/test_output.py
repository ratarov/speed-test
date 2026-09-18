"""Единицы измерения, подсветка и печать итога."""

import io

import pytest

from speed_test.models import Attempt, summarize
from speed_test.output import (
    Style,
    format_progress,
    format_provider_speed,
    format_size,
    format_speed,
    print_report,
)

MB = 1024 * 1024


@pytest.mark.parametrize(
    ('size', 'expected'),
    [(0, '0 Б'), (999, '999 Б'), (1024, '1.0 КБ'), (MB - 1, '1024.0 КБ'), (MB, '1.00 МБ'), (10 * MB, '10.00 МБ')],
)
def test_size_switches_units_instead_of_printing_zero(size, expected):
    assert format_size(size) == expected


def test_speed_is_binary_and_provider_speed_is_decimal():
    """Две единицы намеренно разные: слева двоичные мегабайты, справа десятичные провайдерские."""
    bytes_per_second = 50_000_000

    assert format_speed(bytes_per_second) == '47.68 МБ/с'
    assert format_provider_speed(bytes_per_second) == '50.00 МБ/с (400.0 Мбит/с)'


def test_provider_units_multiply_by_eight():
    # Ровно то, чего не даёт двоичная цифра: мегабайты провайдера умножаются на 8 в мегабиты.
    assert format_provider_speed(1_000_000) == '1.00 МБ/с (8.0 Мбит/с)'


def test_progress_line_aligns_numbers_by_the_total():
    line = format_progress(7, 10, Attempt(size=10 * MB, seconds=0.5))

    assert line == ' 7/10: 10.00 МБ за 0.50 с — 20.00 МБ/с'


class TestStyle:
    def test_disabled_style_returns_plain_text(self):
        assert Style(enabled=False).accent('42') == '42'

    def test_enabled_style_wraps_text_in_ansi(self):
        assert Style(enabled=True).accent('42') == '\033[1;32m42\033[0m'

    def test_detect_keeps_color_out_of_a_pipe(self):
        assert Style.detect(io.StringIO()).enabled is False

    def test_detect_obeys_no_color(self, monkeypatch):
        stream = io.StringIO()
        monkeypatch.setattr(stream, 'isatty', lambda: True)
        monkeypatch.setenv('NO_COLOR', '1')

        assert Style.detect(stream).enabled is False

    def test_detect_obeys_the_flag(self, monkeypatch):
        stream = io.StringIO()
        monkeypatch.setattr(stream, 'isatty', lambda: True)
        monkeypatch.delenv('NO_COLOR', raising=False)

        assert Style.detect(stream, disabled=True).enabled is False


class TestReport:
    def test_report_shows_both_unit_systems(self, capsys):
        print_report(summarize([Attempt(size=10 * MB, seconds=1.0)]), Style())
        printed = capsys.readouterr().out

        assert 'средняя скорость:      10.00 МБ/с' in printed
        assert 'Скорость в единицах провайдера: 10.49 МБ/с (83.9 Мбит/с)' in printed
        assert '1 МБ = 1024 × 1024 байт' in printed

    def test_small_response_earns_a_warning(self, capsys):
        print_report(summarize([Attempt(size=1000, seconds=0.1)]), Style())

        assert 'Ответ меньше 1 МБ' in capsys.readouterr().out

    def test_heavy_response_does_not(self, capsys):
        print_report(summarize([Attempt(size=10 * MB, seconds=1.0)]), Style())

        assert 'Ответ меньше 1 МБ' not in capsys.readouterr().out
