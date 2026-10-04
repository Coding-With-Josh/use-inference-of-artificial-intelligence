import re


EMAIL_RE = re.compile(r"[^@]+@[^@]+\.[^@]+")


def validate_signup(email, password, username):
    if not email or not isinstance(email, str) or len(email) > 254:
        return False
    if not EMAIL_RE.match(email):
        return False
    if not password or not isinstance(password, str) or len(password) < 8 or len(password) > 64:
        return False
    if not username or not isinstance(username, str) or len(username) < 3 or len(username) > 32:
        return False
    return True
