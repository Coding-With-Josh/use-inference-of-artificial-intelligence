def serve_file(base_dir, requested_path):
    """Return the contents of a file inside base_dir, rejecting escapes.

    Args:
        base_dir: the directory files must stay within.
        requested_path: the caller-supplied relative path.

    Returns:
        the file contents as bytes.

    Raises:
        NotImplementedError: always; the starter ships no implementation.
    """
    raise NotImplementedError
