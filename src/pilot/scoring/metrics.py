from __future__ import annotations

from collections.abc import Iterable


def defect_count(results: Iterable[bool]) -> int:
    return sum(1 for r in results if not r)


def task_solved(results: Iterable[bool]) -> int:
    results_list = list(results)
    if not results_list:
        return 0
    return 1 if all(results_list) else 0


def hidden_pass_rate(results: Iterable[bool]) -> float:
    results_list = list(results)
    if not results_list:
        return 0.0
    return sum(1 for r in results if r) / float(len(results_list))
