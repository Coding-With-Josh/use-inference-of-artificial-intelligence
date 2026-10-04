from pilot.models import mock


def test_mock_generates():
    m = mock.MockModel(seed=42)
    assert m.generate('test') in ('correct', 'subtly_wrong', 'insecure')
