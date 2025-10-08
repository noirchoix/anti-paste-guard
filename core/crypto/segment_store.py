from __future__ import annotations
import os, json, time, sqlite3, threading
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import asdict

from blake3 import blake3
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.hooks.events import BaseEvent
from core.crypto.aead import pick_suite, SUITE_AES_SIV, SUITE_CHACHA20P
from core.crypto.key_manager import MasterKeyManager, SessionKeys, derive_segment_key

DB_FILE = os.path.join(os.path.abspath("."), "apg_segments.sqlite3")

def utc_ts_ms() -> int:
    return int(time.time() * 1000)

def pad_to_block(data: bytes, block: int = 256) -> Tuple[bytes, int]:
    rem = (-len(data)) % block
    if rem == 0:
        return data, len(data)
    return data + b"\x00" * rem, len(data) + rem

class SegmentStore:
    """Append-only encrypted segment store with tamper-evident chain."""
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS segments(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts_utc INTEGER NOT NULL,
                  header BLOB NOT NULL,
                  body BLOB NOT NULL,
                  meta TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def insert_segment(self, ts_utc: int, header: bytes, body: bytes, meta: Dict[str, Any]) -> int:
      conn = sqlite3.connect(self.db_path)
      try:
          cur = conn.execute(
              "INSERT INTO segments(ts_utc, header, body, meta) VALUES (?,?,?,?)",
              (ts_utc, header, body, json.dumps(meta))
          )
          conn.commit()
          rowid = cur.lastrowid
          if rowid is None:
              raise RuntimeError("insert_segment: lastrowid is None (insert failed)")
          return int(rowid)
      finally:
          conn.close()

class SegmentWriter:
    """
    Buffers event records and periodically writes encrypted segments.
    - AEAD suite chosen per segment (crypto-agile)
    - Per-segment key ratchet (HKDF over session key + prev_tag)
    - Chain HMAC over header+body of each segment
    - Header signed with Ed25519
    """
    def __init__(self, store: SegmentStore, flush_sec: int = 60, max_events: int = 500):
        self.store = store
        self.flush_sec = flush_sec
        self.max_events = max_events

        self.km = MasterKeyManager()
        self.sess: SessionKeys = self.km.start_session()

        # Ratchet state
        self._current_key = self.sess.session_key
        self._prev_tag = b"\x00" * 16

        # Chain HMAC context
        self._hmac_key = self.sess.chain_hmac_key
        self._last_chain_tag = b"\x00" * 32

        # Buffers & thread
        self._buf: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thr: Optional[threading.Thread] = None
        self._next_flush = time.time() + self.flush_sec

    def start(self):
        if self._thr and self._thr.is_alive(): return
        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop(self):
        self._stop.set()
        if self._thr:
            self._thr.join(timeout=1.0)
        # final flush
        self._flush_if_needed(force=True)

    def add_event(self, ev: BaseEvent):
        # NOTE: events are already privacy-safe (no text), we serialize minimal record.
        rec = ev.to_record()
        with self._lock:
            self._buf.append(rec)
        self._flush_if_needed()

    # -------- internal --------

    def _loop(self):
        while not self._stop.is_set():
            time.sleep(0.5)
            self._flush_if_needed()

    def _flush_if_needed(self, force: bool = False):
        now = time.time()
        with self._lock:
            if not self._buf:
                self._next_flush = now + self.flush_sec
                return
            if not force and len(self._buf) < self.max_events and now < self._next_flush:
                return
            batch = self._buf
            self._buf = []
            self._next_flush = now + self.flush_sec

        self._write_segment(batch)

    def _write_segment(self, batch: List[Dict[str, Any]]):
        # Serialize payload as JSON lines for streaming forensics
        raw = ("\n".join(json.dumps(obj, separators=(",", ":")) for obj in batch)).encode("utf-8")

        # Pick suite, derive per-segment key from ratchet
        suite = pick_suite()
        key_len = 64 if suite.suite_id == SUITE_AES_SIV else 32
        info = f"segment-key:{suite.suite_id}".encode()
        seg_key = derive_segment_key(self._current_key, self._prev_tag, key_len, info)

        # Pad payload
        padded, padded_len = pad_to_block(raw, 256)

        # Prepare header (before signing)
        ts = utc_ts_ms()
        header = {
            "ver": 1,
            "suite": suite.suite_id,
            "session": self.sess.session_id,
            "padded_len": padded_len,
            "hkdf_info": info.decode(),
            "prev_tag": self._prev_tag.hex(),
            "sign_pub": self.sess.sign_public_bytes.hex(),
        }
        aad = json.dumps(header, separators=(",", ":")).encode("utf-8")

        # Encrypt
        ct, params = suite.encrypt(seg_key, padded, aad)
        header.update(params)

        # Chain HMAC over header+body
        h = hmac.HMAC(self._hmac_key, hashes.SHA256())
        h.update(aad)
        h.update(ct)
        h.update(self._last_chain_tag)
        chain_tag = h.finalize()
        header["chain_tag"] = chain_tag.hex()

        # Sign header (Ed25519) for integrity/authenticity
        sign_priv: Ed25519PrivateKey = self.sess.sign_private
        header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = sign_priv.sign(header_bytes)
        header["sig"] = signature.hex()

        # Update ratchet for next segment
        self._current_key = seg_key  # ratchet forward
        self._prev_tag = chain_tag[:16]  # small salt for next HKDF
        self._last_chain_tag = chain_tag

        # Persist
        seq = self.store.insert_segment(ts_utc=ts, header=json.dumps(header).encode("utf-8"), body=ct, meta={"count": len(batch)})
        # Optionally: return seq/log; we keep it silent here.
