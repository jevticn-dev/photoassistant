"""Finds words that mix Cyrillic and Latin letters.

    uv run --project ml python -m sandbox.check_script_mixing docs/thesis/rad.md ...

The thesis is written in Cyrillic, and terms that stay in Latin stay in Latin
**whole**. A word with one letter from the wrong alphabet is the kind of defect
no reader spots and no spell checker catches, because the two letters render
identically — a Latin "a" inside a Cyrillic word is invisible, and so is a word
whose first half is in one alphabet and second half in the other. Two of those
had already got through a draft when the project owner caught them by eye.

The examples are deliberately described rather than written out: written out,
they would look exactly like the correct spelling, which is the whole problem.

So the rule does not rely on attention. A word is reported when it contains at
least one Cyrillic **and** at least one Latin letter. Whole-Latin identifiers
(`pre512_key`, `sRGB`, `vector(30)`), whole-Cyrillic words, Greek letters and
digits are all left alone, since none of them mix the two alphabets.

Exit code is 1 if anything was found, so this can gate a commit.
"""

import re
import sys
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
# In source files a `\n` immediately before Cyrillic text makes the escape's "n"
# look like the first letter of that word — an artefact of the source, not a
# defect in any label. Escapes are dropped before scanning so the tool is usable
# on code as well as on the document.
ESCAPE = re.compile(r"\\[nrtvfab0]")


def alphabets(word: str) -> set[str]:
    """Which alphabets the letters of one word come from."""
    found = set()
    for character in word:
        name = unicodedata.name(character, "")
        if name.startswith("CYRILLIC"):
            found.add("ćirilica")
        elif name.startswith("LATIN"):
            found.add("latinica")
    return found


def scan(path: Path) -> list[tuple[int, str, str]]:
    findings = []
    for number, raw in enumerate(path.read_text("utf-8").splitlines(), start=1):
        line = ESCAPE.sub(" ", raw)
        for match in WORD.finditer(line):
            word = match.group()
            if len(alphabets(word)) > 1:
                findings.append((number, word, line.strip()))
    return findings


def main(arguments: list[str]) -> int:
    if not arguments:
        print(__doc__)
        return 2

    total = 0
    for name in arguments:
        path = Path(name)
        if not path.is_file():
            print(f"нема фајла: {path}")
            return 2
        findings = scan(path)
        total += len(findings)
        for number, word, line in findings:
            print(f"{path}:{number}: «{word}» — меша писма")
            print(f"    {line[:120]}")

    if total == 0:
        print(f"нема мешања писама, проверено фајлова: {len(arguments)}")
        return 0
    print(f"\nукупно: {total}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
