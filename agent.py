#!/usr/bin/env python3
"""Backward-compatible CLI entry point; implementation lives in backend/."""

from backend.agent import main


if __name__ == "__main__":
    raise SystemExit(main())
