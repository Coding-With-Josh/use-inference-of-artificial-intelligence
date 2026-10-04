from merge_intervals import merge_intervals


def test_basic_merge():
    assert merge_intervals([(1, 3), (2, 6)]) == [(1, 6)]


def test_separate():
    assert merge_intervals([(1, 2), (3, 4)]) == [(1, 2), (3, 4)]
