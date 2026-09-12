"""Make the storage tests find the local containers without any manual setup.

Those tests skip themselves when no database or object store answers. A skip that
depends on the developer having exported ten variables by hand is a trap: the run
says "13 skipped", nobody reads it, and the storage layer goes untested for weeks
while the containers were up the whole time. So the repository's ``.env`` is read
here, if it exists, and its host-side values are mapped onto the names the library
reads.

Nothing is invented and nothing is overridden: variables already set win, and in
CI there is no ``.env``, so the storage tests skip there for the real reason —
the schema they check is created by EF migrations, which the ML job cannot run.

**Why this reaches into ``pipeline/``.** The mapping from ``*_LOCAL`` to the
container-side names exists there already, and having it in two places is how the
two drift apart. The direction is wrong for the library, which must never import
the pipeline, and right for a test, which is allowed to know how this repository
is laid out. The boundary that matters is still enforced:
``test_library_boundary.py`` walks the library itself.

**Why not ``. ./.env`` in the shell instead.** ``.env`` holds
``FIVEK_DATASET_PATH=D:/Fakultet/IV godina/...`` — an unquoted value with a space
in it. A shell sourcing that file splits it and fails; the parser used here takes
everything after the first ``=``.
"""

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from pipeline.environment import load  # noqa: E402

load()
