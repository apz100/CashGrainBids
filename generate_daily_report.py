"""Compatibility entry point for the daily cash-bid report.

The implementation lives in :mod:`cashgrainbids.reporting`. Keep this file so
the existing scheduled task and documented command continue to work.
"""

from cashgrainbids.reporting import main


if __name__ == "__main__":
    raise SystemExit(main())
