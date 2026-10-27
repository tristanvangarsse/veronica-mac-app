#!/usr/bin/env python3
"""Veronica entry point; isolated imports come only from its own code bundle."""
from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "__media_worker__":
    from media_worker import main
    raise SystemExit(main(sys.argv[2:]))

if __name__ == "__main__":
    import os
    import signal
    import threading
    import time
    try:
        os.setsid()
    except OSError:
        pass
    def stop(signum, frame):
        raise SystemExit(130)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if os.environ.get("VERONICA_GUI_RUN") == "1":
        parent = os.getppid()
        def watch_parent():
            while os.getppid() == parent:
                time.sleep(1)
            os.kill(os.getpid(), signal.SIGTERM)
        threading.Thread(target=watch_parent, daemon=True).start()

from media_maintenance import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
