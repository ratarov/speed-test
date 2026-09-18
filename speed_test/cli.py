"""Командная строка: разбор параметров, запуск замера и показ ошибок."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Final

import httpx

from speed_test.errors import SpeedTestError, UsageError, describe_network_error
from speed_test.measure import measure
from speed_test.models import Attempt, summarize
from speed_test.output import Style, format_progress, print_header, print_report

DEFAULT_URL: Final[str] = 'https://speed.cloudflare.com/__down?bytes=10000000'
DEFAULT_REQUESTS: Final[int] = 10
DEFAULT_TIMEOUT: Final[float] = 10.0
ALLOWED_SCHEMES: Final[tuple[str, ...]] = ('http://', 'https://')

#: Код возврата для ошибки в параметрах — как у argparse, чтобы скрипты вокруг не переучивать.
USAGE_EXIT_CODE: Final[int] = 2
FAILURE_EXIT_CODE: Final[int] = 1


@dataclass(frozen=True)
class Options:
    """Проверенные параметры запуска."""

    url: str
    requests: int
    timeout: float
    no_color: bool


def build_parser() -> argparse.ArgumentParser:
    """Собирает разборщик аргументов. Значения проверяются отдельно, человеческими сообщениями."""
    parser = argparse.ArgumentParser(
        prog='speed-test',
        description='Меряет скорость скачивания: несколько последовательных запросов к одному адресу.',
    )
    parser.add_argument(
        'url',
        nargs='?',
        default=DEFAULT_URL,
        help=f'адрес тяжёлого файла; по умолчанию тестовый файл на 10 МБ ({DEFAULT_URL})',
    )
    parser.add_argument(
        '-n',
        '--requests',
        default=str(DEFAULT_REQUESTS),
        help=f'сколько запросов сделать (по умолчанию {DEFAULT_REQUESTS})',
    )
    parser.add_argument(
        '--timeout',
        default=str(DEFAULT_TIMEOUT),
        help=f'сколько секунд ждать ответ (по умолчанию {DEFAULT_TIMEOUT:g})',
    )
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='не подсвечивать вывод (цвет и так отключается, если вывод не в терминал)',
    )
    return parser


def check_url(value: str) -> str:
    """Проверяет адрес до начала замера и подсказывает, как его дописать.

    Единственное место, где сформулировано правило про http и https: сетевые ошибки
    его не повторяют.
    """
    if '://' not in value:
        raise UsageError(f'Адрес без схемы: {value}\nДопишите протокол в начало, например: https://{value}')
    scheme = value.partition('://')[0]
    if not value.startswith(ALLOWED_SCHEMES):
        raise UsageError(f'Схема {scheme}:// не поддерживается.\nНужен адрес по http:// или https://')
    try:
        httpx.URL(value)
    except httpx.InvalidURL as error:
        raise UsageError(f'Не могу разобрать адрес: {value}\nЧто не так: {error}') from None
    return value


def check_requests(value: str) -> int:
    """Проверяет число запросов."""
    try:
        number = int(value)
    except ValueError:
        raise UsageError(f'Число запросов должно быть целым числом, а указано: {value}') from None
    if number < 1:
        raise UsageError(f'Запросов должно быть хотя бы один, а указано: {number}')
    return number


def check_timeout(value: str) -> float:
    """Проверяет таймаут ожидания ответа."""
    try:
        seconds = float(value)
    except ValueError:
        raise UsageError(f'Таймаут должен быть числом секунд, а указано: {value}') from None
    if seconds <= 0:
        raise UsageError(f'Таймаут должен быть больше нуля, а указано: {seconds:g}')
    return seconds


def parse_options(argv: list[str]) -> Options:
    """Разбирает аргументы командной строки и проверяет их пригодность для замера."""
    args = build_parser().parse_args(argv)
    return Options(
        url=check_url(args.url),
        requests=check_requests(args.requests),
        timeout=check_timeout(args.timeout),
        no_color=args.no_color,
    )


def run(options: Options, style: Style) -> None:
    """Выполняет замер целиком: от шапки до итога."""
    print_header(options.url, options.requests, options.timeout, style)

    attempts: list[Attempt] = []
    downloads = measure(options.url, requests=options.requests, timeout=options.timeout)
    for number, attempt in enumerate(downloads, start=1):
        attempts.append(attempt)
        print(format_progress(number, options.requests, attempt), flush=True)

    summary = summarize(attempts)
    if not summary.total_size:
        raise SpeedTestError('По этому адресу нечего скачивать: ответ пустой. Нужен адрес файла.')
    print_report(summary, style)


def fail(message: str, style: Style, *, code: int = FAILURE_EXIT_CODE) -> int:
    """Печатает ошибку после уже показанного прогресса и отдаёт код возврата."""
    sys.stdout.flush()
    print(style.error(message), file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    """Точка входа: 0 — замер состоялся, 1 — ошибка замера, 2 — ошибка в параметрах."""
    raw_args = sys.argv[1:] if argv is None else argv
    # Параметры ещё не разобраны, а ошибку показывать уже нужно: флаг читаем из строки как есть.
    err_style = Style.detect(sys.stderr, disabled='--no-color' in raw_args)

    try:
        options = parse_options(raw_args)
    except UsageError as error:
        return fail(f'{error}\n\nВсе параметры: speed-test --help', err_style, code=USAGE_EXIT_CODE)

    try:
        run(options, Style.detect(sys.stdout, disabled=options.no_color))
    except SpeedTestError as error:
        return fail(str(error), err_style)
    except httpx.RequestError as error:
        return fail(describe_network_error(error, options.url, options.timeout), err_style)
    except KeyboardInterrupt:
        return fail('Прервано.', err_style)
    return 0
