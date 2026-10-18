#!/usr/bin/env python3
"""VCU Library Packer: compresses large library data files into split zip parts (< 48 MB each)
to comply with GitHub's 100 MB file size limit without requiring Git LFS.
"""
from __future__ import annotations
import glob, os, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "library_data"
CHUNK_SIZE = 45 * 1024 * 1024  # 45 MB chunks

TARGETS = [
    "vcu_biomedical_library.sqlite",
    "metadata_pubmed.csv",
    "metadata_pubmed.jsonl"
]

def pack_file(filename: str):
    src = DATA_DIR / filename
    if not src.exists():
        print(f"Skipping {filename}: not found.")
        return

    print(f"Compressing {filename} ({src.stat().st_size:,} bytes)...", flush=True)
    temp_zip = DATA_DIR / f"{filename}.temp.zip"
    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(src, arcname=filename)

    zip_bytes = temp_zip.read_bytes()
    temp_zip.unlink()

    total_len = len(zip_bytes)
    print(f"  Compressed size: {total_len:,} bytes. Splitting into 45 MB parts...", flush=True)

    # Clean old parts
    for old_part in glob.glob(str(DATA_DIR / f"{filename}.zip.part*")):
        os.remove(old_part)

    part_idx = 1
    for i in range(0, total_len, CHUNK_SIZE):
        chunk = zip_bytes[i:i + CHUNK_SIZE]
        part_path = DATA_DIR / f"{filename}.zip.part{part_idx:02d}"
        part_path.write_bytes(chunk)
        print(f"  Created {part_path.name}: {len(chunk):,} bytes", flush=True)
        part_idx += 1

def main():
    print("=== Starting VCU Library Data Packaging ===", flush=True)
    for t in TARGETS:
        pack_file(t)
    print("\nAll data files packaged into GitHub-safe parts (< 48 MB) successfully!", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
