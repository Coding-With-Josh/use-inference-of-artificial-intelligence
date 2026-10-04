"""Hidden tests for t01: merge overlapping intervals.

Behaviors asserted here are the ones documented in docs/tasks.md item 1:
overlapping intervals merge, output is sorted, and touching endpoints merge.
"""

from merge_intervals import merge_intervals


def test_empty_input_returns_empty_list():
    assert merge_intervals([]) == []


def test_single_interval_passes_through():
    assert merge_intervals([(1, 5)]) == [(1, 5)]


def test_touching_intervals_merge():
    # (1,3) and (3,6) share an endpoint and must become one interval.
    assert merge_intervals([(1, 3), (3, 6)]) == [(1, 6)]


def test_contained_interval_is_absorbed():
    assert merge_intervals([(1, 10), (2, 3)]) == [(1, 10)]


def test_unsorted_input_produces_sorted_output():
    assert merge_intervals([(5, 6), (1, 2), (3, 4)]) == [(1, 2), (3, 4), (5, 6)]


def test_fully_contained_chain_collapses_to_one():
    assert merge_intervals([(1, 9), (2, 8), (3, 7)]) == [(1, 9)]


def test_duplicate_intervals_collapse():
    assert merge_intervals([(1, 2), (1, 2)]) == [(1, 2)]


def test_long_overlapping_chain_merges_into_one():
    intervals = [(i, i + 2) for i in range(10)]
    assert merge_intervals(intervals) == [(0, 11)]


def test_adjacent_discrete_intervals_merge():
    assert merge_intervals([(1, 2), (2, 3), (3, 4)]) == [(1, 4)]


def test_one_gap_keeps_two_groups():
    assert merge_intervals([(1, 2), (3, 4), (10, 11)]) == [(1, 2), (3, 4), (10, 11)]
