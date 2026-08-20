"""创建 Vaultwarden 测试/初始化账号。
按 Bitwarden 官方密钥派生流程（bitwarden-core/bitwarden-crypto）计算：
- masterKey = PBKDF2-SHA256(password, salt=email 小写, 600000)
- 认证哈希  = PBKDF2-SHA256(key=masterKey, salt=password, 1)
- 用户密钥包裹 = EncString type2（HKDF-Expand "enc"/"mac" + AES-256-CBC + HMAC-SHA256）
用法: python scripts/register_vaultwarden_account.py <email> <master_password> <vaultwarden_url>"""
import base64
import hashlib
import hmac
import os
import ssl
import sys
import urllib.error
import urllib.request
import json
import pathlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def pbkdf2(password: bytes, salt: bytes, iterations: int, dklen: int = 32) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations, dklen)


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """RFC5869 HKDF-Expand（SHA-256），与 bitwarden-crypto hkdf_expand 一致。"""
    out, t = b"", b""
    for i in range(1, (length + 31) // 32 + 1):
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
    return out[:length]


def aes_cbc_pkcs7(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(padded) + enc.finalize()


def wrap_user_key(master_key: bytes, user_key: bytes) -> str:
    enc_key = hkdf_expand(master_key, b"enc", 32)
    mac_key = hkdf_expand(master_key, b"mac", 32)
    iv = os.urandom(16)
    ct = aes_cbc_pkcs7(enc_key, iv, user_key)
    mac = hmac.new(mac_key, iv + ct, hashlib.sha256).digest()
    return f"2.{base64.b64encode(iv).decode()}|{base64.b64encode(ct).decode()}|{base64.b64encode(mac).decode()}"


def register(email: str, password: str, base_url: str) -> None:
    email_lower = email.lower().strip()
    kdf_iterations = 600000

    master_key = pbkdf2(password.encode(), email_lower.encode(), kdf_iterations)
    auth_hash = pbkdf2(master_key, password.encode(), 1)  # key=masterKey, salt=password
    user_key = os.urandom(64)  # AES-256-CBC-HMAC 用户密钥（64 字节）
    user_symmetric_key = wrap_user_key(master_key, user_key)

    # 账号非对称密钥对：私钥用用户密钥包裹（EncString type2），公钥 SPKI DER base64
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_der = priv.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    pub_der = priv.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    enc_key, mac_key = user_key[:32], user_key[32:]
    piv = os.urandom(16)
    pct = aes_cbc_pkcs7(enc_key, piv, priv_der)
    pmac = hmac.new(mac_key, piv + pct, hashlib.sha256).digest()
    encrypted_private_key = f"2.{base64.b64encode(piv).decode()}|{base64.b64encode(pct).decode()}|{base64.b64encode(pmac).decode()}"

    body = {
        "email": email_lower,
        "kdf": 0,
        "kdfIterations": kdf_iterations,
        "kdfMemory": None,
        "kdfParallelism": None,
        "userSymmetricKey": user_symmetric_key,
        "masterPasswordHash": base64.b64encode(auth_hash).decode(),
        "masterPasswordHint": "created by asset-assistant setup",
        "name": "asset-assistant",
        "keys": {
            "encryptedPrivateKey": encrypted_private_key,
            "publicKey": base64.b64encode(pub_der).decode(),
        },
    }
    ctx = ssl.create_default_context(cafile=str(pathlib.Path(__file__).parent.parent / "certs" / "ca.crt"))
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/identity/accounts/register",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            print("注册成功:", r.status, r.read().decode()[:120])
    except urllib.error.HTTPError as e:
        print("注册失败:", e.code, e.read().decode()[:300])
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    register(sys.argv[1], sys.argv[2], sys.argv[3])
