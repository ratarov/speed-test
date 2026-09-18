"""Перевод кодов ответа и сетевых сбоев на человеческий язык."""

import socket
import ssl

import httpx
import pytest

from speed_test.errors import caused_by, describe_network_error, status_message

URL = 'https://example.com/file.bin'


@pytest.mark.parametrize(
    ('status_code', 'expected'),
    [
        (404, 'по этому адресу файла нет'),
        (403, 'не отдаёт этот файл автоматическим клиентам'),
        (401, 'не отдаёт этот файл автоматическим клиентам'),
        (429, 'ограничил частоту запросов'),
        (500, 'нужен адрес, который отдаёт файл'),
    ],
)
def test_status_message_explains_the_code(status_code, expected):
    message = status_message(status_code)

    assert str(status_code) in message
    assert expected in message


class TestCausedBy:
    def test_finds_the_reason_deep_in_the_chain(self):
        root = socket.gaierror('getaddrinfo failed')
        middle = OSError('connect failed')
        middle.__cause__ = root
        outer = httpx.ConnectError('nope')
        outer.__cause__ = middle

        assert caused_by(outer, socket.gaierror) is True

    def test_says_no_when_the_reason_is_different(self):
        assert caused_by(httpx.ConnectError('nope'), ssl.SSLError) is False

    def test_survives_a_looped_chain(self):
        """Цепочка причин бывает закольцованной — обход обязан завершиться."""
        first = httpx.ConnectError('first')
        second = httpx.ConnectError('second')
        first.__context__ = second
        second.__context__ = first

        assert caused_by(first, socket.gaierror) is False


class TestDescribeNetworkError:
    def test_dns_failure_names_the_host(self):
        error = httpx.ConnectError('nope')
        error.__cause__ = socket.gaierror('getaddrinfo failed')

        message = describe_network_error(error, URL, timeout=10)

        assert 'example.com не найден' in message

    def test_certificate_failure(self):
        error = httpx.ConnectError('nope')
        error.__cause__ = ssl.SSLCertVerificationError('bad certificate')

        assert 'сертификат не прошёл проверку' in describe_network_error(error, URL, timeout=10)

    def test_refused_connection(self):
        message = describe_network_error(httpx.ConnectError('refused'), URL, timeout=10)

        assert 'Не удалось подключиться к example.com' in message

    def test_timeout_mentions_the_limit(self):
        message = describe_network_error(httpx.ReadTimeout('slow'), URL, timeout=2.5)

        assert 'не пришёл за 2.5 с' in message

    def test_unsupported_protocol_is_about_a_redirect(self):
        """Адрес проверен при разборе аргументов, поэтому сюда приводит только перенаправление."""
        message = describe_network_error(httpx.UnsupportedProtocol('ftp'), URL, timeout=10)

        assert 'перенаправляет на адрес с неподдерживаемой схемой' in message

    def test_redirect_loop(self):
        message = describe_network_error(httpx.TooManyRedirects('loop'), URL, timeout=10)

        assert 'по кругу' in message

    def test_broken_connection(self):
        message = describe_network_error(httpx.ReadError('reset'), URL, timeout=10)

        assert 'оборвалось во время скачивания' in message

    def test_unknown_error_still_names_the_kind(self):
        message = describe_network_error(httpx.ProxyError('proxy'), URL, timeout=10)

        assert 'ProxyError' in message
