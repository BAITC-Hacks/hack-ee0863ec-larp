"""Validate and atomically replace the shared catalogue from CSV/JSONL."""
import argparse
from pathlib import Path
from hackalem.catalog_store import DATABASE, import_catalog

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--database", type=Path, default=DATABASE)
    args = parser.parse_args()
    count = import_catalog(args.source, args.database)
    print(f"Imported {count} contractors. Website and console use this database.")

if __name__ == "__main__":
    main()
