from pilot.scoring import metrics


def test_edges():
    assert metrics.task_solved([]) == 0
    assert metrics.hidden_pass_rate([]) == 0.0
    assert metrics.defect_count([]) == 0
