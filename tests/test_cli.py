"""Разбор параметров, коды возврата и сообщения об ошибках."""

import httpx
import pytest

from speed_test import cli
from speed_test.cli import check_requests, check_timeout, check_url, main, parse_options
from speed_test.errors import SpeedTestError, UsageError
from speed_test.models import Attempt

MB = 1024 * 1024


class TestOptions:
    def test_defaults_measure_the_built_in_file(self):
        options = parse_options([])

        assert options.url == cli.DEFAULT_URL
        assert options.requests == cli.DEFAULT_REQUESTS
        assert options.timeout == cli.DEFAULT_TIMEOUT
        assert options.no_color is False

    def test_values_come_from_the_command_line(self):
        options = parse_options(['https://example.com/f.bin', '-n', '3', '--timeout', '2.5', '--no-color'])

        assert options.url == 'https://example.com/f.bin'
        assert options.requests == 3
        assert options.timeout == 2.5
        assert options.no_color is True


class TestChecks:
    def test_address_without_scheme_suggests_the_fix(self):
        with pytest.raises(UsageError) as failure:
            check_url('speed.cloudflare.com/__down?bytes=10')

        assert 'https://speed.cloudflare.com/__down?bytes=10' in str(failure.value)

    def test_foreign_scheme_names_itself(self):
        with pytest.raises(UsageError) as failure:
            check_url('ftp://example.com/f.bin')

        assert 'ftp://' in str(failure.value)

    @pytest.mark.parametrize('value', ['abc', '3.5', ''])
    def test_requests_must_be_a_whole_number(self, value):
        with pytest.raises(UsageError, match='целым числом'):
            check_requests(value)

    def test_requests_must_be_at_least_one(self):
        with pytest.raises(UsageError, match='хотя бы один'):
            check_requests('0')

    def test_timeout_must_be_a_number(self):
        with pytest.raises(UsageError, match='числом секунд'):
            check_timeout('быстро')

    @pytest.mark.parametrize('value', ['0', '-1'])
    def test_timeout_must_be_positive(self, value):
        with pytest.raises(UsageError, match='больше нуля'):
            check_timeout(value)


class TestMain:
    @pytest.fixture
    def downloaded(self, monkeypatch):
        """Подменяет замер готовыми результатами: тесты не ходят в сеть."""

        def fake_measure(url, *, requests, timeout):
            for _ in range(requests):
                yield Attempt(size=10 * MB, seconds=0.5)

        monkeypatch.setattr(cli, 'measure', fake_measure)

    def test_successful_run_prints_the_report(self, downloaded, capsys):
        code = main(['https://example.com/f.bin', '-n', '2'])
        printed = capsys.readouterr().out

        assert code == 0
        assert '1/2: 10.00 МБ за 0.50 с — 20.00 МБ/с' in printed
        assert 'средняя скорость:      20.00 МБ/с' in printed

    def test_usage_error_goes_to_stderr_with_code_two(self, capsys):
        code = main(['ftp://example.com/f.bin'])
        streams = capsys.readouterr()

        assert code == cli.USAGE_EXIT_CODE
        assert 'Схема ftp:// не поддерживается' in streams.err
        assert streams.out == ''

    def test_measurement_error_gives_code_one(self, monkeypatch, capsys):
        def fake_measure(url, *, requests, timeout):
            raise SpeedTestError('Сервер ответил 404 — по этому адресу файла нет.')
            yield  # pragma: no cover - делает функцию генератором

        monkeypatch.setattr(cli, 'measure', fake_measure)

        code = main(['https://example.com/f.bin'])

        assert code == cli.FAILURE_EXIT_CODE
        assert '404' in capsys.readouterr().err

    def test_network_error_is_explained(self, monkeypatch, capsys):
        def fake_measure(url, *, requests, timeout):
            raise httpx.ConnectError('refused')
            yield  # pragma: no cover - делает функцию генератором

        monkeypatch.setattr(cli, 'measure', fake_measure)

        code = main(['https://example.com/f.bin'])

        assert code == cli.FAILURE_EXIT_CODE
        assert 'Не удалось подключиться к example.com' in capsys.readouterr().err

    def test_empty_response_is_reported(self, monkeypatch, capsys):
        def fake_measure(url, *, requests, timeout):
            yield Attempt(size=0, seconds=0.1)

        monkeypatch.setattr(cli, 'measure', fake_measure)

        code = main(['https://example.com/f.bin', '-n', '1'])

        assert code == cli.FAILURE_EXIT_CODE
        assert 'нечего скачивать' in capsys.readouterr().err

    def test_interruption_is_not_a_traceback(self, monkeypatch, capsys):
        def fake_measure(url, *, requests, timeout):
            raise KeyboardInterrupt
            yield  # pragma: no cover - делает функцию генератором

        monkeypatch.setattr(cli, 'measure', fake_measure)

        assert main(['https://example.com/f.bin']) == cli.FAILURE_EXIT_CODE
        assert 'Прервано' in capsys.readouterr().err
