from __future__ import annotations
import os
from typing import Tuple, Optional, Dict, Any

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

try:
    from Crypto.Cipher import AES  # pycryptodome
    HAVE_PYCRYPTO = True
except Exception:
    HAVE_PYCRYPTO = False

# Suite IDs for header
SUITE_CHACHA20P = "CHACHA20P"
SUITE_AES_SIV   = "AES_SIV"

class AEADSuite:
    suite_id: str
    key_len: int
    def encrypt(self, key: bytes, plaintext: bytes, aad: bytes) -> Tuple[bytes, Dict[str, Any]]:
        raise NotImplementedError
    def decrypt(self, key: bytes, ciphertext: bytes, aad: bytes, params: Dict[str, Any]) -> bytes:
        raise NotImplementedError

class ChaCha20PSuite(AEADSuite):
    suite_id = SUITE_CHACHA20P
    key_len = 32
    def encrypt(self, key: bytes, plaintext: bytes, aad: bytes) -> Tuple[bytes, Dict[str, Any]]:
        nonce = os.urandom(12)
        aead = ChaCha20Poly1305(key)
        ct = aead.encrypt(nonce, plaintext, aad)
        return ct, {"nonce": nonce.hex()}
    def decrypt(self, key: bytes, ciphertext: bytes, aad: bytes, params: Dict[str, Any]) -> bytes:
        nonce = bytes.fromhex(params["nonce"])
        aead = ChaCha20Poly1305(key)
        return aead.decrypt(nonce, ciphertext, aad)

class AESSIVSuite(AEADSuite):
    suite_id = SUITE_AES_SIV
    key_len = 64  # AES-SIV expects 64 bytes (two 256-bit keys) in pycryptodome
    def encrypt(self, key: bytes, plaintext: bytes, aad: bytes) -> Tuple[bytes, Dict[str, Any]]:
        if not HAVE_PYCRYPTO:  # fallback transparently (we won't raise)
            raise RuntimeError("AES-SIV unavailable")
        cipher = AES.new(key, AES.MODE_SIV)
        cipher.update(aad)
        ct, tag = cipher.encrypt_and_digest(plaintext)
        return ct + tag, {}  # tag is appended by pycryptodome; no nonce needed
    def decrypt(self, key: bytes, ciphertext: bytes, aad: bytes, params: Dict[str, Any]) -> bytes:
        if not HAVE_PYCRYPTO:
            raise RuntimeError("AES-SIV unavailable")
        ct, tag = ciphertext[:-16], ciphertext[-16:]
        cipher = AES.new(key, AES.MODE_SIV)
        cipher.update(aad)
        return cipher.decrypt_and_verify(ct, tag)

def pick_suite() -> AEADSuite:
    # Randomly choose between available suites; prefer diversity
    import os
    if HAVE_PYCRYPTO and (os.urandom(1)[0] & 1):
        return AESSIVSuite()
    return ChaCha20PSuite()
