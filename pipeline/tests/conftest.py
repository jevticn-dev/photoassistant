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
