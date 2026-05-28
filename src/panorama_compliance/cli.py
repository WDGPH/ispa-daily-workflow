from __future__ import annotations

import argparse

from panorama_compliance.pipeline import deliver_outputs as deliver_outputs_pipeline
from panorama_compliance.pipeline import update_state as update_state_pipeline


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Panorama compliance unified CLI")
    parser.add_argument("command", choices=("deliver-outputs", "update-state"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    if parsed.command == "update-state":
        return update_state_pipeline.main(parsed.args)
    return deliver_outputs_pipeline.main(parsed.args)


def update_state(argv: list[str] | None = None) -> int:
    return update_state_pipeline.main(argv)


def deliver_outputs(argv: list[str] | None = None) -> int:
    return deliver_outputs_pipeline.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
