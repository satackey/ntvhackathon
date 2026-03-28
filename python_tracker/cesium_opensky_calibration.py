from __future__ import annotations

import sys

import uvicorn

from python_tracker.calibration import parse_web_cli_args
from python_tracker.web_calibration_server import create_app


def main() -> int:
    args = parse_web_cli_args(sys.argv[1:])
    uvicorn.run(create_app(args), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
