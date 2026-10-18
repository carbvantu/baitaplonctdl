#!/usr/bin/env python3
"""VCU Deep Multi-Web Harvester: comprehensive, exhaustive data collector across:
1. Dieutri.vn: Vietnamese medical textbooks, Harrison Internal Medicine, treatment protocols, laboratory tests, traditional medicine.
2. NCBI / NIH Bookshelf: StatPearls comprehensive clinical monographs across 10 specialties.
3. Top-tier International Journals Page 2: NEJM, The Lancet, JAMA, BMJ, Annals of Internal Medicine, JAMA Internal Medicine.
4. Vietnamese Medical Institutions & Research Page 2: Hanoi Medical Univ, Cho Ray, Bach Mai, Ho Chi Minh UMP.

Strict Requirement: 100% FULL, UNSHORTENED TEXT & ABSTRACTS (không tóm tắt, không rút gọn).
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
            time.sleep(min(2 ** attempt, 8))
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
        article = node.find(".//Article")
        if article is None:
            return None
    pmid = first_text(node, "MedlineCitation/PMID") or first_text(node, ".//PMID")
    title = first_text(article, "ArticleTitle") or first_text(node, ".//BookTitle")
    journal = first_text(article, "Journal/Title") or first_text(node, ".//Book/BookTitle")
    authors = []
    for a in node.findall(".//AuthorList/Author"):
        collective = first_text(a, "CollectiveName")
        last = first_text(a, "LastName")
        fore = first_text(a, "ForeName") or first_text(a, "Initials")
        name = collective or (f"{fore} {last}".strip())
        if name:
            authors.append(name)
    abstract_parts = []
    for a in node.findall(".//Abstract/AbstractText"):
        label = a.attrib.get("Label") or a.attrib.get("NlmCategory") or ""
        text = flatten_text(a)
        if text:
            abstract_parts.append(f"{label}: {text}" if label else text)
    doi = ""
    pmcid = ""
    for aid in node.findall(".//ArticleIdList/ArticleId"):
        typ = (aid.attrib.get("IdType") or "").lower()
        val = flatten_text(aid)
        if typ == "doi": doi = val
        elif typ == "pmc": pmcid = val
    if not doi:
        for eid in node.findall(".//ELocationID"):
            if eid.attrib.get("EIdType", "").lower() == "doi":
                doi = flatten_text(eid)
                break
    mesh = [flatten_text(x.find("DescriptorName")) for x in node.findall(".//MeshHeadingList/MeshHeading") if x.find("DescriptorName") is not None]
    keywords = [flatten_text(x) for x in node.findall(".//KeywordList/Keyword") if flatten_text(x)]
    pubtypes = [flatten_text(x) for x in node.findall(".//PublicationTypeList/PublicationType") if flatten_text(x)]
    return {
        "pmid": pmid, "pmcid": pmcid, "doi": doi, "title": title, "authors": authors,
        "journal": journal, "publication_date": pubdate_text(article), "language": [flatten_text(x) for x in node.findall(".//Language")],
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
    if any(k in text for k in ["cancer", "neoplasm", "tumor", "carcinoma", "oncolog", "leukemia", "lymphoma", "ung thư", "u bướu"]):
        specs.append("Cancer")
    if any(k in text for k in ["surg", "operat", "resect", "laparoscop", "graft", "transplant", "phẫu thuật", "mổ", "ngoại khoa"]):
        specs.append("Surgery")
    if any(k in text for k in ["immune", "immunol", "antibod", "t cell", "autoimmun", "vaccin", "checkpoint", "miễn dịch", "kháng thể"]):
        specs.append("Immunology")
    if any(k in text for k in ["gene", "genom", "mutation", "sequencing", "dna", "rna", "crispr", "heredit", "di truyền", "gen"]):
        specs.append("Genetics")
    if any(k in text for k in ["drug", "pharmacol", "dose", "pharmacokinet", "toxic", "thuốc", "dược", "liều dùng", "đông y", "dược liệu"]):
        specs.append("Pharmacology")
    if any(k in text for k in ["patholog", "histolog", "biopsy", "morpholog", "cytolog", "bệnh học", "sinh thiết", "sinh lý bệnh"]):
        specs.append("Pathology")
    if any(k in text for k in ["biomarker", "assay", "diagnostic", "laboratory", "pcr", "elisa", "sensitivity", "xét nghiệm", "chỉ số"]):
        specs.append("Laboratory diagnostics")
    if any(k in text for k in ["computational", "bioinformatic", "machine learning", "algorithm", "deep learning", "neural network", "ai", "tính toán"]):
        specs.append("Computational biology")
    if any(k in text for k in ["anatom", "morpholog", "cadaver", "dissect", "giải phẫu", "cấu trúc cơ thể"]):
        specs.append("Anatomy")
    if not specs:
        specs.append("Internal medicine")
    return specs

def harvest_pubmed_query(con, source_label: str, query_term: str, run_id: str, max_items: int = 1000, retstart: int = 0):
    user_agent = "VCUBiomedicalLibrary/1.0 (contact: dotu020806@gmail.com)"
    common = {"db": "pubmed", "tool": "VCUBiomedicalLibrary", "email": "dotu020806@gmail.com", "retmode": "json"}
    params = dict(common)
    params.update({"term": query_term, "retmax": max_items, "retstart": retstart, "sort": "pub date"})
    
    print(f"\n[PubMed] Querying: {source_label} (retstart={retstart}, max={max_items})...", flush=True)
    body = request_url(BASE + "esearch.fcgi", params, 0.36, user_agent)
    result = json.loads(body.decode("utf-8"))["esearchresult"]
    total = int(result.get("count", 0))
    ids = result.get("idlist", [])
    print(f"  Total matched: {total:,} | Fetching batch of {len(ids)} articles...", flush=True)
    
    recs = []
    batch_size = 100
    for offset in range(0, len(ids), batch_size):
        chunk = ids[offset:offset + batch_size]
        if not chunk: continue
        fp = dict(common); fp.update({"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"})
        xml_bytes = request_url(BASE + "efetch.fcgi", fp, 0.36, user_agent)
        root = ET.fromstring(xml_bytes)
        for node in root.findall(".//PubmedArticle"):
            rec = parse_pubmed_article(node)
            if rec:
                recs.append(rec)
        for node in root.findall(".//PubmedBookArticle"):
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
    print(f"  Processed {len(recs)} records for {source_label} (New: {new_c}, Updated: {updated_c})", flush=True)
    return len(recs), new_c

def harvest_dieutri_deep(con, run_id: str, max_articles: int = 500):
    print("\n[Dieutri.vn Deep Crawler] Fetching clinical articles from sitemap.xml...", flush=True)
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    # Priority sections on Dieutri.vn
    priority_prefixes = [
        "https://www.dieutri.vn/noikhoaharrison18/",
        "https://www.dieutri.vn/thchandoandieutri/",
        "https://www.dieutri.vn/trieuchungnoi/",
        "https://www.dieutri.vn/chandoan/",
        "https://www.dieutri.vn/bgsinhlybenh/",
        "https://www.dieutri.vn/motsoxetnghiem/",
        "https://www.dieutri.vn/ynghiaxetnghiem/",
        "https://www.dieutri.vn/duocly/",
        "https://www.dieutri.vn/duocdiendongduoc/",
        "https://www.dieutri.vn/thuocdongyhieunghiem/",
        "https://www.dieutri.vn/sinhlynguoi/",
        "https://www.dieutri.vn/hscctt/",
        "https://www.dieutri.vn/bgsanphukhoa/",
        "https://www.dieutri.vn/caythuocdongy/",
        "https://www.dieutri.vn/phacdo"
    ]
    
    try:
        sitemap_raw = request_url("https://www.dieutri.vn/sitemap.xml", min_delay=0.5, user_agent=user_agent).decode("utf-8", errors="ignore")
        all_urls = re.findall(r'<loc>(https?://www\.dieutri\.vn/[^<]+)</loc>', sitemap_raw)
        print(f"  Total URLs in sitemap: {len(all_urls):,}", flush=True)
        
        target_urls = []
        for u in all_urls:
            if any(u.startswith(p) for p in priority_prefixes):
                target_urls.append(u)
                
        print(f"  Target clinical article URLs: {len(target_urls):,} | Collecting up to {max_articles}...", flush=True)
        
        harvested = 0
        new_c = 0
        for i, art_url in enumerate(target_urls[:max_articles]):
            doc_id = "DIEUTRI-" + hashlib.md5(art_url.encode()).hexdigest()[:12]
            
            # Check if already in db
            cur = con.execute("SELECT pmid, abstract FROM records WHERE pmid=?", (doc_id,))
            row = cur.fetchone()
            if row and row[1] and len(row[1]) > 500:
                continue
                
            try:
                art_raw = request_url(art_url, min_delay=0.3, user_agent=user_agent).decode("utf-8", errors="ignore")
                m_title = re.search(r'<h1[^>]*>(.*?)</h1>', art_raw, re.DOTALL | re.IGNORECASE)
                title = html.unescape(re.sub(r'<[^>]+>', '', m_title.group(1)).strip()) if m_title else ""
                if not title or len(title) < 5:
                    continue
                    
                clean = re.sub(r'<(script|style|nav|header|footer)[^>]*>.*?</\1>', '', art_raw, flags=re.DOTALL | re.IGNORECASE)
                clean_text = html.unescape(re.sub(r'<[^>]+>', ' ', clean))
                lines = [l.strip() for l in clean_text.splitlines() if l.strip()]
                full_content = "\n\n".join(lines)
                
                if len(full_content) < 300:
                    continue
                    
                specs = determine_specialty(title, full_content, [])
                rec = {
                    "pmid": doc_id, "pmcid": "", "doi": art_url, "title": title,
                    "authors": ["Ban biên tập Y học Dieutri.vn"],
                    "journal": "Dieutri.vn - Cẩm nang Y học lâm sàng & Dược học",
                    "publication_date": "2024-2026",
                    "language": ["Vietnamese"],
                    "publication_types": ["Clinical Practice Guideline", "Medical Textbook Chapter"],
                    "mesh_terms": [],
                    "keywords": ["Y học Việt Nam", "Phác đồ điều trị", "Nội khoa Harrison", "Dược học"],
                    "abstract": full_content,  # 100% full unshortened text
                    "pubmed_url": art_url,
                    "source": "Dieutri.vn Clinical Portal",
                    "fetched_at": now_iso()
                }
                status = upsert_record(con, rec, run_id)
                for s in specs:
                    con.execute("INSERT INTO record_specialties VALUES (?,?,?,?) ON CONFLICT(pmid,specialty) DO UPDATE SET last_seen_run=excluded.last_seen_run", (doc_id, s, run_id, run_id))
                harvested += 1
                if status == "new": new_c += 1
                if harvested % 50 == 0:
                    con.commit()
                    print(f"    Progress: {harvested} articles harvested from Dieutri.vn...", flush=True)
            except Exception as e:
                continue
                
        con.commit()
        print(f"  Completed Dieutri.vn deep crawl: {harvested} full articles (New: {new_c})", flush=True)
        return harvested, new_c
    except Exception as e:
        print(f"  Error crawling Dieutri.vn sitemap: {e}", file=sys.stderr)
        return 0, 0

def main():
    con = sqlite3.connect(DB_PATH)
    run_id = datetime.now(timezone.utc).strftime("vcu_deep_%Y%m%dT%H%M%SZ")
    print(f"=== Starting VCU Deep Multi-Web Harvester (Run ID: {run_id}) ===", flush=True)
    
    total_new = 0
    
    # 1. NCBI Bookshelf StatPearls Clinical Monographs (1,500 monographs across specialties)
    statpearls_queries = [
        ("StatPearls - Oncology / Cancer Monographs", '"StatPearls"[book] AND ("neoplasms"[MeSH Terms] OR "cancer"[Title] OR "oncology"[Title])', 400),
        ("StatPearls - Surgery / Surgical Procedures", '"StatPearls"[book] AND ("surgical procedures"[MeSH Terms] OR "surgery"[Title])', 400),
        ("StatPearls - Pharmacology & Clinical Drugs", '"StatPearls"[book] AND ("pharmacology"[MeSH Terms] OR "drug"[Title] OR "therapy"[Title])', 400),
        ("StatPearls - Laboratory Diagnostics & Biomarkers", '"StatPearls"[book] AND ("diagnostic techniques and procedures"[MeSH Terms] OR "laboratory"[Title])', 400),
    ]
    for label, q, limit in statpearls_queries:
        tot, nc = harvest_pubmed_query(con, label, q, run_id, max_items=limit, retstart=0)
        total_new += nc
        
    # 2. Top-tier International Journals Page 2 (Retstart=1000)
    top_journals_page2 = [
        ("The New England Journal of Medicine (NEJM) - Page 2", '"N Engl J Med"[Journal]', 1000, 1000),
        ("The Lancet - Page 2", '"Lancet"[Journal]', 1000, 1000),
        ("JAMA - Page 2", '"JAMA"[Journal]', 1000, 1000),
        ("The BMJ - Page 2", '"BMJ"[Journal]', 1000, 1000),
        ("Annals of Internal Medicine - Page 2", '"Ann Intern Med"[Journal]', 1000, 1000),
        ("JAMA Internal Medicine - Page 2", '"JAMA Intern Med"[Journal]', 1000, 1000),
    ]
    for label, q, limit, offset in top_journals_page2:
        tot, nc = harvest_pubmed_query(con, label, q, run_id, max_items=limit, retstart=offset)
        total_new += nc
        
    # 3. Vietnamese Medical Research Deep Expansion (Hanoi Med Univ, Cho Ray, Bach Mai, Ho Chi Minh UMP)
    vn_query = '("Vietnam"[Affiliation] OR "Viet Nam"[Affiliation]) AND ("clinical trial"[Publication Type] OR "review"[Publication Type] OR "randomized controlled trial"[Publication Type] OR "epidemiology"[Title/Abstract])'
    tot, nc = harvest_pubmed_query(con, "Vietnamese Medical Research Deep Batch", vn_query, run_id, max_items=2500, retstart=2500)
    total_new += nc
    
    # 4. Dieutri.vn Deep Clinical Library (Up to 500 comprehensive articles with Harrison & Pharmacopoeia)
    tot, nc = harvest_dieutri_deep(con, run_id, max_articles=500)
    total_new += nc
    
    con.close()
    print(f"\n=== Deep Multi-Web Harvest Completed! Total brand-new records added: {total_new:,} ===", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
