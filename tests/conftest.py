"""Shared test setup.

Scripts in model/ use flat imports (`from features import ...`) because they are run
as `python model/<script>.py`. Putting model/ on the path lets tests import them the same way.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "model"))
