#!/usr/bin/env python3
"""VCU Report Generator: automatically query the local biomedical library SQLite
and generate Markdown and CSV reports into the reports/ folder.
"""
from __future__ import annotations
import csv, json, sqlite3, sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = ROOT / "library_data" / "vcu_biomedical_library.sqlite"

def main():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB_PATH)
    total = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    with_doi = con.execute("SELECT COUNT(*) FROM records WHERE doi IS NOT NULL AND doi != ''").fetchone()[0]
    with_pmcid = con.execute("SELECT COUNT(*) FROM records WHERE pmcid IS NOT NULL AND pmcid != ''").fetchone()[0]
    with_mesh = con.execute("SELECT COUNT(*) FROM records WHERE mesh_terms_json IS NOT NULL AND mesh_terms_json != '[]'").fetchone()[0]

    specialties = con.execute(
        "SELECT specialty, COUNT(*) FROM record_specialties GROUP BY specialty ORDER BY COUNT(*) DESC"
    ).fetchall()

    journals = con.execute(
        "SELECT journal, COUNT(*) FROM records WHERE journal != '' GROUP BY journal ORDER BY COUNT(*) DESC LIMIT 10"
    ).fetchall()

    years = con.execute(
        "SELECT SUBSTR(publication_date, 1, 4) as yr, COUNT(*) FROM records GROUP BY yr ORDER BY yr DESC LIMIT 10"
    ).fetchall()

    con.close()

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    timestamp_tag = datetime.now().strftime("%Y%m%d_%H%M%S")

    md_content = f"""# BÁO CÁO CẬP NHẬT KHO DỮ LIỆU Y SINH HỌC VCU
*Thời gian xuất báo cáo: {now_str}*

## 1. Thống Kê Tổng Thể
- **Tổng số bản ghi duy nhất:** {total:,} bài
- **Bản ghi có DOI:** {with_doi:,} ({with_doi/total*100:.1f}%)
- **Bản ghi có PMCID (khả năng lấy toàn văn):** {with_pmcid:,} ({with_pmcid/total*100:.1f}%)
- **Bản ghi có thuật ngữ MeSH:** {with_mesh:,} ({with_mesh/total*100:.1f}%)

## 2. Phân Bố Theo Chuyên Ngành
| STT | Chuyên ngành | Số lượng bản ghi |
|:---:|:---|:---:|
"""
    for i, (spec, cnt) in enumerate(specialties, 1):
        md_content += f"| {i} | {spec} | {cnt:,} |\n"

    md_content += "\n## 3. Top 10 Tạp Chí\n| STT | Tạp chí | Số lượng bài |\n|:---:|:---|:---:|\n"
    for i, (jnl, cnt) in enumerate(journals, 1):
        md_content += f"| {i} | *{jnl}* | {cnt:,} |\n"

    md_content += "\n## 4. Phân Bố Năm Xuất Bản\n| Năm | Số bài |\n|:---:|:---:|\n"
    for yr, cnt in years:
        md_content += f"| {yr or 'Không rõ'} | {cnt:,} |\n"

    report_path = HERE / f"bao_cao_tu_dong_{timestamp_tag}.md"
    latest_path = HERE / "BAO_CAO_TONG_HOP_THU_THAP.md"
    
    report_path.write_text(md_content, encoding="utf-8")
    latest_path.write_text(md_content, encoding="utf-8")
    print(f"Report generated successfully: {latest_path}")
    print(f"Timestamped archive: {report_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
