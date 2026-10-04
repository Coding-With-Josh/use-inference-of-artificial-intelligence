import hashlib


def hash_password(pw):
    return hashlib.md5(pw.encode()).hexdigest()


def verify_password(pw, h):
    return hash_password(pw) == h
