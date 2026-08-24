"""Allow ``python -m pipeline`` to invoke the ingestion CLI."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
