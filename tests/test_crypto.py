import os

from app import crypto


def test_seal_open_roundtrip():
    key = os.urandom(32)
    blob = crypto.seal(key, "秘密内容".encode())
    assert crypto.open_sealed(key, blob).decode() == "秘密内容"


def test_tamper_fails():
    key = os.urandom(32)
    blob = crypto.seal(key, b"x" * 32)
    try:
        crypto.open_sealed(key, blob[:-2] + "AA")
        assert False
    except Exception:
        pass
