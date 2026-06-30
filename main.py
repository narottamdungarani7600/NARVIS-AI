"""Application entry point for the NARVIS orchestration layer."""

from __future__ import annotations

from narvis import NARVISApplication


def main() -> int:
    """Initialize NARVIS, launch the dashboard, and shut down gracefully."""
    application = NARVISApplication()
    try:
        application.start()
        dashboard = application.container.resolve("dashboard")
        dashboard.run()
        return 0
    finally:
        application.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
