#!/usr/bin/env python3
from pathlib import Path
import csv
from collections import Counter

# Paths
BASE_DIR = Path(__file__).resolve().parent
TICKETS_DIR = BASE_DIR / "tickets"
OUT_CSV = BASE_DIR / "delhaize_name_counts.csv"


def main():
    counts = Counter()
    for p in sorted(TICKETS_DIR.glob("*.csv")):
        try:
            with p.open(newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                if "product_name" not in (r.fieldnames or []):
                    continue
                for row in r:
                    name = (row.get("product_name") or "").strip()
                    if name:
                        counts[name] += 1
        except Exception as e:
            print(f"Skip {p.name}: {e}")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "count"])
        for name, cnt in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
            w.writerow([name, cnt])

    print(f"Wrote {OUT_CSV} ({len(counts)} unique names)")


if __name__ == "__main__":
    main()
