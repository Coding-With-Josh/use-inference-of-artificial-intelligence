from pilot.scoring import metrics


def test_defect_count_and_solved():
    d = metrics.defect_count([True, False, True])
    assert d == 1
    assert metrics.task_solved([True, False]) == 0
    assert metrics.task_solved([True, True]) == 1


def test_hidden_pass_rate():
    assert abs(metrics.hidden_pass_rate([True, False]) - 0.5) < 1e-9
