"""AES-GCM 加解密：待处理凭证队列、模型 API Key 静态加密。"""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def seal(key: bytes, plaintext: bytes) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ct).decode("ascii")


def open_sealed(key: bytes, blob: str) -> bytes:
    raw = base64.b64decode(blob)
    if len(raw) < 13:
        raise ValueError("密文格式错误")
    return AESGCM(key).decrypt(raw[:12], raw[12:], None)


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
