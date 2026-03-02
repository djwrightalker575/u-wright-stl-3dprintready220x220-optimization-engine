from __future__ import annotations

import argparse

from orienter.ui.app import run_ui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orienter", description="Orientation optimizer tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    ui = sub.add_parser("ui", help="Start local operator interface")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8787)
    ui.add_argument("--reload", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "ui":
        run_ui(host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
