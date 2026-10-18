#!/usr/bin/env python3
"""VCU Specialty Source Harvester: expand biomedical library with:
1. Top-tier International Journals: NEJM, The Lancet, JAMA, JAMA Intern Med, Ann Intern Med, BMJ.
2. Vietnamese Biomedical Research & indexed clinical publications from Vietnam medical institutions.
3. Dieutri.vn clinical treatment protocols, laboratory diagnostics, pharmacology, and pathology monographs.

Strict requirement: Preserves FULL, UNSHORTENED text and author abstracts (không tóm tắt, không rút gọn).
"""
from __future__ import annotations
import csv, hashlib, html, http.client, json, os, re, sqlite3, sys, time, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "library_data"
DB_PATH = DATA_DIR / "vcu_biomedical_library.sqlite"

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def request_url(url: str, params: dict | None = None, min_delay: float = 0.36, user_agent: str = "VCUBiomedicalLibrary/1.0", timeout: int = 45):
    request_url.last_time = getattr(request_url, "last_time", 0.0)
    wait = min_delay - (time.monotonic() - request_url.last_time)
    if wait > 0:
        time.sleep(wait)
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers={"User-Agent": user_agent, "Accept": "application/json, application/xml, text/html, */*"})
    last_err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            request_url.last_time = time.monotonic()
            return body
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            last_err = exc
            time.sleep(min(2 ** attempt, 10))
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

def parse_pubmed_article(node):
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
        "abstract": "\n\n".join(abstract_parts), "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        "source": "PubMed / NCBI E-utilities", "fetched_at": now_iso()
    }

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

def determine_specialty(title: str, abstract: str, mesh: list[str]) -> list[str]:
    text = (title + " " + abstract + " " + " ".join(mesh)).lower()
    specs = []
    if any(k in text for k in ["cancer", "neoplasm", "tumor", "carcinoma", "oncolog", "leukemia", "lymphoma"]):
        specs.append("Cancer")
    if any(k in text for k in ["surg", "operat", "resect", "laparoscop", "graft", "transplant"]):
        specs.append("Surgery")
    if any(k in text for k in ["immune", "immunol", "antibod", "t cell", "autoimmun", "vaccin", "checkpoint"]):
        specs.append("Immunology")
    if any(k in text for k in ["gene", "genom", "mutation", "sequencing", "dna", "rna", "crispr", "heredit"]):
        specs.append("Genetics")
    if any(k in text for k in ["drug", "pharmacol", "dose", "pharmacokinet", "adverse reaction", "toxic"]):
        specs.append("Pharmacology")
    if any(k in text for k in ["patholog", "histolog", "biopsy", "morpholog", "cytolog"]):
        specs.append("Pathology")
    if any(k in text for k in ["biomarker", "assay", "diagnostic", "laboratory", "pcr", "elisa", "sensitivity", "specificity"]):
        specs.append("Laboratory diagnostics")
    if any(k in text for k in ["computational", "bioinformatic", "machine learning", "algorithm", "deep learning", "neural network"]):
        specs.append("Computational biology")
    if any(k in text for k in ["anatom", "morpholog", "cadaver", "dissect"]):
        specs.append("Anatomy")
    if not specs:
        specs.append("Internal medicine")
    return specs

def harvest_pubmed_journal(con, journal_name: str, query_term: str, run_id: str, max_items: int = 1000):
    user_agent = "VCUBiomedicalLibrary/1.0 (contact: dotu020806@gmail.com)"
    common = {"db": "pubmed", "tool": "VCUBiomedicalLibrary", "email": "dotu020806@gmail.com", "retmode": "json"}
    params = dict(common)
    params.update({"term": query_term, "retmax": max_items, "retstart": 0, "sort": "pub date"})
    
    print(f"\n[PubMed] Querying journal: {journal_name}...", flush=True)
    body = request_url(BASE + "esearch.fcgi", params, 0.36, user_agent)
    result = json.loads(body.decode("utf-8"))["esearchresult"]
    total = int(result.get("count", 0))
    ids = result.get("idlist", [])
    print(f"  Found {total:,} articles | Fetching top {len(ids)} with full abstracts...", flush=True)
    
    recs = []
    batch_size = 100
    for offset in range(0, len(ids), batch_size):
        chunk = ids[offset:offset + batch_size]
        if not chunk: continue
        fp = dict(common); fp.update({"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"})
        xml_bytes = request_url(BASE + "efetch.fcgi", fp, 0.36, user_agent)
        root = ET.fromstring(xml_bytes)
        for node in root.findall("PubmedArticle"):
            rec = parse_pubmed_article(node)
            if rec:
                recs.append(rec)
    
    new_c = updated_c = 0
    for rec in recs:
        specs = determine_specialty(rec["title"], rec["abstract"], rec["mesh_terms"])
        status = upsert_record(con, rec, run_id)
        for s in specs:
            con.execute("INSERT INTO record_specialties VALUES (?,?,?,?) ON CONFLICT(pmid,specialty) DO UPDATE SET last_seen_run=excluded.last_seen_run", (str(rec["pmid"]), s, run_id, run_id))
        if status == "new": new_c += 1
        else: updated_c += 1
    con.commit()
    print(f"  Saved {len(recs)} articles from {journal_name} (New: {new_c}, Updated: {updated_c})", flush=True)
    return len(recs), new_c

def harvest_dieutri_articles(con, run_id: str):
    print("\n[Dieutri.vn] Harvesting Vietnamese clinical protocols & laboratory guides...", flush=True)
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    sections = [
        ("phacdo", "Internal medicine"),
        ("phacdokysinhtrung", "Internal medicine"),
        ("phacdocoxuongkhop", "Internal medicine"),
        ("phacdonoitiet", "Internal medicine"),
        ("phacdothantietnieu", "Internal medicine"),
        ("phacdotieuhoa", "Internal medicine"),
        ("xetnghiem", "Laboratory diagnostics"),
        ("quytrinhxetnghiem", "Laboratory diagnostics"),
        ("chandoandieutri", "Surgery"),
        ("thuocgoc", "Pharmacology"),
        ("dongduoc", "Pharmacology"),
        ("benhly", "Pathology")
    ]
    
    visited_urls = set()
    harvested = 0
    new_c = 0
    
    for sec_path, default_spec in sections:
        sec_url = f"https://www.dieutri.vn/{sec_path}/"
        try:
            raw = request_url(sec_url, min_delay=0.5, user_agent=user_agent).decode("utf-8", errors="ignore")
            # find all sub-links in this section
            pattern = rf'href=[\'"](https?://www\.dieutri\.vn/{sec_path}/[^\'"]+)[\'"]'
            links = set(re.findall(pattern, raw))
            # Also relative links
            rel_pattern = rf'href=[\'"](/{sec_path}/[^\'"]+)[\'"]'
            for rel in re.findall(rel_pattern, raw):
                links.add("https://www.dieutri.vn" + rel)
                
            article_links = [l for l in links if not l.endswith(f"/{sec_path}/") and not l.endswith(".css") and not l.endswith(".png") and not l.endswith(".jpg")]
            print(f"  Section /{sec_path}/: Discovered {len(article_links)} clinical topic pages", flush=True)
            
            for art_url in article_links[:30]:  # Up to 30 clinical topics per section
                if art_url in visited_urls:
                    continue
                visited_urls.add(art_url)
                
                try:
                    art_raw = request_url(art_url, min_delay=0.4, user_agent=user_agent).decode("utf-8", errors="ignore")
                    m_title = re.search(r'<h1[^>]*>(.*?)</h1>', art_raw, re.DOTALL | re.IGNORECASE)
                    title = html.unescape(re.sub(r'<[^>]+>', '', m_title.group(1)).strip()) if m_title else ""
                    if not title or len(title) < 5:
                        continue
                    
                    # Clean out scripts, styles, header, footer, nav
                    clean = re.sub(r'<(script|style|nav|header|footer)[^>]*>.*?</\1>', '', art_raw, flags=re.DOTALL | re.IGNORECASE)
                    clean_text = html.unescape(re.sub(r'<[^>]+>', ' ', clean))
                    lines = [l.strip() for l in clean_text.splitlines() if l.strip()]
                    full_content = "\n\n".join(lines)
                    
                    if len(full_content) < 300:
                        continue
                        
                    # Generate stable unique ID based on URL
                    doc_id = "DIEUTRI-" + hashlib.md5(art_url.encode()).hexdigest()[:12]
                    
                    specs = determine_specialty(title, full_content, [])
                    if default_spec not in specs:
                        specs.append(default_spec)
                        
                    rec = {
                        "pmid": doc_id,
                        "pmcid": "",
                        "doi": art_url,
                        "title": title,
                        "authors": ["Ban biên tập Dieutri.vn"],
                        "journal": "Dieutri.vn - Phác đồ điều trị & Y học lâm sàng",
                        "publication_date": "2024-2026",
                        "language": ["Vietnamese"],
                        "publication_types": ["Clinical Practice Guideline", "Monograph"],
                        "mesh_terms": [],
                        "keywords": [sec_path, "Y học Việt Nam", "Phác đồ điều trị"],
                        "abstract": full_content,  # 100% full unshortened clinical text
                        "pubmed_url": art_url,
                        "source": "Dieutri.vn Clinical Portal",
                        "fetched_at": now_iso()
                    }
                    
                    status = upsert_record(con, rec, run_id)
                    for s in specs:
                        con.execute("INSERT INTO record_specialties VALUES (?,?,?,?) ON CONFLICT(pmid,specialty) DO UPDATE SET last_seen_run=excluded.last_seen_run", (doc_id, s, run_id, run_id))
                    harvested += 1
                    if status == "new": new_c += 1
                except Exception as e:
                    continue
        except Exception as e:
            print(f"  Warning on section /{sec_path}/: {e}", file=sys.stderr)
            
    con.commit()
    print(f"  Harvested {harvested} full clinical articles from Dieutri.vn (New: {new_c})", flush=True)
    return harvested, new_c

def main():
    con = sqlite3.connect(DB_PATH)
    run_id = datetime.now(timezone.utc).strftime("vcu_harvest_%Y%m%dT%H%M%SZ")
    print(f"=== Starting Multi-Source Harvester (Run ID: {run_id}) ===", flush=True)
    
    # 1. Target Top-tier International Journals
    journals = [
        ("The New England Journal of Medicine (NEJM)", '"N Engl J Med"[Journal]'),
        ("The Lancet", '"Lancet"[Journal]'),
        ("JAMA", '"JAMA"[Journal]'),
        ("JAMA Internal Medicine", '"JAMA Intern Med"[Journal]'),
        ("Annals of Internal Medicine", '"Ann Intern Med"[Journal]'),
        ("The BMJ", '"BMJ"[Journal]'),
    ]
    
    total_new = 0
    for name, q in journals:
        total, new_c = harvest_pubmed_journal(con, name, q, run_id, max_items=1000)
        total_new += new_c
        
    # 2. Target Vietnamese Medical Research & Institutions
    vn_query = '("Vietnam"[Affiliation] OR "Viet Nam"[Affiliation] OR "Vietnam"[Title/Abstract]) AND ("clinical trial"[Publication Type] OR "review"[Publication Type] OR "guideline"[Publication Type] OR "research"[Title/Abstract])'
    vn_tot, vn_new = harvest_pubmed_journal(con, "Vietnam Biomedical Research (Hanoi Medical Univ, Cho Ray, Bach Mai, Ho Chi Minh UMP)", vn_query, run_id, max_items=2500)
    total_new += vn_new
    
    # 3. Target Dieutri.vn Clinical Knowledge Base
    d_tot, d_new = harvest_dieutri_articles(con, run_id)
    total_new += d_new
    
    con.close()
    print(f"\n=== Harvesting complete! Added {total_new:,} brand-new records to library database ===", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
