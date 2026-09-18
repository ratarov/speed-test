"""Замер скорости скачивания: несколько последовательных запросов к одному адресу.

Меряется то, что видит пользователь: время от начала запроса до последнего байта ответа.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from typing import Final, TextIO

import httpx

DEFAULT_URL: Final[str] = 'https://speed.cloudflare.com/__down?bytes=10000000'
DEFAULT_REQUESTS: Final[int] = 10
DEFAULT_TIMEOUT: Final[float] = 10.0
CHUNK_SIZE: Final[int] = 64 * 1024
USER_AGENT: Final[str] = 'speed-test/0.1.0 (network speed check)'
ALLOWED_SCHEMES: Final[tuple[str, ...]] = ('http://', 'https://')

#: Код возврата для ошибки в параметрах — как у argparse, чтобы скрипты вокруг не переучивать.
USAGE_EXIT_CODE: Final[int] = 2
FAILURE_EXIT_CODE: Final[int] = 1

STD_OUTPUT_HANDLE: Final[int] = -11
ENABLE_VIRTUAL_TERMINAL_PROCESSING: Final[int] = 0x0004

BYTES_IN_KB: Final[int] = 1024
BYTES_IN_MB: Final[int] = 1024 * 1024
#: Десятичная приставка «мега» — в ней считает провайдер, и для байтов, и для битов.
MEGA: Final[int] = 1_000_000
MIN_MEANINGFUL_SIZE: Final[int] = BYTES_IN_MB


class SpeedTestError(Exception):
    """Ошибка замера с сообщением, готовым к показу пользователю."""


class UsageError(SpeedTestError):
    """Ошибка в параметрах запуска: сообщение объясняет, как их исправить."""


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


@dataclass(frozen=True)
class Attempt:
    """Один скачанный ответ: объём и время до последнего байта."""

    size: int
    seconds: float

    @property
    def speed(self) -> float:
        """Скорость скачивания в байтах в секунду."""
        return self.size / self.seconds if self.seconds > 0 else 0.0


@dataclass(frozen=True)
class Summary:
    """Агрегаты прогона по всем запросам."""

    attempts: int
    total_size: int
    total_seconds: float
    slowest: float
    fastest: float

    @property
    def average_seconds(self) -> float:
        """Среднее время одного запроса в секундах."""
        return self.total_seconds / self.attempts if self.attempts else 0.0

    @property
    def average_size(self) -> float:
        """Средний объём одного ответа в байтах."""
        return self.total_size / self.attempts if self.attempts else 0.0

    @property
    def average_speed(self) -> float:
        """Средняя скорость в байтах в секунду: весь объём на всё время, а не среднее скоростей."""
        return self.total_size / self.total_seconds if self.total_seconds > 0 else 0.0


@dataclass(frozen=True)
class Options:
    """Проверенные параметры запуска."""

    url: str
    requests: int
    timeout: float
    no_color: bool


def summarize(attempts: list[Attempt]) -> Summary:
    """Считает агрегаты по списку выполненных запросов."""
    speeds = [attempt.speed for attempt in attempts]
    return Summary(
        attempts=len(attempts),
        total_size=sum(attempt.size for attempt in attempts),
        total_seconds=sum(attempt.seconds for attempt in attempts),
        slowest=min(speeds),
        fastest=max(speeds),
    )


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


def status_message(status_code: int) -> str:
    """Объясняет код ответа: 403 и 429 на замере встречаются чаще, чем кажется."""
    if status_code == httpx.codes.NOT_FOUND:
        return f'Сервер ответил {status_code} — по этому адресу файла нет.'
    if status_code == httpx.codes.TOO_MANY_REQUESTS:
        return f'Сервер ответил {status_code} — хост ограничил частоту запросов. Возьмите другой адрес или подождите.'
    if status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        return f'Сервер ответил {status_code} — хост не отдаёт этот файл автоматическим клиентам.'
    return f'Сервер ответил {status_code} — нужен адрес, который отдаёт файл.'


def caused_by(error: BaseException, exception_type: type[BaseException]) -> bool:
    """Ищет исключение нужного типа в цепочке причин: httpx прячет отказы DNS и TLS внутрь своих ошибок."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, exception_type):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def describe_network_error(error: httpx.RequestError, url: str, timeout: float) -> str:
    """Переводит сетевую ошибку httpx в объяснение, по которому понятно, что чинить."""
    host = httpx.URL(url).host or url
    if isinstance(error, httpx.UnsupportedProtocol):
        # Сам адрес проверен при разборе аргументов, так что сюда приводит только перенаправление.
        return f'{host} перенаправляет на адрес с неподдерживаемой схемой.'
    if isinstance(error, httpx.TooManyRedirects):
        return f'{host} перенаправляет запрос по кругу — проверьте адрес.'
    if isinstance(error, httpx.TimeoutException):
        return f'Ответ от {host} не пришёл за {timeout:g} с. Увеличьте --timeout или возьмите файл поменьше.'
    if caused_by(error, socket.gaierror):
        return f'Хост {host} не найден: имя не разрешается. Проверьте адрес и подключение к сети.'
    if caused_by(error, ssl.SSLError):
        return f'Не удалось установить защищённое соединение с {host}: сертификат не прошёл проверку.'
    if isinstance(error, httpx.ConnectError):
        return f'Не удалось подключиться к {host}: хост недоступен или соединение блокируется.'
    if isinstance(error, (httpx.ReadError, httpx.WriteError, httpx.ProtocolError)):
        return f'Соединение с {host} оборвалось во время скачивания.'
    return f'Сетевая ошибка при обращении к {host}: {type(error).__name__}.'


def download_once(client: httpx.Client, url: str) -> Attempt:
    """Скачивает ответ целиком, считая объём и время до последнего байта."""
    started = time.perf_counter()
    size = 0
    with client.stream('GET', url) as response:
        if not response.is_success:
            raise SpeedTestError(status_message(response.status_code))
        for chunk in response.iter_bytes(CHUNK_SIZE):
            size += len(chunk)
    return Attempt(size=size, seconds=time.perf_counter() - started)


def measure(url: str, *, requests: int, timeout: float) -> list[Attempt]:
    """Делает запросы подряд, печатая результат каждого.

    Клиент один на весь прогон: соединение переиспользуется, поэтому меряется скачивание,
    а не переподключение. Заголовки просят не отдавать ответ из кеша и называют клиента —
    на стандартный User-Agent библиотеки часть хостов отвечает отказом.
    """
    attempts: list[Attempt] = []
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={'Cache-Control': 'no-cache', 'User-Agent': USER_AGENT},
    ) as client:
        for number in range(1, requests + 1):
            attempt = download_once(client, url)
            attempts.append(attempt)
            print(
                f'{number:>2}/{requests}: {format_size(attempt.size)} за {attempt.seconds:.2f} с '
                f'— {format_speed(attempt.speed)}',
                flush=True,
            )
    return attempts


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


def run(options: Options, style: Style) -> None:
    """Выполняет замер целиком: от шапки до итога."""
    print(style.muted(f'Адрес:    {options.url}'))
    print(style.muted(f'Запросов: {options.requests}, таймаут: {options.timeout:g} с'))
    print(flush=True)

    summary = summarize(measure(options.url, requests=options.requests, timeout=options.timeout))
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


if __name__ == '__main__':
    raise SystemExit(main())
