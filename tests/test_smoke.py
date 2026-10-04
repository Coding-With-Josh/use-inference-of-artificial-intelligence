def test_import_pilot():
    import pilot  # noqa: F401

    assert pilot is not None
