import re


def slugify(s):
    if s is None:
        return ""
    s = str(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s
