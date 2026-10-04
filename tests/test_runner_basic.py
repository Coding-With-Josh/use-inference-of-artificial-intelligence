from pilot.runner import run


def test_plan_returns_cost():
    res = run.plan()
    assert 'cost_estimate_usd' in res


def test_analyze_noop():
    run.analyze()
