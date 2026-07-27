"""
Istraživanje FiveK Lightroom kataloga (.lrcat = SQLite baza).

Upotreba:
    python catalog_overview.py "D:\\putanja\\do\\fivek.lrcat"                # pregled kataloga
    python catalog_overview.py "D:\\...\\fivek.lrcat" --dng "D:\\...\\a0001.dng"  # + dekodiraj jedan DNG

Za DNG deo treba:  pip install rawpy imageio
Za sam katalog ne treba ništa van standardne biblioteke.

Skript NE menja katalog (otvara ga read-only).
"""

import sqlite3
import sys
import argparse
from pathlib import Path


def connect_readonly(lrcat_path: Path) -> sqlite3.Connection:
    # URI mode=ro garantuje da ništa ne upisujemo u katalog
    return sqlite3.connect(f"file:{lrcat_path.as_posix()}?mode=ro", uri=True)


def list_tables(con: sqlite3.Connection) -> None:
    print("=" * 70)
    print("TABELE U KATALOGU (ime, broj redova)")
    print("=" * 70)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    for t in tables:
        try:
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        except sqlite3.Error:
            n = "?"
        print(f"  {t:55s} {n}")
    print(f"\nUkupno tabela: {len(tables)}")


def show_columns(con: sqlite3.Connection, table: str) -> list[str]:
    cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
    print(f"\nKolone tabele {table}:")
    for c in cols:
        print(f"  - {c}")
    return cols


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def sample_develop_settings(con: sqlite3.Connection, limit: int = 3) -> None:
    """Ispisuje develop parametre za nekoliko slika.

    Očekivana struktura (Lightroom konvencija, proveravamo je upravo ovim skriptom):
      - Adobe_images: jedna slika ili virtuelna kopija po redu (copyName za kopije)
      - Adobe_imageDevelopSettings: kolona 'text' sadrži serijalizovane parametre
      - AgLibraryFile: originalno ime fajla
    Ako se imena razlikuju, skript to prijavljuje umesto da pukne.
    """
    print("\n" + "=" * 70)
    print("UZORAK DEVELOP PARAMETARA")
    print("=" * 70)

    needed = ["Adobe_images", "Adobe_imageDevelopSettings"]
    missing = [t for t in needed if not table_exists(con, t)]
    if missing:
        print(f"PAŽNJA: očekivane tabele ne postoje: {missing}")
        print("Pogledaj listu tabela gore i javi koja imena vidiš umesto njih.")
        return

    show_columns(con, "Adobe_images")
    show_columns(con, "Adobe_imageDevelopSettings")

    has_file = table_exists(con, "AgLibraryFile")
    file_join = (
        "LEFT JOIN AgLibraryFile f ON i.rootFile = f.id_local" if has_file else ""
    )
    file_col = "f.baseName" if has_file else "NULL"

    query = f"""
        SELECT i.id_local,
               {file_col}      AS base_name,
               i.copyName      AS copy_name,
               d.text          AS develop_text
        FROM Adobe_images i
        JOIN Adobe_imageDevelopSettings d ON d.image = i.id_local
        {file_join}
        WHERE d.text IS NOT NULL
        ORDER BY i.id_local
        LIMIT ?
    """
    try:
        rows = con.execute(query, (limit,)).fetchall()
    except sqlite3.Error as e:
        print(f"\nUpit nije prošao ({e}).")
        print("Verovatno se neka kolona drugačije zove — pošalji ispis kolona gore.")
        return

    for id_local, base_name, copy_name, text in rows:
        print("\n" + "-" * 70)
        print(f"Slika id={id_local}  fajl={base_name}  kopija={copy_name!r}")
        print("-" * 70)
        print(text if len(text) < 4000 else text[:4000] + "\n... [skraćeno]")

    # Koliko slika ima develop settings ukupno?
    n = con.execute(
        "SELECT COUNT(*) FROM Adobe_imageDevelopSettings WHERE text IS NOT NULL"
    ).fetchone()[0]
    print(f"\nRedova sa develop parametrima ukupno: {n}")
    print("(5.000 fotografija x 5 eksperata bi trebalo da bude ~25.000+,")
    print(" u zavisnosti od toga kako su kopije organizovane)")


def decode_dng(dng_path: Path) -> None:
    print("\n" + "=" * 70)
    print(f"DEKODIRANJE DNG: {dng_path.name}")
    print("=" * 70)
    try:
        import rawpy
        import imageio.v3 as iio
    except ImportError:
        print("Nedostaju biblioteke. Pokreni:  pip install rawpy imageio")
        return

    with rawpy.imread(str(dng_path)) as raw:
        rgb = raw.postprocess()  # demosaicing + osnovna obrada, podrazumevana podešavanja

    h, w = rgb.shape[:2]
    print(f"PRAVA rezolucija posle dekodiranja: {w} x {h} piksela")
    print("(uporedi sa thumbnail-om od ~256x170 koji Windows prikazuje)")

    out = dng_path.with_suffix(".preview.jpg")
    iio.imwrite(out, rgb, quality=90)
    print(f"Pun preview sačuvan u: {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Istraživanje FiveK .lrcat kataloga")
    ap.add_argument("lrcat", help="putanja do fivek.lrcat")
    ap.add_argument("--dng", help="opciono: putanja do jednog DNG fajla za probno dekodiranje")
    ap.add_argument("--samples", type=int, default=3, help="koliko slika ispisati (default 3)")
    args = ap.parse_args()

    lrcat_path = Path(args.lrcat)
    if not lrcat_path.exists():
        sys.exit(f"Ne postoji fajl: {lrcat_path}")

    con = connect_readonly(lrcat_path)
    try:
        list_tables(con)
        sample_develop_settings(con, args.samples)
    finally:
        con.close()

    if args.dng:
        decode_dng(Path(args.dng))


if __name__ == "__main__":
    main()