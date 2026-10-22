#!/usr/bin/env python3
"""VCU Exhaustive Gap-Sweep & Cycle 5 Starter:
1. Sweeps through ALL 8 Eras from Era 1 (1990) to Era 8 (2027) from the beginning.
2. Checks database to ONLY fetch truly missing records (lưu ý không thu thập dữ liệu cũ, chỉ lấy dữ liệu bị bỏ sót).
3. Closes any gaps across all 21 top medical journals, 10 clinical specialties, and Vietnamese research.
4. Performs post-processing, database sync, report generation, < 45 MB packaging, and push to GitHub.
5. Advances to complete Cycle 4 and immediately starts the new Cycle 5 (offset 4,000) from 1990.
"""
from __future__ import annotations
import json, os, sqlite3, subprocess, sys, time
from datetime import datetime
from pathlib import Path

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

from vcu_continuous_rounds_harvester import (
    load_state, save_state, now_iso, harvest_pubmed_batch,
    harvest_oai_journal, harvest_dieutri_round, harvest_nih_round,
    execute_round
)

ERAS = [
    ("1990:1994", "Era 1 (1990 - 1994): Early 1990s Landmark Medical Canon"),
    ("1995:1999", "Era 2 (1995 - 1999): Late 1990s Evidence-Based Medicine & Trials"),
    ("2000:2004", "Era 3 (2000 - 2004): Genomic & Targeted Therapy Revolution"),
    ("2005:2009", "Era 4 (2005 - 2009): Multi-Center Trials & Clinical Guidelines"),
    ("2010:2014", "Era 5 (2010 - 2014): Immunotherapy & Molecular Medicine"),
    ("2015:2019", "Era 6 (2015 - 2019): Precision Medicine & Early AI"),
    ("2020:2024", "Era 7 (2020 - 2024): Pandemic Response, mRNA & Modern Multi-Omics"),
    ("2025:2027", "Era 8 (2025 - 2027): Frontier Clinical AI & Contemporary Trials"),
]

def git_commit_and_push(msg: str):
    print(f"\n[Git] Committing: {msg}...", flush=True)
    subprocess.run(["git", "add", "."], cwd=str(HERE), check=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=str(HERE), check=False)
    
    print(f"[Git] Pushing to GitHub origin/main...", flush=True)
    pushed = False
    for attempt in range(1, 5):
        try:
            subprocess.run(["git", "remote", "set-url", "origin", AUTH_URL], cwd=str(HERE), check=True)
            res = subprocess.run(["git", "push", "origin", "main"], cwd=str(HERE), check=False)
            if res.returncode == 0:
                pushed = True
                print(f"[Git] Push succeeded on attempt {attempt}!", flush=True)
                break
            print(f"[Git] Push attempt {attempt} failed, retrying in 5s...", flush=True)
            time.sleep(5)
        finally:
            subprocess.run(["git", "remote", "set-url", "origin", REPO_URL], cwd=str(HERE), check=True)
            print("[Git] Remote origin sanitized.", flush=True)
    if not pushed:
        print("[Git] Warning: Push could not complete after 4 attempts.", flush=True)

def run_post_processing():
    print(f"\n--- Running Full Post-Processing ---", flush=True)
    subprocess.run([sys.executable, str(HERE / "sync_library_data.py")], check=True)
    subprocess.run([sys.executable, str(HERE / "reports" / "generate_report.py")], check=True)
    if (HERE / "scratch" / "update_specialty_csv.py").exists():
        subprocess.run([sys.executable, str(HERE / "scratch" / "update_specialty_csv.py")], check=True)
    subprocess.run([sys.executable, str(HERE / "pack_library.py")], check=True)

def comprehensive_gap_sweep():
    print(f"\n{'='*70}", flush=True)
    print(f">>> BẮT ĐẦU QUÉT VÉT TOÀN DIỆN TỪ ĐẦU (1990 - 2027) ĐỂ TRÁNH BỎ SÓT <<<", flush=True)
    print(f">>> NGUYÊN TẮC: KHÔNG THU THẬP DỮ LIỆU CŨ, CHỈ LẤY DỮ LIỆU BỊ BỎ SÓT <<<", flush=True)
    print(f"{'='*70}\n", flush=True)

    con = sqlite3.connect(DB_PATH)
    run_id = f"sweep_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    total_swept_new = 0

    # 1. Domestic portals check
    print("\n--- Kiểm tra bổ sung nguồn dữ liệu trong nước & NIH MedlinePlus ---", flush=True)
    harvest_dieutri_round(con, run_id, target_count=500)
    harvest_nih_round(con, run_id, round_num=99)

    trial_filter = '("randomized controlled trial"[pt] OR "clinical trial"[pt] OR "systematic review"[pt] OR "practice guideline"[pt])'

    # 2. Iterate each era from 1990 to 2027
    for era_idx, (era_range, era_title) in enumerate(ERAS):
        print(f"\n{'*'*60}", flush=True)
        print(f"[*] Quét rà soát Kỷ nguyên {era_idx + 1}/8: {era_title}", flush=True)
        print(f"{'*'*60}", flush=True)

        # Offsets to verify: 0, 1000, 2000, 3000, 4000, 5000 (Cycles 1 to 6)
        for offset in [0, 1000, 2000, 3000, 4000, 5000]:
            top_journals = [
                (f"NEJM ({era_range})", f'"N Engl J Med"[Journal] AND {era_range}[pdat]', 1000, offset),
                (f"The Lancet ({era_range})", f'"Lancet"[Journal] AND {era_range}[pdat]', 1000, offset),
                (f"JAMA ({era_range})", f'"JAMA"[Journal] AND {era_range}[pdat]', 1000, offset),
                (f"The BMJ ({era_range})", f'"BMJ"[Journal] AND {era_range}[pdat]', 1000, offset),
                (f"Annals of Internal Medicine ({era_range})", f'"Ann Intern Med"[Journal] AND {era_range}[pdat]', 1000, offset),
                (f"Circulation ({era_range})", f'"Circulation"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"JACC ({era_range})", f'"J Am Coll Cardiol"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Journal of Clinical Oncology ({era_range})", f'"J Clin Oncol"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Blood ({era_range})", f'"Blood"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Gastroenterology ({era_range})", f'"Gastroenterology"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Cell ({era_range})", f'"Cell"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Stroke ({era_range})", f'"Stroke"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Diabetes Care ({era_range})", f'"Diabetes Care"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Gut ({era_range})", f'"Gut"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"European Heart Journal ({era_range})", f'"Eur Heart J"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Nature (Biomedical) ({era_range})", f'"Nature"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Science (Biomedical) ({era_range})", f'"Science"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Chest ({era_range})", f'"Chest"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Radiology ({era_range})", f'"Radiology"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Pediatrics ({era_range})", f'"Pediatrics"[Journal] AND {era_range}[pdat]', 800, offset),
                (f"Kidney International ({era_range})", f'"Kidney Int"[Journal] AND {era_range}[pdat]', 800, offset),
            ]
            for label, q, limit, off in top_journals:
                tot, nc = harvest_pubmed_batch(con, label, q, run_id, max_items=limit, retstart=off)
                total_swept_new += nc

            specialty_batch = [
                (f"Surgery ({era_range})", f'(surgery[MeSH] OR "surgical procedures"[Title/Abstract]) AND {trial_filter} AND {era_range}[pdat]', 1500, offset),
                (f"Cancer ({era_range})", f'(neoplasms[MeSH] OR cancer[Title/Abstract]) AND {trial_filter} AND {era_range}[pdat]', 1500, offset),
                (f"Genetics ({era_range})", f'(genomics[MeSH] OR genetics[MeSH] OR "gene expression"[Title/Abstract]) AND {trial_filter} AND {era_range}[pdat]', 1500, offset),
                (f"Pharmacology ({era_range})", f'(pharmacovigilance[Title/Abstract] OR "clinical pharmacology"[Title/Abstract] OR "drug safety"[Title/Abstract] OR "adverse drug reaction"[MeSH]) AND {trial_filter} AND {era_range}[pdat]', 1500, offset),
                (f"Immunology ({era_range})", f'(immunology[MeSH] OR immunotherapy[MeSH] OR antibodies[MeSH]) AND {trial_filter} AND {era_range}[pdat]', 1500, offset),
                (f"Laboratory Diagnostics ({era_range})", f'(biomarkers[MeSH] OR "diagnostic accuracy"[Title/Abstract] OR "clinical laboratory techniques"[MeSH]) AND {trial_filter} AND {era_range}[pdat]', 1500, offset),
                (f"Internal Medicine ({era_range})", f'("internal medicine"[Title/Abstract] OR "chronic disease"[Title/Abstract] OR "clinical decision support"[Title/Abstract]) AND {trial_filter} AND {era_range}[pdat]', 1500, offset),
                (f"Computational Biology / AI ({era_range})", f'("medical informatics"[MeSH] OR "computational biology"[MeSH] OR "biostatistics"[MeSH] OR "machine learning"[Title/Abstract] OR "computer"[Title/Abstract]) AND {trial_filter} AND {era_range}[pdat]', 1500, offset),
                (f"Pathology ({era_range})", f'(pathology[MeSH] OR histopathology[MeSH] OR biopsy[MeSH]) AND {trial_filter} AND {era_range}[pdat]', 1500, offset),
                (f"Anatomy ({era_range})", f'(anatomy[MeSH] OR "surgical anatomy"[Title/Abstract] OR "organ transplantation"[MeSH]) AND {trial_filter} AND {era_range}[pdat]', 1500, offset),
            ]
            for label, q, limit, off in specialty_batch:
                tot, nc = harvest_pubmed_batch(con, label, q, run_id, max_items=limit, retstart=off)
                total_swept_new += nc

            vn_queries = [
                (f"Vietnam Medical Research ({era_range})", f'("Vietnam"[Affiliation] OR "Viet Nam"[Affiliation]) AND {era_range}[pdat]', 2000, offset),
            ]
            for label, q, limit, off in vn_queries:
                tot, nc = harvest_pubmed_batch(con, label, q, run_id, max_items=limit, retstart=off)
                total_swept_new += nc

    con.close()
    print(f"\n{'='*70}", flush=True)
    print(f"🎉 HOÀN TẤT QUÉT VÉT TỪ ĐẦU (1990 - 2027)!", flush=True)
    print(f"Tổng số bài báo bị bỏ sót đã thu thập bổ sung thành công: +{total_swept_new:,}", flush=True)
    print(f"{'='*70}\n", flush=True)

    if total_swept_new > 0:
        run_post_processing()
        cur_count = sqlite3.connect(DB_PATH).execute("SELECT COUNT(*) FROM records").fetchone()[0]
        state = load_state()
        state["history"].append({
            "round": "gap_sweep",
            "new_records": total_swept_new,
            "total_records": cur_count,
            "timestamp": now_iso()
        })
        save_state(state)
        git_commit_and_push(f"feat: complete exhaustive gap sweep across 1990-2027 canon (+{total_swept_new:,} missing records, total {cur_count:,})")
    else:
        print("Tất cả các kỷ nguyên từ 1990 đến 2027 đã đầy đủ và không bị bỏ sót bài báo nào!", flush=True)

    return total_swept_new

def main():
    import argparse
    parser = argparse.ArgumentParser(description="VCU Gap-Sweep and Cycle 5 Runner")
    parser.add_argument("--skip-sweep", action="store_true", help="Skip gap sweep and start cycle 5 directly")
    parser.add_argument("--cycle5-rounds", type=int, default=4, help="Number of Cycle 5 rounds to execute")
    args = parser.parse_args()

    # Step 1: Gap sweep from the beginning
    if not args.skip_sweep:
        comprehensive_gap_sweep()

    # Step 2: Complete Cycle 4 (Round 45) if not done yet
    state = load_state()
    cur_r = state.get("current_round", 45)
    if cur_r == 45:
        print(f"\n>>> Hoàn tất Round 45 (Era 8: 2025 - 2027, Cycle 4) để khép lại Chu kỳ 4...", flush=True)
        execute_round(45)

    # Step 3: Start New Cycle (Cycle 5 - Offset 4,000)
    state = load_state()
    start_r = state.get("current_round", 46)
    print(f"\n{'#'*65}", flush=True)
    print(f"🚀 BẮT ĐẦU CHU KỲ MỚI: CHU KỲ 5 (CYCLE 5 - DEEP OFFSET 4,000) 🚀", flush=True)
    print(f"Khởi động từ Round {start_r} (Era 1: 1990 - 1994) với tầng quét sâu 4,000...", flush=True)
    print(f"{'#'*65}\n", flush=True)

    for r in range(start_r, start_r + args.cycle5_rounds):
        execute_round(r)

    print(f"\n🎉 HOÀN THÀNH TOÀN BỘ TIẾN TRÌNH QUÉT VÉT VÀ KHỞI ĐỘNG CHU KỲ MỚI!", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
