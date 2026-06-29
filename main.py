"""Application entry point for the NARVIS orchestration layer."""

from __future__ import annotations

from narvis import NARVISApplication


def main() -> int:
    """Initialize NARVIS and shut it down gracefully."""
    application = NARVISApplication()
    try:
        application.start()
        application.health()
        return 0
    finally:
        application.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
