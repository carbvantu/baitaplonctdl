#!/usr/bin/env python3
"""VCU Continuous Multi-Round Harvester:
Automates iterative execution of Round 3, 4, 5... until all available data
across domestic journals, clinical textbook chapters, NIH topics, and top international journals
is exhaustively harvested (thu thập hết dữ liệu không bỏ sót).

Features:
- State management via library_data/harvester_state.json
- Robust OAI-PMH harvesting with XML control character sanitization
- Sitemap traversal for Dieutri.vn until all clinical URLs are harvested
- Complete pagination across top journals and Vietnamese hospitals on PubMed
- Automatic synchronization (SQLite -> CSV/JSONL + VACUUM)
- Automatic report generation & packaging into split parts (< 45 MB)
- Automatic Git commit & push to main branch with credential sanitization
"""
from __future__ import annotations
import csv, glob, hashlib, html, http.client, json, os, re, sqlite3, ssl, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
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
STATE_FILE = DATA_DIR / "harvester_state.json"
REPO_URL = "https://github.com/carbvantu/baitaplonctdl.git"
TOKEN_FILE = HERE / ".git_token"
PAT = os.environ.get("GITHUB_PAT", "")
if not PAT and TOKEN_FILE.exists():
    PAT = TOKEN_FILE.read_text(encoding="utf-8").strip()
AUTH_URL = f"https://carbvantu:{PAT}@github.com/carbvantu/baitaplonctdl.git" if PAT else REPO_URL

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "current_round": 3,
        "vmj_max_records": 3000,
        "tcncyh_completed": False,
        "yhcd_completed": False,
        "dieutri_target_per_round": 1500,
        "pubmed_top_journals_retstart": 3000,
        "history": []
    }

def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

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
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
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
    cur = con.execute("SELECT pmid, abstract FROM records WHERE pmid=?", (rec["pmid"],))
    row = cur.fetchone()
    existed = row is not None
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
    if any(k in text for k in ["surg", "operat", "resect", "laparoscop", "graft", "transplant", "phẫu thuật", "mổ", "ngoại khoa", "cắt"]):
        specs.append("Surgery")
    if any(k in text for k in ["immune", "immunol", "antibod", "t cell", "autoimmun", "vaccin", "checkpoint", "miễn dịch", "kháng thể", "dị ứng"]):
        specs.append("Immunology")
    if any(k in text for k in ["gene", "genom", "mutation", "sequencing", "dna", "rna", "crispr", "heredit", "di truyền", "gen", "đột biến"]):
        specs.append("Genetics")
    if any(k in text for k in ["drug", "pharmacol", "dose", "pharmacokinet", "toxic", "thuốc", "dược", "liều", "đông y", "dược liệu", "cây thuốc"]):
        specs.append("Pharmacology")
    if any(k in text for k in ["patholog", "histolog", "biopsy", "morpholog", "cytolog", "bệnh học", "sinh thiết", "sinh lý bệnh", "mô bệnh"]):
        specs.append("Pathology")
    if any(k in text for k in ["biomarker", "assay", "diagnostic", "laboratory", "pcr", "elisa", "sensitivity", "xét nghiệm", "chỉ số", "hóa sinh"]):
        specs.append("Laboratory diagnostics")
    if any(k in text for k in ["computational", "bioinformatic", "machine learning", "algorithm", "deep learning", "neural network", "ai", "tính toán"]):
        specs.append("Computational biology")
    if any(k in text for k in ["anatom", "morpholog", "cadaver", "dissect", "giải phẫu", "cấu trúc", "xương"]):
        specs.append("Anatomy")
    if not specs:
        specs.append("Internal medicine")
    return specs

def harvest_oai_journal(con, journal_name: str, base_oai_url: str, id_prefix: str, run_id: str, max_records: int = 3000):
    print(f"\n[OAI-PMH] Harvesting journal: {journal_name} (Max: {max_records:,})...", flush=True)
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    
    url = f"{base_oai_url}?verb=ListRecords&metadataPrefix=oai_dc"
    harvested = 0
    new_c = 0
    batch_num = 1
    completed_all = False
    
    while url and harvested < max_records:
        try:
            raw = request_url(url, min_delay=0.36, user_agent=user_agent)
            clean_raw = re.sub(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]', b' ', raw)
            root = ET.fromstring(clean_raw)
            recs = root.findall(".//{http://www.openarchives.org/OAI/2.0/}record")
            if not recs:
                completed_all = True
                break
                
            for r in recs:
                header = r.find("{http://www.openarchives.org/OAI/2.0/}header")
                if header is not None and header.attrib.get("status") == "deleted":
                    continue
                metadata = r.find("{http://www.openarchives.org/OAI/2.0/}metadata")
                if metadata is None:
                    continue
                    
                titles = [t.text.strip() for t in metadata.findall(".//{http://purl.org/dc/elements/1.1/}title") if t.text and t.text.strip()]
                title = " / ".join(titles) if titles else "Không có tiêu đề"
                
                authors = [a.text.strip() for a in metadata.findall(".//{http://purl.org/dc/elements/1.1/}creator") if a.text and a.text.strip()]
                descriptions = [d.text.strip() for d in metadata.findall(".//{http://purl.org/dc/elements/1.1/}description") if d.text and d.text.strip()]
                abstract = "\n\n".join(descriptions)
                abstract = html.unescape(abstract).replace("&nbsp;", " ")
                
                subjects = [s.text.strip() for s in metadata.findall(".//{http://purl.org/dc/elements/1.1/}subject") if s.text and s.text.strip()]
                dates = [d.text.strip() for d in metadata.findall(".//{http://purl.org/dc/elements/1.1/}date") if d.text and d.text.strip()]
                pubdate = dates[0] if dates else "2024"
                
                identifiers = [i.text.strip() for i in metadata.findall(".//{http://purl.org/dc/elements/1.1/}identifier") if i.text and i.text.strip()]
                doi = ""
                web_url = ""
                for ident in identifiers:
                    if ident.startswith("10."): doi = ident
                    elif ident.startswith("http"): web_url = ident
                        
                oai_id = header.find("{http://www.openarchives.org/OAI/2.0/}identifier")
                raw_id = oai_id.text.strip() if oai_id is not None and oai_id.text else (doi or web_url or title)
                clean_id = f"{id_prefix}-" + hashlib.md5(raw_id.encode()).hexdigest()[:12]
                
                specs = determine_specialty(title, abstract, subjects)
                rec = {
                    "pmid": clean_id, "pmcid": "", "doi": doi or web_url, "title": title, "authors": authors,
                    "journal": journal_name, "publication_date": pubdate, "language": ["Vietnamese", "English"],
                    "publication_types": ["Peer-Reviewed Journal Article"], "mesh_terms": subjects, "keywords": subjects,
                    "abstract": abstract, "pubmed_url": web_url, "source": journal_name, "fetched_at": now_iso()
                }
                status = upsert_record(con, rec, run_id)
                for s in specs:
                    con.execute("INSERT INTO record_specialties VALUES (?,?,?,?) ON CONFLICT(pmid,specialty) DO UPDATE SET last_seen_run=excluded.last_seen_run", (clean_id, s, run_id, run_id))
                harvested += 1
                if status == "new": new_c += 1
                if harvested >= max_records:
                    break
                    
            con.commit()
            print(f"  Batch {batch_num}: Processed {harvested} articles from {journal_name} (New: {new_c})...", flush=True)
            batch_num += 1
            
            token = root.find(".//{http://www.openarchives.org/OAI/2.0/}resumptionToken")
            if token is not None and token.text and token.text.strip():
                url = f"{base_oai_url}?verb=ListRecords&resumptionToken={token.text.strip()}"
            else:
                completed_all = True
                break
        except Exception as e:
            print(f"  Warning on {journal_name}: {e}", file=sys.stderr)
            break
            
    print(f"  Completed {journal_name}: Total {harvested} articles processed (New: {new_c}, All exhausted: {completed_all})", flush=True)
    return harvested, new_c, completed_all

def harvest_dieutri_round(con, run_id: str, target_count: int = 1500):
    print(f"\n[Dieutri.vn] Crawling clinical articles from sitemap (Target: {target_count:,})...", flush=True)
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
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
        "https://www.dieutri.vn/caythuocdongy/",
        "https://www.dieutri.vn/sinhlynguoi/",
        "https://www.dieutri.vn/hscctt/",
        "https://www.dieutri.vn/bgsanphukhoa/",
        "https://www.dieutri.vn/bgnhi/",
        "https://www.dieutri.vn/ngoaikhoa/",
        "https://www.dieutri.vn/mat/",
        "https://www.dieutri.vn/taimuihong/",
        "https://www.dieutri.vn/dalieu/",
        "https://www.dieutri.vn/phacdo"
    ]
    
    try:
        sitemap_raw = request_url("https://www.dieutri.vn/sitemap.xml", min_delay=0.4, user_agent=user_agent).decode("utf-8", errors="ignore")
        all_urls = re.findall(r'<loc>(https?://www\.dieutri\.vn/[^<]+)</loc>', sitemap_raw)
        target_urls = [u for u in all_urls if any(u.startswith(p) for p in priority_prefixes)]
        print(f"  Discovered {len(target_urls):,} candidate clinical URLs.", flush=True)
        
        harvested = 0
        new_c = 0
        for art_url in target_urls:
            if harvested >= target_count:
                break
            doc_id = "DIEUTRI-" + hashlib.md5(art_url.encode()).hexdigest()[:12]
            
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
                    "abstract": full_content,
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
                    print(f"    Progress: {harvested}/{target_count} Dieutri.vn articles harvested (New: {new_c})...", flush=True)
            except Exception:
                continue
                
        con.commit()
        print(f"  Dieutri.vn round finished: {harvested} articles (New: {new_c})", flush=True)
        return harvested, new_c
    except Exception as e:
        print(f"  Dieutri.vn crawler error: {e}", file=sys.stderr)
        return 0, 0

def harvest_nih_round(con, run_id: str, round_num: int = 3):
    print(f"\n[NIH / MedlinePlus Round {round_num}] Harvesting clinical topics...", flush=True)
    terms = [
        "cardiac arrest", "coronary artery disease", "atherosclerosis", "aortic aneurysm",
        "deep vein thrombosis", "pulmonary embolism", "chronic obstructive pulmonary disease",
        "idiopathic pulmonary fibrosis", "acute respiratory distress syndrome", "pneumothorax",
        "gastroesophageal reflux disease", "peptic ulcer", "cirrhosis", "cholecystitis",
        "pancreatic cancer", "colorectal cancer", "gastric cancer", "esophageal cancer",
        "cervical cancer", "ovarian cancer", "uterine cancer", "prostate cancer", "bladder cancer",
        "renal cell carcinoma", "melanoma", "basal cell carcinoma", "squamous cell carcinoma",
        "anemia", "sickle cell disease", "thalassemia", "hemophilia", "thrombocytopenia",
        "myeloma", "myelodysplastic syndromes", "bone marrow transplantation", "immunodeficiency",
        "hiv aids", "tuberculosis", "malaria", "dengue fever", "septic shock", "meningitis",
        "encephalitis", "stroke rehabilitation", "epilepsy management", "concussion", "traumatic brain injury"
    ]
    harvested = 0
    new_c = 0
    seen_urls = set()
    for term in terms:
        q_term = urllib.parse.quote_plus(term)
        url = f"https://wsearch.nlm.nih.gov/ws/query?db=healthTopics&term={q_term}&retmax=40"
        try:
            raw = request_url(url, min_delay=0.36, user_agent="VCUBiomedicalLibrary/1.0")
            root = ET.fromstring(raw)
            for doc in root.findall(".//document"):
                doc_url = doc.attrib.get("url", "")
                if not doc_url or doc_url in seen_urls:
                    continue
                seen_urls.add(doc_url)
                
                title_elem = doc.find(".//content[@name='title']")
                title_html = title_elem.text if title_elem is not None and title_elem.text else ""
                title = html.unescape(re.sub(r'<[^>]+>', '', title_html)).strip()
                
                summary_elem = doc.find(".//content[@name='FullSummary']")
                summary_html = summary_elem.text if summary_elem is not None and summary_elem.text else ""
                summary = html.unescape(re.sub(r'<[^>]+>', ' ', summary_html)).strip()
                
                if not title or len(summary) < 100:
                    continue
                    
                mesh_terms = [html.unescape(re.sub(r'<[^>]+>', '', c.text)).strip() for c in doc.findall(".//content[@name='mesh']") if c.text]
                group_names = [html.unescape(re.sub(r'<[^>]+>', '', c.text)).strip() for c in doc.findall(".//content[@name='groupName']") if c.text]
                alt_titles = [html.unescape(re.sub(r'<[^>]+>', '', c.text)).strip() for c in doc.findall(".//content[@name='altTitle']") if c.text]
                
                doc_id = "NIH-" + hashlib.md5(doc_url.encode()).hexdigest()[:12]
                specs = determine_specialty(title, summary, mesh_terms + group_names)
                
                rec = {
                    "pmid": doc_id, "pmcid": "", "doi": doc_url, "title": title,
                    "authors": ["National Institutes of Health (NIH) / National Library of Medicine (NLM)"],
                    "journal": "NIH MedlinePlus Clinical Health Topics",
                    "publication_date": "2024-2026", "language": ["English"],
                    "publication_types": ["Clinical Practice Guideline", "Government Publication", "Patient Education Handout"],
                    "mesh_terms": mesh_terms, "keywords": list(set(group_names + alt_titles)),
                    "abstract": summary, "pubmed_url": doc_url, "source": "NIH MedlinePlus", "fetched_at": now_iso()
                }
                status = upsert_record(con, rec, run_id)
                for s in specs:
                    con.execute("INSERT INTO record_specialties VALUES (?,?,?,?) ON CONFLICT(pmid,specialty) DO UPDATE SET last_seen_run=excluded.last_seen_run", (doc_id, s, run_id, run_id))
                harvested += 1
                if status == "new": new_c += 1
        except Exception as e:
            continue
    con.commit()
    print(f"  NIH MedlinePlus round finished: {harvested} topics processed (New: {new_c})", flush=True)
    return harvested, new_c

def harvest_pubmed_batch(con, source_label: str, query_term: str, run_id: str, max_items: int = 500, retstart: int = 3000):
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
            if rec: recs.append(rec)
            
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

def execute_round(round_num: int):
    print(f"\n{'='*20} STARTING ROUND {round_num} {'='*20}", flush=True)
    state = load_state()
    con = sqlite3.connect(DB_PATH)
    run_id = datetime.now(timezone.utc).strftime(f"vcu_round{round_num}_%Y%m%dT%H%M%SZ")
    total_new = 0
    
    # 1. TCNCYH (Hanoi Medical University)
    if not state.get("tcncyh_completed", False):
        tot, nc, done = harvest_oai_journal(con, "Tạp chí Nghiên cứu Y học", "https://tapchinghiencuuyhoc.vn/index.php/tcncyh/oai", "TCNCYH", run_id, max_records=2000)
        total_new += nc
        if done or nc == 0:
            state["tcncyh_completed"] = True
            print("  ==> Tạp chí Nghiên cứu Y học completely exhausted and collected!", flush=True)
            
    # 2. YHCD (Journal of Community Medicine)
    if not state.get("yhcd_completed", False):
        tot, nc, done = harvest_oai_journal(con, "Tạp chí Y học Cộng đồng", "https://tapchiyhcd.vn/index.php/yhcd/oai", "YHCD", run_id, max_records=6000)
        total_new += nc
        if done:
            state["yhcd_completed"] = True
            print("  ==> Tạp chí Y học Cộng đồng completely exhausted and collected!", flush=True)
            
    # 3. VMJ (Vietnam Medical Journal)
    if not state.get("vmj_completed", False):
        vmj_max = 9500 + (round_num - 4) * 4500
        tot, nc, done = harvest_oai_journal(con, "Tạp chí Y học Việt Nam", "https://tapchiyhocvietnam.vn/index.php/vmj/oai", "VMJ", run_id, max_records=vmj_max)
        total_new += nc
        state["vmj_max_records"] = vmj_max
        if done:
            state["vmj_completed"] = True
            print("  ==> Tạp chí Y học Việt Nam completely exhausted and collected!", flush=True)
        
    # 4. Dieutri.vn
    dt_target = state.get("dieutri_target_per_round", 1500)
    tot, nc = harvest_dieutri_round(con, run_id, target_count=dt_target)
    total_new += nc
    
    # 5. NIH MedlinePlus
    tot, nc = harvest_nih_round(con, run_id, round_num=round_num)
    total_new += nc
    
    # 6. Top International Journals & Specialty Medical Canon (Super Massive Harvest)
    p_offset = state.get("pubmed_top_journals_retstart", 6000)
    top_journals = [
        # Established Top Journals (Batch of 1,000 each)
        (f"The New England Journal of Medicine (NEJM) - Round {round_num}", '"N Engl J Med"[Journal]', 1000, p_offset),
        (f"The Lancet - Round {round_num}", '"Lancet"[Journal]', 1000, p_offset),
        (f"JAMA - Round {round_num}", '"JAMA"[Journal]', 1000, p_offset),
        (f"The BMJ - Round {round_num}", '"BMJ"[Journal]', 1000, p_offset),
        (f"Annals of Internal Medicine - Round {round_num}", '"Ann Intern Med"[Journal]', 1000, p_offset),
        (f"JAMA Internal Medicine - Round {round_num}", '"JAMA Intern Med"[Journal]', 500, p_offset),
        (f"Nature Medicine - Round {round_num}", '"Nat Med"[Journal]', 1000, 1500 if round_num >= 8 else 500),
        (f"The Lancet Oncology - Round {round_num}", '"Lancet Oncol"[Journal]', 1000, 1500 if round_num >= 8 else 500),

        # World-Leading Specialty Medical Journals (Round 7 journals continued)
        (f"Circulation (Cardiology #1) - Round {round_num}", '"Circulation"[Journal]', 1000, 1000 if round_num >= 8 else 0),
        (f"JACC (Clinical Cardiology) - Round {round_num}", '"J Am Coll Cardiol"[Journal]', 1000, 1000 if round_num >= 8 else 0),
        (f"Journal of Clinical Oncology (JCO) - Round {round_num}", '"J Clin Oncol"[Journal]', 1000, 1000 if round_num >= 8 else 0),
        (f"Blood (Hematology & Oncology) - Round {round_num}", '"Blood"[Journal]', 1000, 1000 if round_num >= 8 else 0),
        (f"Gastroenterology (GI & Liver) - Round {round_num}", '"Gastroenterology"[Journal]', 1000, 1000 if round_num >= 8 else 0),
        (f"Cell (Biomedical & Molecular Science) - Round {round_num}", '"Cell"[Journal]', 1000, 1000 if round_num >= 8 else 0),
        (f"The Lancet Infectious Diseases - Round {round_num}", '"Lancet Infect Dis"[Journal]', 1000, 800 if round_num >= 8 else 0),
        (f"The Lancet Neurology - Round {round_num}", '"Lancet Neurol"[Journal]', 1000, 800 if round_num >= 8 else 0),
        (f"Science Translational Medicine - Round {round_num}", '"Sci Transl Med"[Journal]', 1000, 800 if round_num >= 8 else 0),
        (f"The Lancet Respiratory Medicine - Round {round_num}", '"Lancet Respir Med"[Journal]', 1000, 800 if round_num >= 8 else 0),

        # New Tier-1 Medical Journals for Round 8
        (f"European Heart Journal - Round {round_num}", '"Eur Heart J"[Journal]', 1000, 0),
        (f"Stroke (AHA) - Round {round_num}", '"Stroke"[Journal]', 1000, 0),
        (f"Diabetes Care (ADA) - Round {round_num}", '"Diabetes Care"[Journal]', 1000, 0),
        (f"Gut (Gastroenterology) - Round {round_num}", '"Gut"[Journal]', 1000, 0),
        (f"Nature Biotechnology - Round {round_num}", '"Nat Biotechnol"[Journal]', 1000, 0),
        (f"Nature Genetics - Round {round_num}", '"Nat Genet"[Journal]', 1000, 0),
        (f"Immunity (Cell Press) - Round {round_num}", '"Immunity"[Journal]', 800, 0),
        (f"Nature Immunology - Round {round_num}", '"Nat Immunol"[Journal]', 800, 0),
        (f"The Lancet Psychiatry - Round {round_num}", '"Lancet Psychiatry"[Journal]', 800, 0),
    ]
    for label, q, limit, offset in top_journals:
        tot, nc = harvest_pubmed_batch(con, label, q, run_id, max_items=limit, retstart=offset)
        total_new += nc
    state["pubmed_top_journals_retstart"] = p_offset + 1000

    # 7. Ten Clinical Specialties High-Impact Queries (Offset 500, Batch of 500 each)
    sp_offset = 500 if round_num >= 8 else 0
    specialty_batch = [
        ("Surgery / Ngoại khoa (High-Impact)", '(surgery[MeSH] OR "surgical procedures"[Title/Abstract]) AND ("randomized controlled trial"[pt] OR "systematic review"[pt]) AND 2020:2027[pdat]', 500, sp_offset),
        ("Cancer / Ung thư lâm sàng (High-Impact)", '(neoplasms[MeSH] OR "cancer immunotherapy"[Title/Abstract]) AND ("clinical trial"[pt] OR "systematic review"[pt]) AND 2020:2027[pdat]', 500, sp_offset),
        ("Genetics / Di truyền học y khoa (High-Impact)", '(genomics[MeSH] OR "gene therapy"[Title/Abstract] OR "whole genome sequencing"[Title/Abstract]) AND 2020:2027[pdat]', 500, sp_offset),
        ("Pharmacology / Dược lý lâm sàng (High-Impact)", '(pharmacovigilance[Title/Abstract] OR "drug safety"[Title/Abstract] OR "adverse drug reaction"[MeSH]) AND 2020:2027[pdat]', 500, sp_offset),
        ("Immunology / Miễn dịch học (High-Impact)", '(immunotherapy[MeSH] OR "CAR-T"[Title/Abstract] OR "monoclonal antibody"[Title/Abstract]) AND 2020:2027[pdat]', 500, sp_offset),
        ("Laboratory diagnostics / Xét nghiệm (High-Impact)", '(biomarkers[MeSH] OR "diagnostic accuracy"[Title/Abstract] OR "liquid biopsy"[Title/Abstract]) AND 2020:2027[pdat]', 500, sp_offset),
        ("Internal medicine / Nội khoa (High-Impact)", '("practice guideline"[pt] OR "clinical decision support"[Title/Abstract] OR "chronic disease"[Title/Abstract]) AND 2020:2027[pdat]', 500, sp_offset),
        ("Computational biology / AI Y khoa (High-Impact)", '("deep learning"[Title/Abstract] OR "artificial intelligence"[MeSH] OR "machine learning"[Title/Abstract]) AND (diagnosis[Title/Abstract] OR medicine[Title/Abstract]) AND 2020:2027[pdat]', 500, sp_offset),
        ("Pathology / Bệnh học (High-Impact)", '("digital pathology"[Title/Abstract] OR "molecular pathology"[Title/Abstract] OR histopathology[MeSH]) AND 2020:2027[pdat]', 500, sp_offset),
        ("Anatomy / Giải phẫu học (High-Impact)", '("surgical anatomy"[Title/Abstract] OR "3D reconstruction"[Title/Abstract] OR "organ transplantation"[MeSH]) AND 2020:2027[pdat]', 500, sp_offset),
    ]
    for label, q, limit, offset in specialty_batch:
        tot, nc = harvest_pubmed_batch(con, label, q, run_id, max_items=limit, retstart=offset)
        total_new += nc

    # 8. Vietnamese Medical Institutions on PubMed (Extended)
    vn_offset = (round_num - 2) * 250
    vn_queries = [
        (f"Hanoi Medical University Studies (Round {round_num})", '("Hanoi Medical University"[Affiliation])', 300, 800 + vn_offset),
        (f"Cho Ray & Bach Mai Hospitals (Round {round_num})", '("Bach Mai Hospital"[Affiliation] OR "Cho Ray Hospital"[Affiliation])', 300, 600 + vn_offset),
        (f"University of Medicine and Pharmacy at Ho Chi Minh City (Round {round_num})", '("University of Medicine and Pharmacy at Ho Chi Minh"[Affiliation])', 300, 650 + vn_offset),
        (f"Vietnam National Children's Hospital & K Hospital (Round {round_num})", '("National Children\'s Hospital"[Affiliation] OR "National Cancer Hospital"[Affiliation])', 300, 300 + vn_offset),
        (f"Military Central Hospital 108 (Round {round_num})", '("108 Military Central Hospital"[Affiliation] OR "Military Central Hospital 108"[Affiliation])', 300, 300 if round_num >= 8 else 0),
        (f"Pasteur Institute & NIHE Vietnam (Round {round_num})", '("Pasteur Institute"[Affiliation] AND Vietnam[Affiliation]) OR ("National Institute of Hygiene and Epidemiology"[Affiliation])', 300, 300 if round_num >= 8 else 0),
    ]
    for label, q, limit, offset in vn_queries:
        tot, nc = harvest_pubmed_batch(con, label, q, run_id, max_items=limit, retstart=offset)
        total_new += nc
        
    con.close()
    print(f"\n=== Round {round_num} Harvest Completed! New records added: {total_new:,} ===", flush=True)
    
    # Post-processing: Sync to CSV & JSONL, VACUUM, Update reports, Pack, Commit & Push
    print(f"\n--- Running Post-Processing for Round {round_num} ---", flush=True)
    subprocess.run([sys.executable, str(HERE / "sync_library_data.py")], check=True)
    subprocess.run([sys.executable, str(HERE / "reports" / "generate_report.py")], check=True)
    if (HERE / "scratch" / "update_specialty_csv.py").exists():
        subprocess.run([sys.executable, str(HERE / "scratch" / "update_specialty_csv.py")], check=True)
    subprocess.run([sys.executable, str(HERE / "pack_library.py")], check=True)
    
    # Git add, commit, push
    cur_count = sqlite3.connect(DB_PATH).execute("SELECT COUNT(*) FROM records").fetchone()[0]
    msg = f"feat: complete round {round_num} exhaustive harvest across medical journals and portals ({cur_count:,} records)"
    print(f"Committing to git: {msg}...", flush=True)
    subprocess.run(["git", "add", "."], cwd=str(HERE), check=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=str(HERE), check=False)
    
    print(f"Pushing to GitHub origin/main...", flush=True)
    subprocess.run(["git", "remote", "set-url", "origin", AUTH_URL], cwd=str(HERE), check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=str(HERE), check=True)
    subprocess.run(["git", "remote", "set-url", "origin", REPO_URL], cwd=str(HERE), check=True)
    print(f"Git push succeeded and credentials sanitized!", flush=True)
    
    state["current_round"] = round_num + 1
    state["history"].append({"round": round_num, "new_records": total_new, "total_records": cur_count, "timestamp": now_iso()})
    save_state(state)
    return total_new, cur_count

def main():
    state = load_state()
    start_round = state.get("current_round", 3)
    print(f"=== Starting Continuous Harvester from Round {start_round} ===", flush=True)
    execute_round(start_round)
    print(f"\nAll operations for Round {start_round} completed successfully!", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
