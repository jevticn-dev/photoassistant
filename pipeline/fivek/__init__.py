"""FiveK adapter — everything that knows what this particular dataset looks like.

Adapter 1 of the three the plan foresees (§5.3). It reads a Lightroom catalogue,
translates PV2010 develop settings into edit schema v1, and decides which edits
the schema cannot represent.

**Why this is not in the library.** Nothing here generalises. The next adapter
reads XMP presets and the one after that reads user choices; they share the
schema and the fitting loop, which already live in ``photoassistant``, and
nothing else. A ``.lrcat`` reader in the library would be a promise that a second
caller exists.
"""
