#!/usr/bin/env python3
"""Run the ResearchAtlas CLI from a source checkout: python atlas.py <command> ..."""

import sys

from atlaslib.cli import main

if __name__ == "__main__":
    sys.exit(main())
