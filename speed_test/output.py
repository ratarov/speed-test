"""Оформление вывода: единицы измерения, подсветка и печать итога."""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from typing import Final, TextIO

from speed_test.models import Attempt, Summary

STD_OUTPUT_HANDLE: Final[int] = -11
ENABLE_VIRTUAL_TERMINAL_PROCESSING: Final[int] = 0x0004

BYTES_IN_KB: Final[int] = 1024
BYTES_IN_MB: Final[int] = 1024 * 1024
#: Десятичная приставка «мега» — в ней считает провайдер, и для байтов, и для битов.
MEGA: Final[int] = 1_000_000
#: Ниже этого объёма замер говорит скорее о задержке сети, чем о пропускной способности.
MIN_MEANINGFUL_SIZE: Final[int] = BYTES_IN_MB


def enable_windows_ansi() -> None:
    """Разрешает ANSI-последовательности в консоли Windows; в Терминале они и так работают."""
    if sys.platform != 'win32':
        return
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)


@dataclass(frozen=True)
class Style:
    """Подсветка вывода. Когда цвет недоступен, методы возвращают текст без изменений."""

    enabled: bool = False

    @classmethod
    def detect(cls, stream: TextIO, *, disabled: bool = False) -> Style:
        """Включает цвет только для настоящего терминала: в файле и в конвейере ANSI — мусор."""
        if disabled or os.environ.get('NO_COLOR') or not stream.isatty():
            return cls(enabled=False)
        enable_windows_ansi()
        return cls(enabled=True)

    def accent(self, text: str) -> str:
        """Выделяет главные цифры прогона."""
        return self._paint(text, '1;32')

    def bold(self, text: str) -> str:
        """Выделяет заголовок."""
        return self._paint(text, '1')

    def muted(self, text: str) -> str:
        """Приглушает пояснение, чтобы оно не спорило с цифрами."""
        return self._paint(text, '2')

    def warning(self, text: str) -> str:
        """Отмечает предупреждение."""
        return self._paint(text, '33')

    def error(self, text: str) -> str:
        """Отмечает ошибку."""
        return self._paint(text, '31')

    def _paint(self, text: str, code: str) -> str:
        return f'\033[{code}m{text}\033[0m' if self.enabled else text


def format_size(size: float) -> str:
    """Объём в двоичных единицах: мегабайты, а для мелочи — килобайты и байты."""
    if size >= BYTES_IN_MB:
        return f'{size / BYTES_IN_MB:.2f} МБ'
    if size >= BYTES_IN_KB:
        return f'{size / BYTES_IN_KB:.1f} КБ'
    return f'{size:.0f} Б'


def format_speed(bytes_per_second: float) -> str:
    """Скорость в двоичных мегабайтах в секунду."""
    return f'{bytes_per_second / BYTES_IN_MB:.2f} МБ/с'


def format_provider_speed(bytes_per_second: float) -> str:
    """Та же скорость в единицах провайдера: десятичные мегабайты и мегабиты в секунду."""
    return f'{bytes_per_second / MEGA:.2f} МБ/с ({bytes_per_second * 8 / MEGA:.1f} Мбит/с)'


def format_progress(number: int, total: int, attempt: Attempt) -> str:
    """Строка о только что скачанном ответе."""
    return (
        f'{number:>{len(str(total))}}/{total}: {format_size(attempt.size)} '
        f'за {attempt.seconds:.2f} с — {format_speed(attempt.speed)}'
    )


def print_header(url: str, requests: int, timeout: float, style: Style) -> None:
    """Печатает условия замера перед первым запросом."""
    print(style.muted(f'Адрес:    {url}'))
    print(style.muted(f'Запросов: {requests}, таймаут: {timeout:g} с'))
    print(flush=True)


def print_report(summary: Summary, style: Style) -> None:
    """Печатает итог прогона и перевод средней скорости в единицы провайдера."""
    print()
    print(style.bold('Итог:'))
    print(f'  среднее время запроса: {summary.average_seconds:.2f} с')
    print(f'  скачано всего:         {format_size(summary.total_size)}')
    print(f'  средняя скорость:      {style.accent(format_speed(summary.average_speed))}')
    print(f'  разброс по запросам:   от {format_speed(summary.slowest)} до {format_speed(summary.fastest)}')
    print()
    print(
        style.muted(
            'Значения двоичные: 1 МБ = 1024 × 1024 байт. '
            'Провайдер измеряет канал в десятичных мегабитах (1 Мбит = 1 000 000 бит).'
        )
    )
    print(f'Скорость в единицах провайдера: {style.accent(format_provider_speed(summary.average_speed))}')
    if summary.average_size < MIN_MEANINGFUL_SIZE:
        print()
        print(
            style.warning(
                'Ответ меньше 1 МБ: на таком объёме измеряется в основном задержка сети, '
                'а не пропускная способность. Возьмите файл потяжелее.'
            )
        )
