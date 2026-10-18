#!/usr/bin/env python3
"""VCU PubMed collector: retrieve bounded batches of bibliographic records and inventory results.

Requirements: Python 3.10+, standard library only. Intended for a research workstation with internet.
The collector fetches PubMed metadata and abstracts; it does NOT scrape publisher websites or bulk
-download copyrighted full text. Check each record's rights before reusing any abstract/full text.
Follow NCBI E-utilities policy: identify your tool/email and keep request rate <= 3/sec by default.
"""
from __future__ import annotations
import argparse, csv, http.client, json, os, sqlite3, sys, time, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
HERE = Path(__file__).resolve().parent


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def request(url: str, params: dict, min_delay: float, user_agent: str):
    request.last_time = getattr(request, "last_time", 0.0)
    wait = min_delay - (time.monotonic() - request.last_time)
    if wait > 0:
        time.sleep(wait)
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": user_agent, "Accept": "application/json, application/xml, text/xml"})
    last_err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
            request.last_time = time.monotonic()
            return body
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            last_err = exc
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(f"Request failed after retries: {last_err}")


def flatten_text(elem):
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def first_text(parent, path):
    e = parent.find(path)
    return flatten_text(e)


def pubdate_text(article):
    pubdate = article.find(".//JournalIssue/PubDate")
    if pubdate is None:
        pubdate = article.find(".//PubDate")
    if pubdate is None:
        return ""
    parts = []
    for tag in ("Year", "Month", "Day", "MedlineDate"):
        val = first_text(pubdate, tag)
        if val:
            parts.append(val)
    return " ".join(parts)


def parse_article(node, keep_abstract=True):
    article = node.find("MedlineCitation/Article")
    if article is None:
        return None
    pmid = first_text(node, "MedlineCitation/PMID")
    title = first_text(article, "ArticleTitle")
    journal = first_text(article, "Journal/Title")
    authors = []
    for a in article.findall("AuthorList/Author"):
        collective = first_text(a, "CollectiveName")
        last = first_text(a, "LastName")
        fore = first_text(a, "ForeName") or first_text(a, "Initials")
        name = collective or (f"{fore} {last}".strip())
        if name:
            authors.append(name)
    abstract_parts = []
    if keep_abstract:
        for a in article.findall("Abstract/AbstractText"):
            label = a.attrib.get("Label") or a.attrib.get("NlmCategory") or ""
            text = flatten_text(a)
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)
    doi = ""
    pmcid = ""
    for aid in node.findall("PubmedData/ArticleIdList/ArticleId"):
        typ = (aid.attrib.get("IdType") or "").lower()
        val = flatten_text(aid)
        if typ == "doi": doi = val
        elif typ == "pmc": pmcid = val
    if not doi:
        for eid in article.findall("ELocationID"):
            if eid.attrib.get("EIdType", "").lower() == "doi":
                doi = flatten_text(eid)
                break
    mesh = [flatten_text(x.find("DescriptorName")) for x in node.findall("MedlineCitation/MeshHeadingList/MeshHeading") if x.find("DescriptorName") is not None]
    keywords = [flatten_text(x) for x in node.findall("MedlineCitation/KeywordList/Keyword") if flatten_text(x)]
    pubtypes = [flatten_text(x) for x in article.findall("PublicationTypeList/PublicationType") if flatten_text(x)]
    return {
        "pmid": pmid, "pmcid": pmcid, "doi": doi, "title": title, "authors": authors,
        "journal": journal, "publication_date": pubdate_text(article), "language": [flatten_text(x) for x in article.findall("Language")],
        "publication_types": pubtypes, "mesh_terms": mesh, "keywords": keywords,
        "abstract": "\n".join(abstract_parts), "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        "source": "PubMed / NCBI E-utilities", "fetched_at": now_iso()
    }


def load_queries(path):
    queries = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("specialty") and row.get("query"):
                queries.append((row["specialty"].strip(), row["query"].strip()))
    return queries


def read_existing(path):
    rows = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            try:
                obj = json.loads(line)
                if obj.get("pmid"): rows[str(obj["pmid"])] = obj
            except json.JSONDecodeError:
                continue
    return rows


def db_setup(path):
    con = sqlite3.connect(path)
    con.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS records (
      pmid TEXT PRIMARY KEY, pmcid TEXT, doi TEXT, title TEXT, authors_json TEXT,
      journal TEXT, publication_date TEXT, language_json TEXT, publication_types_json TEXT,
      mesh_terms_json TEXT, keywords_json TEXT, abstract TEXT, pubmed_url TEXT, source TEXT,
      fetched_at TEXT, first_seen_run TEXT, last_seen_run TEXT
    );
    CREATE TABLE IF NOT EXISTS search_runs (
      run_id TEXT, specialty TEXT, query TEXT, search_count INTEGER,
      fetched_count INTEGER, new_count INTEGER, updated_count INTEGER,
      status TEXT, error TEXT, started_at TEXT, finished_at TEXT,
      PRIMARY KEY(run_id, specialty)
    );
    CREATE TABLE IF NOT EXISTS record_specialties (
      pmid TEXT NOT NULL, specialty TEXT NOT NULL, first_seen_run TEXT, last_seen_run TEXT,
      PRIMARY KEY(pmid, specialty), FOREIGN KEY(pmid) REFERENCES records(pmid)
    );
    CREATE TABLE IF NOT EXISTS source_registry (
      source_id TEXT PRIMARY KEY, source_name TEXT, source_type TEXT, official_url TEXT,
      priority TEXT, available_data TEXT, collection_method TEXT, full_text_policy TEXT,
      seed_records_curated_this_batch INTEGER, known_gaps_or_notes TEXT
    );
    ''')
    con.commit()
    return con


def upsert_record(con, rec, run_id):
    cur = con.execute("SELECT pmid FROM records WHERE pmid=?", (rec["pmid"],))
    existed = cur.fetchone() is not None
    con.execute('''INSERT INTO records (pmid,pmcid,doi,title,authors_json,journal,publication_date,language_json,
      publication_types_json,mesh_terms_json,keywords_json,abstract,pubmed_url,source,fetched_at,first_seen_run,last_seen_run)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(pmid) DO UPDATE SET 
      pmcid=CASE WHEN excluded.pmcid != '' THEN excluded.pmcid ELSE records.pmcid END,
      doi=CASE WHEN excluded.doi != '' THEN excluded.doi ELSE records.doi END,
      title=excluded.title,
      authors_json=excluded.authors_json, journal=excluded.journal, publication_date=excluded.publication_date,
      language_json=excluded.language_json, publication_types_json=excluded.publication_types_json,
      mesh_terms_json=excluded.mesh_terms_json, keywords_json=excluded.keywords_json,
      abstract=CASE WHEN excluded.abstract != '' THEN excluded.abstract ELSE records.abstract END,
      pubmed_url=excluded.pubmed_url, source=excluded.source, fetched_at=excluded.fetched_at, last_seen_run=excluded.last_seen_run''',
      (rec.get("pmid"), rec.get("pmcid"), rec.get("doi"), rec.get("title"), json.dumps(rec.get("authors", []), ensure_ascii=False),
       rec.get("journal"), rec.get("publication_date"), json.dumps(rec.get("language", []), ensure_ascii=False),
       json.dumps(rec.get("publication_types", []), ensure_ascii=False), json.dumps(rec.get("mesh_terms", []), ensure_ascii=False),
       json.dumps(rec.get("keywords", []), ensure_ascii=False), rec.get("abstract", ""), rec.get("pubmed_url"), rec.get("source"),
       rec.get("fetched_at"), run_id if not existed else "", run_id))
    return "updated" if existed else "new"


def write_csv(path, rows):
    fieldnames = ["pmid", "pmcid", "doi", "title", "authors", "journal", "publication_date", "language", "publication_types", "mesh_terms", "keywords", "abstract", "pubmed_url", "source", "fetched_at"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = dict(r)
            for k in ("authors", "language", "publication_types", "mesh_terms", "keywords"):
                out[k] = "; ".join(out.get(k) or []) if isinstance(out.get(k), list) else out.get(k, "")
            w.writerow(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--email", default=os.getenv("NCBI_EMAIL", ""), help="Contact email registered/owned by tool developer")
    ap.add_argument("--tool", default=os.getenv("NCBI_TOOL", "VCUBiomedicalLibrary"), help="NCBI tool name without spaces")
    ap.add_argument("--api-key", default=os.getenv("NCBI_API_KEY", ""), help="Optional NCBI API key")
    ap.add_argument("--query-file", default=str(HERE / "specialty_queries.csv"))
    ap.add_argument("--source-registry", default=str(HERE / "source_registry.csv"))
    ap.add_argument("--out", default=str(HERE / "library_data"))
    ap.add_argument("--max-per-topic", type=int, default=50, help="Maximum articles to fetch per topic (default 50)")
    ap.add_argument("--batch-size", type=int, default=100, help="EFetch size; 100 is conservative")
    ap.add_argument("--date-from", default="", help="Optional publication date YYYY/MM/DD")
    ap.add_argument("--date-to", default="", help="Optional publication date YYYY/MM/DD")
    ap.add_argument("--retstart", type=int, default=0, help="Offset in search results to start fetching from (default 0)")
    ap.add_argument("--no-abstracts", action="store_true", help="Store metadata only; recommended for a redistributable catalog")
    ap.add_argument("--seed-only", action="store_true", help="Initialize local database from seed_records.csv without network requests")
    args = ap.parse_args()
    if not args.email and not args.seed_only:
        print("ERROR: Provide --email or set NCBI_EMAIL before live collection. For a metadata-only local initialization, use --seed-only.", file=sys.stderr)
        return 2
    if args.max_per_topic < 1 or args.batch_size < 1 or args.retstart < 0:
        print("ERROR: --max-per-topic and --batch-size must be positive, --retstart must be non-negative.", file=sys.stderr); return 2
    outdir = Path(args.out); outdir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("vcu_%Y%m%dT%H%M%SZ")
    dbpath = outdir / "vcu_biomedical_library.sqlite"
    con = db_setup(dbpath)
    existing = read_existing(outdir / "metadata_pubmed.jsonl")
    if args.seed_only:
        seed = HERE / "seed_records.csv"
        seeded = 0
        with open(seed, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rec = {"pmid": row["pmid"], "pmcid": row.get("pmcid", ""), "doi": row.get("doi", ""), "title": row["title"],
                       "authors": [row.get("authors", "").strip()] if row.get("authors", "").strip() else [], "journal": row.get("journal", ""), "publication_date": row.get("year", ""),
                       "language": [], "publication_types": [row.get("record_type", "")], "mesh_terms": [], "keywords": [], "abstract": "",
                       "pubmed_url": row.get("pubmed_url", ""), "source": "PubMed result; manually curated seed (not API-fetched)", "fetched_at": now_iso(),
                       "seed_verification_status": row.get("verification_status", ""), "seed_notes": row.get("notes", "")}
                existing[str(rec["pmid"])] = rec
                upsert_record(con, rec, run_id)
                if row.get("specialty"):
                    con.execute("INSERT INTO record_specialties VALUES (?,?,?,?) ON CONFLICT(pmid,specialty) DO UPDATE SET last_seen_run=excluded.last_seen_run", (str(rec["pmid"]), row["specialty"], run_id, run_id))
                seeded += 1
        con.commit()
        print(f"Seeded {seeded} bibliographic records into {dbpath}; no network request made.")
    else:
        user_agent = f"{args.tool}/1.0 (contact: {args.email})"
        common = {"db": "pubmed", "tool": args.tool, "email": args.email, "retmode": "json"}
        if args.api_key: common["api_key"] = args.api_key
        query_rows = load_queries(Path(args.query_file))
        inventory = []
        log_file = outdir / "collection_runs.jsonl"
        for i, (specialty, base_query) in enumerate(query_rows):
            started = now_iso(); term = base_query
            if args.date_from and args.date_to:
                term = f'({term}) AND ("{args.date_from}"[Date - Publication] : "{args.date_to}"[Date - Publication])'
            elif args.date_from:
                term = f'({term}) AND ("{args.date_from}"[Date - Publication] : "3000"[Date - Publication])'
            params = dict(common); params.update({"term": term, "retmax": args.max_per_topic, "retstart": args.retstart, "sort": "pub date"})
            try:
                body = request(BASE + "esearch.fcgi", params, 0.36 if not args.api_key else 0.15, user_agent)
                result = json.loads(body.decode("utf-8"))["esearchresult"]
                total = int(result.get("count", 0)); ids = result.get("idlist", [])
                recs = []
                for offset in range(0, len(ids), args.batch_size):
                    chunk = ids[offset:offset + args.batch_size]
                    if not chunk: continue
                    fp = dict(common); fp.update({"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"})
                    xml_bytes = request(BASE + "efetch.fcgi", fp, 0.36 if not args.api_key else 0.15, user_agent)
                    root = ET.fromstring(xml_bytes)
                    for node in root.findall("PubmedArticle"):
                        rec = parse_article(node, keep_abstract=not args.no_abstracts)
                        if rec:
                            rec["matched_specialties"] = [specialty]
                            recs.append(rec)
                new_count = updated_count = 0
                for rec in recs:
                    old_rec = existing.get(str(rec["pmid"]), {})
                    prior_tags = old_rec.get("matched_specialties", [])
                    if isinstance(prior_tags, str): prior_tags = [prior_tags]
                    rec["matched_specialties"] = sorted(set(prior_tags + rec.get("matched_specialties", [])))
                    if not rec.get("abstract") and old_rec.get("abstract"):
                        rec["abstract"] = old_rec["abstract"]
                    status = upsert_record(con, rec, run_id)
                    con.execute("INSERT INTO record_specialties VALUES (?,?,?,?) ON CONFLICT(pmid,specialty) DO UPDATE SET last_seen_run=excluded.last_seen_run", (str(rec["pmid"]), specialty, run_id, run_id))
                    if status == "new": new_count += 1
                    else: updated_count += 1
                    existing[str(rec["pmid"])] = rec
                con.commit()
                row = {"run_id": run_id, "specialty": specialty, "query": term, "search_count": total,
                       "fetched_count": len(recs), "new_count": new_count, "updated_count": updated_count,
                       "status": "success", "error": "", "started_at": started, "finished_at": now_iso()}
                print(f"[{i+1}/{len(query_rows)}] {specialty}: Found {total:,} records | Fetched {len(recs)} (New: {new_count}, Updated: {updated_count})", flush=True)
            except Exception as exc:
                row = {"run_id": run_id, "specialty": specialty, "query": term, "search_count": "",
                       "fetched_count": 0, "new_count": 0, "updated_count": 0, "status": "error",
                       "error": f"{type(exc).__name__}: {exc}", "started_at": started, "finished_at": now_iso()}
                print(f"[{i+1}/{len(query_rows)}] WARNING [{specialty}]: {row['error']}", file=sys.stderr, flush=True)
            con.execute("INSERT OR REPLACE INTO search_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (row["run_id"], row["specialty"], row["query"], row["search_count"] if row["search_count"] != "" else None,
                 row["fetched_count"], row["new_count"], row["updated_count"], row["status"], row["error"], row["started_at"], row["finished_at"]))
            con.commit()
            inventory.append(row)
            with open(log_file, "a", encoding="utf-8") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
            # Update current specialty_inventory.csv progressively
            fields = ["run_id", "specialty", "query", "search_count", "fetched_count", "new_count", "updated_count", "status", "error", "started_at", "finished_at"]
            with open(outdir / "specialty_inventory.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(inventory)
        # Also save archive copy of inventory with run_id
        with open(outdir / f"specialty_inventory_{run_id}.csv", "w", newline="", encoding="utf-8-sig") as f:
            fields = ["run_id", "specialty", "query", "search_count", "fetched_count", "new_count", "updated_count", "status", "error", "started_at", "finished_at"]
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(inventory)
        successes = sum(1 for x in inventory if x["status"] == "success")
        print(f"Collection run {run_id} completed: {successes}/{len(inventory)} topics succeeded; Inventory: {outdir / 'specialty_inventory.csv'}", flush=True)
    # Export all records currently stored in the JSONL/SQLite store.
    rows = list(existing.values())
    tmp = outdir / "metadata_pubmed.jsonl.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for pmid in sorted(existing.keys(), key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x)):
            f.write(json.dumps(existing[pmid], ensure_ascii=False) + "\n")
    tmp.replace(outdir / "metadata_pubmed.jsonl")
    write_csv(outdir / "metadata_pubmed.csv", rows)
    # Sync source registry into SQLite if present.
    regpath = Path(args.source_registry)
    if regpath.exists():
        with open(regpath, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                con.execute("INSERT OR REPLACE INTO source_registry VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    row.get("source_id"), row.get("source_name"), row.get("source_type"), row.get("official_url"),
                    row.get("priority"), row.get("available_data"), row.get("collection_method"), row.get("full_text_policy"),
                    int(row.get("seed_records_curated_this_batch") or 0), row.get("known_gaps_or_notes")))
        con.commit()
    con.close()
    status = {"run_id": run_id, "run_mode": "seed-only" if args.seed_only else "live_api_collection", "live_api_requests_made": not args.seed_only, "finished_at": now_iso(), "database": str(dbpath), "records_in_jsonl": len(existing),
              "note": "Seed-only mode makes no network requests; live search counts remain unmeasured. In live mode, inventory counts come from E-utilities ESearch responses. Seed records are not claimed as a comprehensive corpus."}
    (outdir / "pipeline_status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
