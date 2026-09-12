"""The boundary between the library and the service.

The ``photoassistant`` library is imported both by the FastAPI service and by the
offline pipeline. If a service dependency ever creeps into it, the pipeline stops
working without FastAPI installed — and that surfaces only in phase 2, over 25,000
edits, overnight.

The boundary is therefore a checked condition rather than an agreement.

Note what this test does **not** cover: it inspects imports, not installed
packages. A dependency declared in the wrong place in ``pyproject.toml`` would
pass here. That claim is proven separately, by installing the library into an
empty environment and asking whether FastAPI is present.
"""

import importlib
import pkgutil
import sys

import photoassistant

FORBIDDEN_ROOTS = {"fastapi", "starlette", "uvicorn", "service"}


def _library_modules() -> list[str]:
    return [
        module.name
        for module in pkgutil.walk_packages(
            photoassistant.__path__,
            prefix=f"{photoassistant.__name__}.",
        )
    ]


def test_library_has_submodules() -> None:
    """Guards the test itself: it must not pass trivially if the package is renamed."""
    modules = _library_modules()

    expected = {
        "photoassistant.schema",
        "photoassistant.renderer",
        "photoassistant.fitting",
        "photoassistant.embeddings",
        "photoassistant.recommender",
        "photoassistant.storage",
    }
    assert expected <= set(modules)


def test_library_does_not_import_the_service_layer() -> None:
    for name in [photoassistant.__name__, *_library_modules()]:
        module = importlib.import_module(name)

        imported_roots = {
            value.__name__.split(".")[0]
            for value in vars(module).values()
            if isinstance(value, type(importlib))
        }

        leaked = imported_roots & FORBIDDEN_ROOTS
        assert not leaked, f"{name} imports {leaked}, which breaks the library boundary"


def test_the_embeddings_package_does_not_drag_torch_in() -> None:
    """The third dependency set has to be a boundary, not a habit.

    ``torch`` is about a gigabyte and only the step that computes CLIP vectors
    needs it, so it lives in the ``embeddings`` extra rather than in the library's
    dependencies. That only holds if importing the package does not reach for it:
    one convenience re-export in ``embeddings/__init__.py`` would put a gigabyte
    into every CI job and into the pipeline's install, and nothing would fail —
    the jobs would simply get slower and nobody would connect the two.

    Written against ``sys.modules`` rather than against the import list, because
    the failure is a transitive import somewhere below, not a name in this file.
    """
    for name in ["photoassistant", "photoassistant.embeddings"]:
        importlib.import_module(name)

    assert "torch" not in sys.modules, (
        "importing the library pulled in torch; the embeddings extra stops being "
        "a boundary the moment something imports photoassistant.embeddings.clip "
        "at module scope"
    )
