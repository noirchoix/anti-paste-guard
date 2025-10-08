from __future__ import annotations
import os, json, time
from dataclasses import dataclass
from typing import Optional, Tuple

from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization, hmac
from cryptography.hazmat.primitives.asymmetric import ed25519

SECRETS_DIR = os.path.join(os.path.abspath("."), "secrets")
MASTER_KEY_FILE = os.path.join(SECRETS_DIR, "master.key")
SIGN_PRIV_FILE  = os.path.join(SECRETS_DIR, "signing.key")

def _ensure_secrets_dir():
    os.makedirs(SECRETS_DIR, exist_ok=True)
    try:
        os.chmod(SECRETS_DIR, 0o700)
    except Exception:
        pass

@dataclass
class SessionKeys:
    session_id: str
    session_key: bytes      # 32 bytes
    chain_hmac_key: bytes   # 32 bytes (for HMAC chain)
    sign_private: ed25519.Ed25519PrivateKey
    sign_public_bytes: bytes

class MasterKeyManager:
    """
    Dev-friendly sealed file fallback:
      - 32-byte master key stored in ./secrets/master.key with 0700 perms
      - Ed25519 signing key in ./secrets/signing.key
    Swap this for OS keystore later (DPAPI/Keychain).
    """
    def __init__(self):
        _ensure_secrets_dir()

    def load_or_create_master(self) -> bytes:
        if os.path.exists(MASTER_KEY_FILE):
            with open(MASTER_KEY_FILE, "rb") as f:
                return f.read()
        key = os.urandom(32)
        with open(MASTER_KEY_FILE, "wb") as f:
            f.write(key)
        try:
            os.chmod(MASTER_KEY_FILE, 0o600)
        except Exception:
            pass
        return key

    def load_or_create_signing_key(self) -> ed25519.Ed25519PrivateKey:
        if os.path.exists(SIGN_PRIV_FILE):
            with open(SIGN_PRIV_FILE, "rb") as f:
                data = f.read()
            return ed25519.Ed25519PrivateKey.from_private_bytes(data)
        priv = ed25519.Ed25519PrivateKey.generate()
        with open(SIGN_PRIV_FILE, "wb") as f:
            f.write(priv.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption()
            ))
        try:
            os.chmod(SIGN_PRIV_FILE, 0o600)
        except Exception:
            pass
        return priv

    def start_session(self) -> SessionKeys:
        master = self.load_or_create_master()
        # derive fresh per-session key with random salt
        session_salt = os.urandom(16)
        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=session_salt, info=b"session-key")
        session_key = hkdf.derive(master)

        # derive chain HMAC key
        hkdf2 = HKDF(algorithm=hashes.SHA256(), length=32, salt=session_salt, info=b"hmac-chain")
        chain_key = hkdf2.derive(master)

        # signing key
        sign_priv = self.load_or_create_signing_key()
        sign_pub_bytes = sign_priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )

        session_id = session_salt.hex()
        return SessionKeys(session_id=session_id, session_key=session_key, chain_hmac_key=chain_key,
                           sign_private=sign_priv, sign_public_bytes=sign_pub_bytes)

def derive_segment_key(prev_key: bytes, prev_tag: bytes, length: int, info: bytes) -> bytes:
    """
    Ratchet: derive a new key for each segment from the previous key + prev_tag.
    'length' controls key length (32 for ChaCha20P, 64 for AES-SIV).
    """
    hkdf = HKDF(algorithm=hashes.SHA256(), length=length, salt=prev_tag or b"\x00"*16, info=info)
    return hkdf.derive(prev_key)
