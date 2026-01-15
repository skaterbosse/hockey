#!/usr/bin/env python3
import os

EXPECTED_DIR = "tests/expected"

def normalize_line(line):
    parts = line.rstrip("\n").split(";")

    # Ta bort trailing semicolons men behåll korrekta kolumner
    while parts and parts[-1] == "":
        parts.pop()

    # Efter pop:ar har gamla expected 12 kolumner
    # Vi kräver 13 kolumner i nya formatet
    if len(parts) == 12:
        # Lägg till iterations_total = same as iteration_fetched
        iteration_fetched = parts[-1]
        parts.append(iteration_fetched)

    # Om ännu färre kolumner → fyll på
    while len(parts) < 13:
        parts.append("")

    return ";".join(parts)


def process_file(path):
    print(f"[FIX] Processing → {path}")

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    normalized = [normalize_line(l) + "\n" for l in lines]

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(normalized)

    print(f"[FIX] ✔ Updated {path}")


def main():
    for fname in os.listdir(EXPECTED_DIR):
        if fname.endswith(".txt"):
            process_file(os.path.join(EXPECTED_DIR, fname))

    print("\n[FIX] ALL expected files normalized. READY for testing.\n")


if __name__ == "__main__":
    main()

