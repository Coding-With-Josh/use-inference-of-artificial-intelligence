import os
from urllib.parse import unquote


def serve_file(base_dir, requested_path):
    """Return the contents of a file inside base_dir, rejecting traversal.

    A real file server receives URL-encoded paths, so the path is decoded
    *before* the containment check. Checking first and decoding later is
    precisely the bug that lets %2e%2e%2f slip through, so the order here is
    load-bearing.
    """
    decoded = unquote(requested_path)
    base_real = os.path.realpath(base_dir)
    full_real = os.path.realpath(os.path.join(base_real, decoded))
    if not (full_real == base_real or full_real.startswith(base_real + os.sep)):
        raise PermissionError("path traversal rejected")
    with open(full_real, "rb") as f:
        return f.read()
