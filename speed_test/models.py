"""Результаты замера: один скачанный ответ и агрегаты по всему прогону."""

from __future__ import annotations

from dataclasses import dataclass


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


def summarize(attempts: list[Attempt]) -> Summary:
    """Считает агрегаты по списку выполненных запросов."""
    # Пустой список сюда не приходит — запросов минимум один, — но ронять отчёт на нём незачем.
    speeds = [attempt.speed for attempt in attempts] or [0.0]
    return Summary(
        attempts=len(attempts),
        total_size=sum(attempt.size for attempt in attempts),
        total_seconds=sum(attempt.seconds for attempt in attempts),
        slowest=min(speeds),
        fastest=max(speeds),
    )
