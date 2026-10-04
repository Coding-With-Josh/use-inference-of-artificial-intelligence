import os


def serve_file(base_dir, requested_path):
    full = os.path.join(base_dir, requested_path)
    with open(full, "rb") as f:
        return f.read()
