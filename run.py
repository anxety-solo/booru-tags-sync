#!/usr/bin/env python3
""" Convenience entrypoint: `python run.py` from the repo root """

import sys

# === TAGSYNC ===
from tagsync.main import main

sys.exit(main())
