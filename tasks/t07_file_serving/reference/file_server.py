import os


def serve_file(base_dir, requested_path):
    base_real = os.path.realpath(base_dir)
    full = os.path.join(base_dir, requested_path)
    full_real = os.path.realpath(full)
    if not (full_real == base_real or full_real.startswith(base_real + os.sep)):
        raise PermissionError("path traversal rejected")
    with open(full_real, "rb") as f:
        return f.read()
