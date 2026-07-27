"""
FiveK katalog — statistika develop parametara preko SVIH ekspertskih edita.

Cilj: kompletan inventar parametara + opsezi vrednosti, kao empirijski osnov
za zakljucavanje v1 seme izmene.

Ispisuje, samo za kolekcije eksperata A-E (25.000 edita):
  1. Frekvenciju svakog kljuca (u koliko % edita se javlja)
  2. Min / max / prosek za numericke parametre
  3. Raspodelu ToneCurveName vrednosti
  4. Koliko edita koristi HSL / split toning / grayscale

Upotreba:
    python catalog_param_stats.py "D:\\...\\fivek.lrcat"
    python catalog_param_stats.py "D:\\...\\fivek.lrcat" --csv stats.csv
"""

import re
import csv
import sqlite3
import sys
import argparse
from pathlib import Path
from collections import defaultdict, Counter

EXPERT_COLLECTIONS = ("A", "B", "C", "D", "E")

# Kljucevi koje tretiramo kao ne-parametarske (tehnicki metapodaci, ne izgled)
META_KEYS = {
    "CameraProfile", "CameraProfileDigest", "Version", "ProcessVersion",
    "WhiteBalance", "ToneCurveName", "AutoGrayscaleMix", "ConvertToGrayscale",
    "LensProfileSetup", "AutoLateralCA", "LensProfileEnable",
}

HSL_PREFIXES = ("HueAdjustment", "SaturationAdjustment", "LuminanceAdjustment")
SPLIT_PREFIX = "SplitToning"


def connect_readonly(p: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)


NUM_RE = re.compile(r'^-?\d+(\.\d+)?$')
PAIR_RE = re.compile(r'(\w+)\s*=\s*("[^"]*"|-?[\d.]+|true|false)')


def parse_pairs(text: str) -> dict:
    out = {}
    for m in PAIR_RE.finditer(text or ""):
        out[m.group(1)] = m.group(2).strip('"')
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lrcat")
    ap.add_argument("--csv", help="opciono: putanja za CSV izvoz statistike")
    args = ap.parse_args()

    p = Path(args.lrcat)
    if not p.exists():
        sys.exit(f"Ne postoji fajl: {p}")

    con = connect_readonly(p)

    placeholders = ",".join("?" for _ in EXPERT_COLLECTIONS)
    query = f"""
        SELECT c.name, d.text
        FROM AgLibraryCollection c
        JOIN AgLibraryCollectionImage ci ON ci.collection = c.id_local
        JOIN Adobe_images i              ON i.id_local = ci.image
        JOIN Adobe_imageDevelopSettings d ON d.id_local = i.developSettingsIDCache
        WHERE c.name IN ({placeholders}) AND d.text IS NOT NULL
    """

    key_count: Counter = Counter()
    num_stats: dict = defaultdict(lambda: {"min": float("inf"), "max": float("-inf"),
                                           "sum": 0.0, "n": 0})
    curve_names: Counter = Counter()
    per_expert: Counter = Counter()
    hsl_used = split_used = grayscale_used = 0
    total = 0

    for expert, text in con.execute(query, EXPERT_COLLECTIONS):
        total += 1
        per_expert[expert] += 1
        pairs = parse_pairs(text)

        if pairs.get("ConvertToGrayscale") == "true":
            grayscale_used += 1
        if any(k.startswith(HSL_PREFIXES) and pairs[k] not in ("0", "0.0")
               for k in pairs):
            hsl_used += 1
        if any(k.startswith(SPLIT_PREFIX) and pairs[k] not in ("0", "0.0")
               for k in pairs):
            split_used += 1

        curve_names[pairs.get("ToneCurveName", "(nema)")] += 1

        for k, v in pairs.items():
            key_count[k] += 1
            if k not in META_KEYS and NUM_RE.match(v):
                s = num_stats[k]
                x = float(v)
                s["min"] = min(s["min"], x)
                s["max"] = max(s["max"], x)
                s["sum"] += x
                s["n"] += 1

    con.close()

    print(f"Ukupno ekspertskih edita: {total}")
    print("Po ekspertu:", dict(sorted(per_expert.items())))

    print("\n" + "=" * 78)
    print(f"{'KLJUC':<34}{'javlja se':>10}{'%':>7}{'min':>9}{'max':>9}{'prosek':>9}")
    print("=" * 78)
    for k, n in key_count.most_common():
        pct = 100.0 * n / total if total else 0
        s = num_stats.get(k)
        if s and s["n"]:
            print(f"{k:<34}{n:>10}{pct:>6.1f}%{s['min']:>9.2f}{s['max']:>9.2f}"
                  f"{s['sum']/s['n']:>9.2f}")
        else:
            print(f"{k:<34}{n:>10}{pct:>6.1f}%{'':>9}{'':>9}{'':>9}")

    print("\nToneCurveName raspodela:")
    for name, n in curve_names.most_common(10):
        print(f"  {name:<30} {n}  ({100.0*n/total:.1f}%)")

    print(f"\nEditi sa HSL izmenama:        {hsl_used}  ({100.0*hsl_used/max(total,1):.1f}%)")
    print(f"Editi sa split toning-om:     {split_used}  ({100.0*split_used/max(total,1):.1f}%)")
    print(f"Editi konvertovani u crno-belo: {grayscale_used}  ({100.0*grayscale_used/max(total,1):.1f}%)")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["key", "count", "pct", "min", "max", "mean"])
            for k, n in key_count.most_common():
                s = num_stats.get(k)
                if s and s["n"]:
                    w.writerow([k, n, round(100.0*n/total, 2),
                                s["min"], s["max"], round(s["sum"]/s["n"], 4)])
                else:
                    w.writerow([k, n, round(100.0*n/total, 2), "", "", ""])
        print(f"\nCSV sacuvan: {args.csv}")


if __name__ == "__main__":
    main()