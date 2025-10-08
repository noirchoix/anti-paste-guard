from __future__ import annotations
import argparse, json, os, sqlite3, sys
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, List

from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

# Optional AES-SIV (pycryptodome)
try:
    from Crypto.Cipher import AES  # type: ignore
    HAVE_PYCRYPTO = True
except Exception:
    HAVE_PYCRYPTO = False

SUITE_CHACHA20P = "CHACHA20P"
SUITE_AES_SIV   = "AES_SIV"

# ---- utilities ----

def hkdf_derive(master: bytes, length: int, salt: bytes, info: bytes) -> bytes:
    hk = HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info)
    return hk.derive(master)

def aad_from_header_stem(header: Dict[str, Any]) -> bytes:
    """
    Reconstruct the AAD exactly as the writer did:
    only these fields, in this order, compact separators.
    """
    stem_keys = ["ver", "suite", "session", "padded_len", "hkdf_info", "prev_tag", "sign_pub"]
    stem = {k: header[k] for k in stem_keys}
    return json.dumps(stem, separators=(",", ":")).encode("utf-8")

def header_bytes_for_sig(header: Dict[str, Any]) -> bytes:
    # Sign/verify the header *without* the "sig" field.
    hdr = dict(header)
    hdr.pop("sig", None)
    return json.dumps(hdr, separators=(",", ":"), sort_keys=True).encode("utf-8")

@dataclass
class VerifyStats:
    total: int = 0
    sig_ok: int = 0
    chain_ok: int = 0
    decrypt_ok: int = 0

# ---- verifier core ----

def verify_db(
    db_path: str,
    secrets_dir: Optional[str],
    limit: Optional[int],
    no_decrypt: bool,
    verbose: bool,
) -> Tuple[VerifyStats, List[str]]:
    """
    Returns (stats, errors). If secrets_dir is provided (with secrets/master.key),
    full chain-HMAC verification is performed. Otherwise, only signatures are verified.
    """
    stats = VerifyStats()
    errors: List[str] = []

    # Load DB rows
    conn = sqlite3.connect(db_path)
    try:
        q = "SELECT seq, ts_utc, header, body FROM segments ORDER BY seq ASC"
        if limit:
            q = f"{q} LIMIT {int(limit)}"
        rows = conn.execute(q).fetchall()
    finally:
        conn.close()

    if not rows:
        return stats, ["No rows found in segments table."]

    # Load master key if available (needed for chain HMAC and decryption)
    master_key: Optional[bytes] = None
    if secrets_dir:
        key_path = os.path.join(secrets_dir, "master.key")
        if os.path.exists(key_path):
            with open(key_path, "rb") as f:
                master_key = f.read()
        else:
            errors.append(f"master.key not found at {key_path}; chain/decrypt checks will be skipped.")

    # State per session for chain verification and ratchet decryption
    session_state: Dict[str, Dict[str, Any]] = {}
    # Initialize prev_chain_tag per session_id to 32 zero bytes when session starts
    ZERO32 = b"\x00" * 32
    ZERO16 = b"\x00" * 16

    for (seq, ts_utc, header_blob, body) in rows:
        stats.total += 1
        try:
            header: Dict[str, Any] = json.loads(header_blob.decode("utf-8"))
        except Exception as e:
            errors.append(f"[seq={seq}] header JSON decode failed: {e}")
            continue

        # 1) Verify header signature (Ed25519) — public verification, no secrets needed
        try:
            sign_pub_hex = header["sign_pub"]
            sig_hex = header["sig"]
            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(sign_pub_hex))
            pub.verify(bytes.fromhex(sig_hex), header_bytes_for_sig(header))
            stats.sig_ok += 1
            if verbose:
                print(f"[seq={seq}] signature OK")
        except Exception as e:
            errors.append(f"[seq={seq}] signature verification FAILED: {e}")
            # continue with other checks to list all issues
        # 2) Chain HMAC over (AAD || ciphertext || prev_chain_tag)
        # Requires master key.
        chain_ok = False
        if master_key is not None:
            try:
                session_id = header["session"]  # hex of session salt
                sess = session_state.get(session_id)
                if sess is None:
                    # derive chain key for this session
                    chain_key = hkdf_derive(master_key, 32, bytes.fromhex(session_id), b"hmac-chain")
                    sess = {
                        "chain_key": chain_key,
                        "prev_chain_tag": ZERO32,
                        # decryption ratchet:
                        "current_key": hkdf_derive(master_key, 32, bytes.fromhex(session_id), b"session-key"),
                    }
                    session_state[session_id] = sess

                aad = aad_from_header_stem(header)
                h = hmac.HMAC(sess["chain_key"], hashes.SHA256())
                h.update(aad)
                h.update(body)
                h.update(sess["prev_chain_tag"])
                expected_chain_tag = h.finalize().hex()

                if expected_chain_tag != header["chain_tag"]:
                    raise ValueError("chain_tag mismatch")

                sess["prev_chain_tag"] = bytes.fromhex(expected_chain_tag)
                stats.chain_ok += 1
                chain_ok = True
                if verbose:
                    print(f"[seq={seq}] chain OK")
            except Exception as e:
                errors.append(f"[seq={seq}] chain verification FAILED: {e}")

        # 3) Optional decryption verification (AEAD integrity & key ratchet)
        #    Requires master key. If AES-SIV suite and pycryptodome missing, skip gracefully.
        if master_key is not None and not no_decrypt:
            try:
                suite = header["suite"]
                hkdf_info = header["hkdf_info"].encode("utf-8")
                prev_tag_hex = header.get("prev_tag", "00" * 16)
                prev_tag = bytes.fromhex(prev_tag_hex)

                sess = session_state[header["session"]]
                # Derive per-segment key by ratcheting from the current key
                # - For CHACHA20P: key_len=32
                # - For AES_SIV:   key_len=64
                if suite == SUITE_CHACHA20P:
                    key_len = 32
                elif suite == SUITE_AES_SIV:
                    key_len = 64
                else:
                    raise ValueError(f"Unknown suite: {suite}")

                seg_key = hkdf_derive(sess["current_key"], key_len, prev_tag, hkdf_info)

                # AAD is the stem only (as used during encrypt)
                aad = aad_from_header_stem(header)

                if suite == SUITE_CHACHA20P:
                    nonce_hex = header["nonce"]
                    aead = ChaCha20Poly1305(seg_key)
                    _pt = aead.decrypt(bytes.fromhex(nonce_hex), body, aad)
                    # We don't need plaintext; success == integrity OK
                else:
                    if not HAVE_PYCRYPTO:
                        if verbose:
                            print(f"[seq={seq}] AES-SIV not available; skipping decrypt check.")
                    else:
                        # pycryptodome AES-SIV appends tag to ciphertext (last 16 bytes)
                        ct, tag = body[:-16], body[-16:]
                        cipher = AES.new(seg_key, AES.MODE_SIV)
                        cipher.update(aad)
                        _pt = cipher.decrypt_and_verify(ct, tag)

                # Ratchet forward "current_key" for the session
                sess["current_key"] = seg_key
                stats.decrypt_ok += 1
                if verbose:
                    print(f"[seq={seq}] decrypt OK")
            except Exception as e:
                errors.append(f"[seq={seq}] decrypt verification FAILED: {e}")

    return stats, errors

def main():
    ap = argparse.ArgumentParser(description="Verify Anti-Paste Guard segments: signatures, chain, and optional decrypt.")
    ap.add_argument("--db", default="apg_segments.sqlite3", help="Path to SQLite DB (default: apg_segments.sqlite3)")
    ap.add_argument("--secrets", default="secrets", help="Path to secrets dir containing master.key (default: ./secrets)")
    ap.add_argument("--limit", type=int, default=None, help="Check only the first N segments (ordered by seq)")
    ap.add_argument("--signatures-only", action="store_true", help="Verify only Ed25519 signatures (no secrets needed)")
    ap.add_argument("--no-decrypt", action="store_true", help="Skip AEAD decrypt check (keeps chain check if secrets are present)")
    ap.add_argument("--verbose", "-v", action="store_true", help="Verbose per-segment output")
    args = ap.parse_args()

    secrets_dir = None if args.signatures_only else args.secrets

    stats, errors = verify_db(
        db_path=args.db,
        secrets_dir=secrets_dir,
        limit=args.limit,
        no_decrypt=args.no_decrypt,
        verbose=args.verbose,
    )

    print("\n=== Verification Summary ===")
    print(f"Segments checked    : {stats.total}")
    print(f"Header signatures   : {stats.sig_ok}/{stats.total} OK")
    if secrets_dir:
        print(f"Chain HMAC          : {stats.chain_ok}/{stats.total} OK")
        if args.no_decrypt:
            print(f"Decrypt check       : skipped")
        else:
            print(f"Decrypt check       : {stats.decrypt_ok}/{stats.total} OK")
    else:
        print("Chain/Decrypt       : skipped (no master key)")

    if errors:
        print("\nErrors:")
        for e in errors:
            print(" -", e)
        sys.exit(2)
    else:
        print("\nAll checks passed.")
        sys.exit(0)

if __name__ == "__main__":
    main()
