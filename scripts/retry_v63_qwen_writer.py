#!/usr/bin/env python3
"""Retry v63 writing from an already completed Qwen perception result."""

import argparse
import json
from pathlib import Path

from backend.agent import run_agent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--attempt', default='ir-r2')
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    source = json.loads((run_dir / 'source_input.json').read_text(encoding='utf-8'))
    return run_agent(source, run_dir / args.attempt, None,
                     perception_from=run_dir / 'media_analysis.json',
                     intent_resolved=True)


if __name__ == '__main__':
    raise SystemExit(main())
