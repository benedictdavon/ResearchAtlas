"""Allow `python -m atlaslib <command> ...`."""

import sys

from atlaslib.cli import main

sys.exit(main())
