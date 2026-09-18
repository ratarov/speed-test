"""Агрегаты прогона: среднее считается по сумме, а не как среднее скоростей."""

from speed_test.models import Attempt, summarize


def test_speed_of_instant_response_does_not_divide_by_zero():
    assert Attempt(size=1000, seconds=0.0).speed == 0.0


def test_average_speed_is_total_size_over_total_time():
    # Средняя от скоростей дала бы 15.0: короткий быстрый запрос весил бы столько же, сколько длинный.
    attempts = [Attempt(size=10, seconds=1.0), Attempt(size=200, seconds=10.0)]

    summary = summarize(attempts)

    assert summary.average_speed == 210 / 11
    assert summary.average_speed != (attempts[0].speed + attempts[1].speed) / 2


def test_summary_collects_totals_and_spread():
    summary = summarize([Attempt(size=100, seconds=1.0), Attempt(size=300, seconds=1.0)])

    assert summary.attempts == 2
    assert summary.total_size == 400
    assert summary.total_seconds == 2.0
    assert summary.average_seconds == 1.0
    assert summary.average_size == 200
    assert (summary.slowest, summary.fastest) == (100.0, 300.0)


def test_empty_run_does_not_break_the_summary():
    """Пустой список сюда не приходит (запросов минимум один), но падать на нём незачем."""
    summary = summarize([])

    assert summary.attempts == 0
    assert summary.average_speed == 0.0
    assert (summary.slowest, summary.fastest) == (0.0, 0.0)
