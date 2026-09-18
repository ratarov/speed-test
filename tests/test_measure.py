"""Скачивание и прогон запросов. Сеть подменяется транспортом httpx — наружу тесты не ходят."""

import httpx
import pytest

from speed_test import measure as measure_module
from speed_test.errors import SpeedTestError
from speed_test.measure import download_once, measure

URL = 'https://example.com/file.bin'


def client_with(handler):
    """Клиент, у которого вместо сети — заданный обработчик запросов."""
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestDownloadOnce:
    def test_counts_every_byte_of_the_body(self):
        body = b'x' * 3000
        with client_with(lambda request: httpx.Response(200, content=body)) as client:
            attempt = download_once(client, URL)

        assert attempt.size == len(body)
        assert attempt.seconds > 0

    def test_empty_body_is_zero_bytes_not_an_error(self):
        with client_with(lambda request: httpx.Response(200, content=b'')) as client:
            attempt = download_once(client, URL)

        assert attempt.size == 0

    def test_bad_status_stops_the_run(self):
        with client_with(lambda request: httpx.Response(403)) as client, pytest.raises(SpeedTestError) as failure:
            download_once(client, URL)

        assert '403' in str(failure.value)


class TestMeasure:
    @pytest.fixture
    def recorded(self, monkeypatch):
        """Подменяет клиент внутри measure на клиент с фальшивым транспортом, записывая запросы."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=b'y' * 1024)

        real_client = httpx.Client

        def fake_client(**kwargs):
            """Тот же клиент, но с фальшивым транспортом вместо сети."""
            kwargs.pop('transport', None)
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(measure_module.httpx, 'Client', fake_client)
        return requests

    def test_makes_exactly_the_requested_number_of_downloads(self, recorded):
        attempts = list(measure(URL, requests=3, timeout=5))

        assert len(attempts) == 3
        assert len(recorded) == 3
        assert {attempt.size for attempt in attempts} == {1024}

    def test_asks_not_to_serve_from_cache_and_names_itself(self, recorded):
        """Стандартный User-Agent библиотеки часть хостов отклоняет, а кеш испортил бы замер."""
        list(measure(URL, requests=1, timeout=5))

        assert recorded[0].headers['Cache-Control'] == 'no-cache'
        assert recorded[0].headers['User-Agent'].startswith('speed-test/')

    def test_results_arrive_one_by_one(self, recorded):
        """Генератор отдаёт запрос сразу после скачивания — иначе прогресс показывать нечем."""
        downloads = measure(URL, requests=3, timeout=5)

        next(downloads)

        assert len(recorded) == 1
