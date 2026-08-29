"""Put the repository root on the import path.

The pipeline is not an installed package — it is a directory of scripts that sits
next to the library and imports it. Tests therefore need the repository root on
``sys.path`` to reach ``pipeline.*``, which an installed project would get for
free and this one deliberately does not have.
"""

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from pipeline.environment import load  # noqa: E402

# Load .env, so that the tests which read the real catalogue actually run on a
# developer machine instead of skipping. A skip nobody notices is how a test
# stops testing: the run still says "passed", and the number that changed sits
# there unchecked. In CI there is no .env, so those tests skip for the honest
# reason — the dataset is not there and never will be.
load()
