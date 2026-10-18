#!/usr/bin/env python3
"""VCU Library Unpacker: recombines split zip parts (< 48 MB) and restores the
full SQLite database, CSV catalog, and JSONL data files locally.
"""
from __future__ import annotations
import glob, os, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "library_data"

TARGETS = [
    "vcu_biomedical_library.sqlite",
    "metadata_pubmed.csv",
    "metadata_pubmed.jsonl"
]

def unpack_file(filename: str):
    part_pattern = str(DATA_DIR / f"{filename}.zip.part*")
    parts = sorted(glob.glob(part_pattern))
    if not parts:
        # Check if legacy single .zip exists
        legacy_zip = DATA_DIR / f"{filename}.zip"
        if legacy_zip.exists():
            print(f"Unpacking legacy single archive {legacy_zip.name}...", flush=True)
            with zipfile.ZipFile(legacy_zip, "r") as zf:
                zf.extractall(DATA_DIR)
            return
        print(f"No parts found for {filename}.")
        return

    print(f"Recombining {len(parts)} parts for {filename}...", flush=True)
    temp_zip = DATA_DIR / f"{filename}.recomb.zip"
    with open(temp_zip, "wb") as outfile:
        for p in parts:
            with open(p, "rb") as infile:
                outfile.write(infile.read())

    print(f"Extracting {filename} from {temp_zip.name}...", flush=True)
    with zipfile.ZipFile(temp_zip, "r") as zf:
        zf.extractall(DATA_DIR)

    temp_zip.unlink()
    dst = DATA_DIR / filename
    print(f"  Restored {filename} ({dst.stat().st_size:,} bytes) successfully!", flush=True)

def main():
    print("=== Starting VCU Library Data Unpacking ===", flush=True)
    for t in TARGETS:
        unpack_file(t)
    print("\nAll library files restored and ready for research and querying!", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
