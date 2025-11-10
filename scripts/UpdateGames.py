#!/usr/bin/env python3
import sys
import csv

def update_games(complete_path, lite_path):
    # Load complete file (19 columns per row)
    with open(complete_path, newline="", encoding="utf-8-sig") as f:
        complete_rows = list(csv.reader(f, delimiter=";"))

    # Build lookup dictionary for complete file
    lookup = {}
    for idx, row in enumerate(complete_rows):
        if len(row) < 7:
            continue  # skip malformed rows

        key = (
            row[0].strip(),  # date
            row[1].strip(),  # time
            row[2].strip(),  # series_name
            row[3].strip(),  # link_to_series
            row[5].strip(),  # home_team
            row[6].strip(),  # away_team
        )
        lookup[key] = idx

    # Process lite file (12 columns per row)
    updated = 0
    with open(lite_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")
        for row in reader:
            if len(row) < 9:
                continue  # skip malformed lines

            key = (
                row[0].strip(),  # date
                row[1].strip(),  # time
                row[2].strip(),  # series_name
                row[3].strip(),  # link_to_series
                row[5].strip(),  # home_team
                row[6].strip(),  # away_team
            )

            if key in lookup:
                i = lookup[key]

                # Update ONLY result and result_link
                complete_rows[i][7] = row[7]  # result
                complete_rows[i][8] = row[8]  # result_link
                updated += 1

    # Save updated complete file (overwrite)
    with open(complete_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerows(complete_rows)

    print(f"✅ Done — updated {updated} games.")

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 UpdateGames.py <path to Complete game file> <path to Lite Game File>")
        sys.exit(1)

    update_games(sys.argv[1], sys.argv[2])

if __name__ == "__main__":
    main()

