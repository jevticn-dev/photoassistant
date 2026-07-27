"""
FiveK katalog — dubinska analiza struktura bitnih za ingestion.

Odgovara na tri pitanja:
  1. Koje kolekcije postoje i koliko slika imaju? (identifikacija eksperata A-E)
  2. Kako izgledaju semanticke oznake (keywords)?
  3. Za jednu fotografiju: svih ~12 verzija, kojoj kolekciji pripada koja,
     i njeni kljucni develop parametri (parsirani iz 'text' kolone).

Upotreba:
    python catalog_collections.py "D:\\...\\fivek.lrcat"
    python catalog_collections.py "D:\\...\\fivek.lrcat" --photo a0067
"""

import re
import sqlite3
import sys
import argparse
from pathlib import Path

# Parametri koje izvlacimo iz develop 'text' bloka (nas kandidat-inventar za semu)
KEY_PARAMS = [
    "Exposure", "HighlightRecovery", "FillLight", "Shadows", "Brightness",
    "Contrast", "Temperature", "Tint", "Saturation", "Vibrance", "Clarity",
    "ToneCurveName", "ProcessVersion", "Version",
]


def connect_readonly(p: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)


def parse_develop_text(text: str) -> dict:
    """Grubo parsiranje Lua-slicnog bloka: kljuc = vrednost parova na prvom nivou.

    Dovoljno za inspekciju; pravi parser pisemo u ingestion fazi.
    """
    if not text:
        return {}
    out = {}
    for m in re.finditer(r'(\w+)\s*=\s*("[^"]*"|-?[\d.]+|true|false)', text):
        out[m.group(1)] = m.group(2).strip('"')
    # ToneCurve tacke (lista brojeva u viticastim zagradama)
    tc = re.search(r'ToneCurve\s*=\s*\{([^}]*)\}', text)
    if tc:
        nums = [n.strip() for n in tc.group(1).replace("\n", " ").split(",") if n.strip()]
        out["ToneCurve_points"] = " ".join(nums)
    return out


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def analyze_collections(con: sqlite3.Connection) -> None:
    section("1. KOLEKCIJE (ovde ocekujemo eksperte A-E i input verzije)")
    try:
        rows = con.execute("""
            SELECT c.id_local, c.name, COUNT(ci.image) AS n
            FROM AgLibraryCollection c
            LEFT JOIN AgLibraryCollectionImage ci ON ci.collection = c.id_local
            GROUP BY c.id_local, c.name
            ORDER BY c.name
        """).fetchall()
    except sqlite3.Error as e:
        print(f"Upit nije prosao ({e}) — posalji mi PRAGMA table_info za AgLibraryCollection.")
        return
    for cid, name, n in rows:
        print(f"  id={cid:<8} {name:<45} {n} slika")


def analyze_keywords(con: sqlite3.Connection, limit: int = 40) -> None:
    section(f"2. SEMANTICKE OZNAKE (prvih {limit} po ucestalosti)")
    # Ime kolone sa nazivom keyword-a varira (name / lc_name) — introspekcija
    cols = [r[1] for r in con.execute("PRAGMA table_info(AgLibraryKeyword)")]
    name_col = "name" if "name" in cols else ("lc_name" if "lc_name" in cols else None)
    if not name_col:
        print(f"Ne prepoznajem kolonu imena. Kolone: {cols}")
        return
    rows = con.execute(f"""
        SELECT k.{name_col}, COUNT(ki.image) AS n
        FROM AgLibraryKeyword k
        JOIN AgLibraryKeywordImage ki ON ki.tag = k.id_local
        GROUP BY k.id_local
        ORDER BY n DESC
        LIMIT ?
    """, (limit,)).fetchall()
    for name, n in rows:
        print(f"  {str(name):<40} {n}")


def analyze_one_photo(con: sqlite3.Connection, base_name_like: str) -> None:
    section(f"3. SVE VERZIJE FOTOGRAFIJE '{base_name_like}*'")
    rows = con.execute("""
        SELECT i.id_local,
               f.baseName,
               i.copyName,
               (SELECT c.name
                  FROM AgLibraryCollectionImage ci
                  JOIN AgLibraryCollection c ON c.id_local = ci.collection
                 WHERE ci.image = i.id_local
                 LIMIT 1)         AS collection_name,
               d.text
        FROM Adobe_images i
        JOIN AgLibraryFile f ON f.id_local = i.rootFile
        LEFT JOIN Adobe_imageDevelopSettings d ON d.id_local = i.developSettingsIDCache
        WHERE f.baseName LIKE ?
        ORDER BY i.id_local
    """, (base_name_like + "%",)).fetchall()

    if not rows:
        print("Nema pogodaka — probaj drugi prefiks (npr. a0001).")
        return

    print(f"Nadjeno verzija: {len(rows)}\n")
    header = f"{'id':<8}{'kopija':<12}{'kolekcija':<35}" + "".join(f"{p:<14}" for p in
             ["Exposure", "Recovery", "FillLight", "Shadows", "Brightness", "Contrast"])
    print(header)
    print("-" * len(header))
    for id_local, base, copy_name, coll, text in rows:
        params = parse_develop_text(text or "")
        vals = [params.get("Exposure", "-"), params.get("HighlightRecovery", "-"),
                params.get("FillLight", "-"), params.get("Shadows", "-"),
                params.get("Brightness", "-"), params.get("Contrast", "-")]
        print(f"{id_local:<8}{str(copy_name):<12}{str(coll):<35}" + "".join(f"{v:<14}" for v in vals))

    # Pun parsiran ispis za jednu (poslednju) verziju, radi uvida u kompletan inventar
    print("\nKompletan parsiran blok poslednje verzije:")
    for k, v in sorted(parse_develop_text(rows[-1][4] or "").items()):
        print(f"  {k:<28} = {v}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lrcat")
    ap.add_argument("--photo", default="a0067", help="prefiks imena fajla (default a0067)")
    args = ap.parse_args()

    p = Path(args.lrcat)
    if not p.exists():
        sys.exit(f"Ne postoji fajl: {p}")

    con = connect_readonly(p)
    try:
        analyze_collections(con)
        analyze_keywords(con)
        analyze_one_photo(con, args.photo)
    finally:
        con.close()


if __name__ == "__main__":
    main()