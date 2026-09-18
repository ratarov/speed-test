"""Ошибки замера и перевод сетевых сбоев httpx на человеческий язык."""

from __future__ import annotations

import socket
import ssl

import httpx


class SpeedTestError(Exception):
    """Ошибка замера с сообщением, готовым к показу пользователю."""


class UsageError(SpeedTestError):
    """Ошибка в параметрах запуска: сообщение объясняет, как их исправить."""


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
