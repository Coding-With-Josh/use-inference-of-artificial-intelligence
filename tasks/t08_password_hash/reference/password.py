import os
import hashlib


def hash_password(pw):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 200000)
    return salt.hex() + ":" + dk.hex()


def verify_password(pw, h):
    try:
        salt_hex, dk_hex = h.split(":")
        salt = bytes.fromhex(salt_hex)
        dk = bytes.fromhex(dk_hex)
        check = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 200000)
        if len(check) != len(dk):
            return False
        return hmac_compare(check, dk)
    except Exception:
        return False


def hmac_compare(a, b):
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= x ^ y
    return result == 0
