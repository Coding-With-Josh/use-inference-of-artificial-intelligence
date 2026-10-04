from merge_intervals import merge_intervals


def test_nested():
    assert merge_intervals([(1, 5), (2, 3)]) == [(1, 5)]


def test_multiple():
    assert merge_intervals([(1, 4), (2, 5), (6, 8)]) == [(1, 5), (6, 8)]


def test_unsorted():
    assert merge_intervals([(6, 8), (1, 4), (2, 5)]) == [(1, 5), (6, 8)]
