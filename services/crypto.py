import base64
import hashlib
import hmac
import os

from flask import current_app


def _get_key():
    secret = current_app.config['SECRET_KEY'].encode()
    return hashlib.sha256(secret).digest()


def encrypt_value(plaintext):
    key = _get_key()
    plaintext_bytes = plaintext.encode('utf-8')
    # Generate random salt
    salt = os.urandom(16)
    # Derive encryption key from key + salt
    derived = hashlib.sha256(key + salt).digest()
    # XOR encrypt
    encrypted = bytes(p ^ derived[i % len(derived)] for i, p in enumerate(plaintext_bytes))
    # HMAC for integrity
    mac = hmac.new(key, salt + encrypted, hashlib.sha256).digest()[:16]
    # Pack: salt(16) + mac(16) + encrypted(N)
    return base64.urlsafe_b64encode(salt + mac + encrypted).decode()


def decrypt_value(ciphertext):
    key = _get_key()
    raw = base64.urlsafe_b64decode(ciphertext.encode())
    if len(raw) < 33:
        raise ValueError('Invalid ciphertext')
    salt = raw[:16]
    stored_mac = raw[16:32]
    encrypted = raw[32:]
    # Verify HMAC
    expected_mac = hmac.new(key, salt + encrypted, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(stored_mac, expected_mac):
        raise ValueError('Integrity check failed')
    # Derive same key and decrypt
    derived = hashlib.sha256(key + salt).digest()
    decrypted = bytes(e ^ derived[i % len(derived)] for i, e in enumerate(encrypted))
    return decrypted.decode('utf-8')
