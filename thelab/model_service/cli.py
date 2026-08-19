"""CLI entry point for the local HTTP model service."""

from __future__ import annotations

import argparse
import warnings

import uvicorn

from .app import app


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thelab-model-service",
        description="Local HTTP service for approved model inference.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        warnings.warn(
            f"binding the model service to {args.host} exposes it beyond the local machine; "
            "use 127.0.0.1 for local-only operation.",
            stacklevel=1,
        )
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
