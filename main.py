# main.py
from __future__ import annotations
import structlog
from app.logging_config import configure_logging
from ui.main_window import MainWindow

def main() -> None:
    configure_logging(debug=True)
    log = structlog.get_logger()

    log.info("app.start", msg="Launching Anti-Paste Guard")
    win = MainWindow()
    win.set_status("Ready")
    win.mainloop()
    log.info("app.stop", msg="Exited cleanly")

if __name__ == "__main__":
    main()
