"""Сам замер: последовательные запросы к одному адресу.

Печатью модуль не занимается — отдаёт результаты по мере готовности, показывает их вызывающий.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Final

import httpx

from speed_test.errors import SpeedTestError, status_message
from speed_test.models import Attempt

#: Тело читаем кусками — файл целиком в память класть незачем.
CHUNK_SIZE: Final[int] = 64 * 1024
USER_AGENT: Final[str] = 'speed-test/0.1.0 (network speed check)'


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


def measure(url: str, *, requests: int, timeout: float) -> Iterator[Attempt]:
    """Делает запросы подряд, отдавая результат каждого сразу после скачивания.

    Клиент один на весь прогон: соединение переиспользуется, поэтому меряется скачивание,
    а не переподключение. Заголовки просят не отдавать ответ из кеша и называют клиента —
    на стандартный User-Agent библиотеки часть хостов отвечает отказом.
    """
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={'Cache-Control': 'no-cache', 'User-Agent': USER_AGENT},
    ) as client:
        for _ in range(requests):
            yield download_once(client, url)
