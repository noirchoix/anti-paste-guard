from __future__ import annotations
import argparse, os, sys

def main():
    ap = argparse.ArgumentParser(prog="apg", description="Anti‑Paste Guard CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_verify = sub.add_parser("verify", help="Verify DB (signatures + chain + decrypt)")
    p_verify.add_argument("--db", default="apg_segments.sqlite3")
    p_verify.add_argument("--secrets", default="secrets")
    p_verify.add_argument("--limit", type=int)
    p_verify.add_argument("--signatures-only", action="store_true")
    p_verify.add_argument("--no-decrypt", action="store_true")
    p_verify.add_argument("-v", "--verbose", action="store_true")

    p_suites = sub.add_parser("suites", help="Show crypto suite counts in DB")
    p_suites.add_argument("--db", default="apg_segments.sqlite3")

    p_gui = sub.add_parser("run", help="Launch GUI")

    args = ap.parse_args()
    if args.cmd == "run":
        # launch GUI
        from ui.main_window import MainWindow
        import tkinter as tk
        root = MainWindow()
        root.mainloop()
        return

    if args.cmd == "verify":
        # delegate to the verifier script function (avoid spawning a 2nd Python)
        sys.path.insert(0, os.path.abspath("."))
        from tools.verify_segments import verify_db
        stats, errors = verify_db(
            db_path=args.db,
            secrets_dir=None if args.signatures_only else args.secrets,
            limit=args.limit,
            no_decrypt=args.no_decrypt,
            verbose=args.verbose,
        )
        print("\n=== Verification Summary ===")
        print(f"Segments checked    : {stats.total}")
        print(f"Header signatures   : {stats.sig_ok}/{stats.total} OK")
        if args.signatures_only:
            print("Chain/Decrypt       : skipped (no master key)")
        else:
            print(f"Chain HMAC          : {stats.chain_ok}/{stats.total} OK")
            print("Decrypt check       :", "skipped" if args.no_decrypt else f"{stats.decrypt_ok}/{stats.total} OK")
        if errors:
            print("\nErrors:")
            for e in errors:
                print(" -", e)
            sys.exit(2)
        else:
            print("\nAll checks passed.")
            sys.exit(0)

    if args.cmd == "suites":
        import sqlite3, json, collections
        conn = sqlite3.connect(args.db)
        rows = conn.execute("SELECT header FROM segments").fetchall()
        conn.close()
        ctr = collections.Counter()
        for (hb,) in rows:
            try:
                hdr = json.loads(hb.decode("utf-8"))
                ctr[hdr.get("suite","?")] += 1
            except Exception:
                ctr["?"] += 1
        print("Suite counts:")
        for k, v in ctr.most_common():
            print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
