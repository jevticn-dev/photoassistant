"""Offline pipeline — scripts that fill the database from a dataset.

Not a library and not part of the deployed system. These scripts **import**
``photoassistant``; nothing imports them back. The rule from
`.claude/rules/pipeline.md` holds in both directions: anything the service could
also need belongs in the library, not here, and anything specific to one dataset
adapter belongs here, not in the library.

A package rather than loose files so that ``pipeline/tests`` can import what it
tests by name instead of by path.
"""
