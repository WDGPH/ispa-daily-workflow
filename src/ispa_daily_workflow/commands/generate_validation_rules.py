from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ispa_daily_workflow.validation import rule_catalog_markdown

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the public validation rule lookup index."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if validation-rules.md is not current.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "validation-rules.md",
        help="Output path (default: validation-rules.md).",
    )
    args = parser.parse_args(argv)

    output_path = args.output
    if not output_path.is_absolute():
        output_path = (PROJECT_ROOT / output_path).resolve()

    content = rule_catalog_markdown()
    if args.check:
        if not output_path.exists():
            print(f"{output_path} is missing", file=sys.stderr)
            return 1
        current = output_path.read_text(encoding="utf-8")
        if current != content:
            print(f"{output_path} is not current", file=sys.stderr)
            return 1
        return 0

    output_path.write_text(content, encoding="utf-8")
    print(f"Wrote {output_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
