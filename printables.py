#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from scheduler import command_printables


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Imagination Day printables")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to the scheduler config file (default: config.json)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for generated PDFs (defaults to config pdf_output_dir)",
    )
    args = parser.parse_args()
    return command_printables(Path(args.config).expanduser(), args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
