"""Allow ``python -m atlas`` to invoke the CLI."""

from .cli import main

raise SystemExit(main())
