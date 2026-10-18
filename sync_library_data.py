#!/usr/bin/env python3
"""Sync Library Data:
Exports all records from SQLite database to:
1. library_data/metadata_pubmed.jsonl
2. library_data/metadata_pubmed.csv
And executes SQLite VACUUM to optimize database footprint.
"""
from __future__ import annotations
import csv, json, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "library_data"
DB_PATH = DATA_DIR / "vcu_biomedical_library.sqlite"

def main():
    print(f"=== Syncing SQLite database to JSONL and CSV ===", flush=True)
    t0 = time.time()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    
    total_records = cur.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    print(f"Total records in SQLite: {total_records:,}", flush=True)
    
    jsonl_path = DATA_DIR / "metadata_pubmed.jsonl"
    csv_path = DATA_DIR / "metadata_pubmed.csv"
    
    jsonl_tmp = DATA_DIR / "metadata_pubmed.jsonl.tmp"
    csv_tmp = DATA_DIR / "metadata_pubmed.csv.tmp"
    
    csv_fields = [
        "pmid", "pmcid", "doi", "title", "authors", "journal", "publication_date",
        "language", "publication_types", "mesh_terms", "keywords", "abstract",
        "pubmed_url", "source", "fetched_at"
    ]
    
    cur.execute("""
        SELECT pmid, pmcid, doi, title, authors_json, journal, publication_date,
               language_json, publication_types_json, mesh_terms_json, keywords_json,
               abstract, pubmed_url, source, fetched_at
        FROM records
        ORDER BY rowid ASC
    """)
    
    count = 0
    with open(jsonl_tmp, "w", encoding="utf-8") as f_jsonl, \
         open(csv_tmp, "w", newline="", encoding="utf-8-sig") as f_csv:
        
        csv_writer = csv.DictWriter(f_csv, fieldnames=csv_fields)
        csv_writer.writeheader()
        
        while True:
            rows = cur.fetchmany(10000)
            if not rows:
                break
            for r in rows:
                authors = json.loads(r["authors_json"] or "[]")
                langs = json.loads(r["language_json"] or "[]")
                pubtypes = json.loads(r["publication_types_json"] or "[]")
                mesh = json.loads(r["mesh_terms_json"] or "[]")
                keywords = json.loads(r["keywords_json"] or "[]")
                
                # Write JSONL
                rec_dict = {
                    "pmid": r["pmid"],
                    "pmcid": r["pmcid"] or "",
                    "doi": r["doi"] or "",
                    "title": r["title"] or "",
                    "authors": authors,
                    "journal": r["journal"] or "",
                    "publication_date": r["publication_date"] or "",
                    "language": langs,
                    "publication_types": pubtypes,
                    "mesh_terms": mesh,
                    "keywords": keywords,
                    "abstract": r["abstract"] or "",
                    "pubmed_url": r["pubmed_url"] or "",
                    "source": r["source"] or "",
                    "fetched_at": r["fetched_at"] or ""
                }
                f_jsonl.write(json.dumps(rec_dict, ensure_ascii=False) + "\n")
                
                # Write CSV
                csv_row = {
                    "pmid": r["pmid"],
                    "pmcid": r["pmcid"] or "",
                    "doi": r["doi"] or "",
                    "title": r["title"] or "",
                    "authors": "; ".join(authors),
                    "journal": r["journal"] or "",
                    "publication_date": r["publication_date"] or "",
                    "language": "; ".join(langs),
                    "publication_types": "; ".join(pubtypes),
                    "mesh_terms": "; ".join(mesh),
                    "keywords": "; ".join(keywords),
                    "abstract": r["abstract"] or "",
                    "pubmed_url": r["pubmed_url"] or "",
                    "source": r["source"] or "",
                    "fetched_at": r["fetched_at"] or ""
                }
                csv_writer.writerow(csv_row)
                count += 1
            print(f"  Processed {count:,}/{total_records:,} records...", flush=True)
            
    # Atomic replace
    if jsonl_path.exists():
        jsonl_path.unlink()
    jsonl_tmp.rename(jsonl_path)
    
    if csv_path.exists():
        csv_path.unlink()
    csv_tmp.rename(csv_path)
    
    print(f"Successfully exported {count:,} records to JSONL and CSV in {time.time()-t0:.1f}s!", flush=True)
    
    print("Running VACUUM on SQLite database...", flush=True)
    t_vac = time.time()
    con.execute("VACUUM;")
    con.close()
    print(f"VACUUM completed in {time.time()-t_vac:.1f}s!", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
