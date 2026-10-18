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

SPEC_VI_MAP = {
    "Cancer": "Ung thư",
    "Laboratory diagnostics": "Xét nghiệm chẩn đoán",
    "Immunology": "Miễn dịch học",
    "Anatomy": "Giải phẫu học",
    "Surgery": "Ngoại khoa",
    "Internal medicine": "Nội khoa",
    "Computational biology": "Sinh học tính toán",
    "Genetics": "Di truyền học",
    "Pathology": "Bệnh học",
    "Pharmacology": "Dược lý học",
    "Computational pathology": "Bệnh học tính toán (Seed)",
    "Clinical AI / imaging": "Trí tuệ nhân tạo lâm sàng (Seed)",
}

def main():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB_PATH)
    total = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    with_doi = con.execute("SELECT COUNT(*) FROM records WHERE doi IS NOT NULL AND doi != ''").fetchone()[0]
    with_pmcid = con.execute("SELECT COUNT(*) FROM records WHERE pmcid IS NOT NULL AND pmcid != ''").fetchone()[0]
    with_mesh = con.execute("SELECT COUNT(*) FROM records WHERE mesh_terms_json IS NOT NULL AND mesh_terms_json != '[]'").fetchone()[0]
    with_abs = con.execute("SELECT COUNT(*) FROM records WHERE abstract IS NOT NULL AND length(abstract) > 0").fetchone()[0]

    prestigious_names = [
        ("The Lancet", "%Lancet%"),
        ("The New England Journal of Medicine (NEJM)", "%New England journal of medicine%"),
        ("The BMJ (British Medical Journal)", "%BMJ%"),
        ("JAMA & JAMA Internal Medicine", "%JAMA%"),
        ("Annals of Internal Medicine", "%Annals of internal medicine%"),
        ("Tạp chí Y học Việt Nam (VMJ)", "%Tạp chí Y học Việt Nam%"),
        ("Tạp chí Nghiên cứu Y học (TCNCYH)", "%Tạp chí Nghiên cứu Y học%"),
        ("Tạp chí Y học Cộng đồng (YHCD)", "%Tạp chí Y học Cộng đồng%"),
        ("Dieutri.vn (Phác đồ & Y học lâm sàng Việt Nam)", "%Dieutri.vn%"),
        ("NIH MedlinePlus (National Institutes of Health)", "%NIH MedlinePlus%"),
    ]
    p_stats = []
    for label, pat in prestigious_names:
        row = con.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN abstract IS NOT NULL AND length(abstract) > 0 THEN 1 ELSE 0 END), 0) FROM records WHERE journal LIKE ?", (pat,)).fetchone()
        cnt = row[0] or 0
        abs_c = row[1] or 0
        p_stats.append((label, cnt, abs_c))

    # Stats for 2024 to present
    c_2024_now = con.execute("""
        SELECT COUNT(*), 
               SUM(CASE WHEN abstract IS NOT NULL AND length(abstract) > 0 THEN 1 ELSE 0 END),
               SUM(CASE WHEN doi IS NOT NULL AND doi != '' THEN 1 ELSE 0 END),
               SUM(CASE WHEN pmcid IS NOT NULL AND pmcid != '' THEN 1 ELSE 0 END)
        FROM records 
        WHERE SUBSTR(publication_date, 1, 4) IN ('2024', '2025', '2026', '2027')
    """).fetchone()

    # Stats for 2020 - 2024
    c_2020_2024 = con.execute("""
        SELECT COUNT(*), 
               SUM(CASE WHEN abstract IS NOT NULL AND length(abstract) > 0 THEN 1 ELSE 0 END),
               SUM(CASE WHEN doi IS NOT NULL AND doi != '' THEN 1 ELSE 0 END),
               SUM(CASE WHEN pmcid IS NOT NULL AND pmcid != '' THEN 1 ELSE 0 END)
        FROM records 
        WHERE SUBSTR(publication_date, 1, 4) IN ('2020', '2021', '2022', '2023', '2024')
    """).fetchone()

    spec_stats = con.execute("""
        SELECT rs.specialty, COUNT(DISTINCT rs.pmid) as cnt,
               SUM(CASE WHEN r.doi IS NOT NULL AND r.doi != '' THEN 1 ELSE 0 END)*100.0/COUNT(*) as p_doi,
               SUM(CASE WHEN r.pmcid IS NOT NULL AND r.pmcid != '' THEN 1 ELSE 0 END)*100.0/COUNT(*) as p_pmc,
               SUM(CASE WHEN r.mesh_terms_json IS NOT NULL AND r.mesh_terms_json != '[]' THEN 1 ELSE 0 END)*100.0/COUNT(*) as p_mesh,
               SUM(CASE WHEN r.abstract IS NOT NULL AND length(r.abstract) > 0 THEN 1 ELSE 0 END)*100.0/COUNT(*) as p_abs
        FROM record_specialties rs 
        JOIN records r ON rs.pmid = r.pmid 
        GROUP BY rs.specialty 
        ORDER BY cnt DESC
    """).fetchall()

    journals = con.execute(
        "SELECT journal, COUNT(*) FROM records WHERE journal != '' GROUP BY journal ORDER BY COUNT(*) DESC LIMIT 15"
    ).fetchall()

    years = con.execute(
        "SELECT SUBSTR(publication_date, 1, 4) as yr, COUNT(*), "
        "SUM(CASE WHEN abstract IS NOT NULL AND length(abstract) > 0 THEN 1 ELSE 0 END) "
        "FROM records GROUP BY yr ORDER BY yr DESC"
    ).fetchall()

    con.close()

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    timestamp_tag = datetime.now().strftime("%Y%m%d_%H%M%S")

    md_content = f"""# BÁO CÁO CẬP NHẬT KHO DỮ LIỆU Y SINH HỌC VCU
*Thời gian xuất báo cáo: {now_str}*

## 1. Thống Kê Tổng Thể Toàn Bộ Thư Viện
- **Tổng số bản ghi duy nhất:** {total:,} bài
- **Bản ghi có tóm tắt nghiên cứu gốc đầy đủ (Full Abstract):** {with_abs:,} ({with_abs/total*100:.1f}%)
- **Bản ghi có định danh số DOI:** {with_doi:,} ({with_doi/total*100:.1f}%)
- **Bản ghi có mã PMCID (khả năng mở rộng toàn văn PMC):** {with_pmcid:,} ({with_pmcid/total*100:.1f}%)
- **Bản ghi có thuật ngữ y học MeSH:** {with_mesh:,} ({with_mesh/total*100:.1f}%)

---

## 2. Các Tạp Chí Y Khoa Hàng Đầu Quốc Tế & Cơ Sở Dữ Liệu Việt Nam
| Tạp chí / Nguồn y học | Tổng số bài | Số bài có Full Abstract | Tỷ lệ Abstract | Ghi chú chất lượng |
|:---|:---:|:---:|:---:|:---|
"""
    for j_label, j_cnt, j_abs in p_stats:
        rate = j_abs / j_cnt * 100 if j_cnt > 0 else 0
        md_content += f"| **{j_label}** | {j_cnt:,} | {j_abs:,} | {rate:.1f}% | Nghiên cứu y học lâm sàng đỉnh cao |\n"

    md_content += f"""
---

## 3. Thống Kê Riêng Giai Đoạn 2024 Đến Nay (2024 – 2027)
- **Tổng số bài giai đoạn 2024 đến nay:** {c_2024_now[0]:,} bài
- **Bài có Full Abstract (tóm tắt gốc tác giả):** {c_2024_now[1]:,} ({c_2024_now[1]/c_2024_now[0]*100:.1f}%)
- **Bài có mã DOI:** {c_2024_now[2]:,} ({c_2024_now[2]/c_2024_now[0]*100:.1f}%)
- **Bài có PMCID:** {c_2024_now[3]:,} ({c_2024_now[3]/c_2024_now[0]*100:.1f}%)

---

## 4. Thống Kê Giai Đoạn 2020 – 2024
- **Tổng số bài giai đoạn 2020 – 2024:** {c_2020_2024[0]:,} bài
- **Bài có Full Abstract:** {c_2020_2024[1]:,} ({c_2020_2024[1]/c_2020_2024[0]*100:.1f}%)
- **Bài có mã DOI:** {c_2020_2024[2]:,} ({c_2020_2024[2]/c_2020_2024[0]*100:.1f}%)
- **Bài có PMCID:** {c_2020_2024[3]:,} ({c_2020_2024[3]/c_2020_2024[0]*100:.1f}%)

---

## 5. Phân Bố Theo 10 Chuyên Ngành Y Học Trọng Điểm
| STT | Chuyên ngành | Tiếng Anh | Số lượng bài | Có DOI | Có PMCID | Có MeSH | Có Full Abstract |
|:---:|:---|:---|:---:|:---:|:---:|:---:|:---:|
"""
    for i, (spec, cnt, p_doi, p_pmc, p_mesh, p_abs) in enumerate(spec_stats, 1):
        vi_name = SPEC_VI_MAP.get(spec, spec)
        md_content += f"| {i} | **{vi_name}** | *{spec}* | {cnt:,} | {p_doi:.1f}% | {p_pmc:.1f}% | {p_mesh:.1f}% | {p_abs:.1f}% |\n"

    md_content += "\n---\n\n## 6. Top 15 Tạp Chí Xuất Bản Uy Tín\n| STT | Tạp chí | Số lượng bài |\n|:---:|:---|:---:|\n"
    for i, (jnl, cnt) in enumerate(journals, 1):
        md_content += f"| {i} | *{jnl}* | {cnt:,} |\n"

    md_content += "\n---\n\n## 7. Phân Bố Theo Năm Xuất Bản (1990 – 2027)\n| Năm | Tổng số bài | Số bài có Full Abstract | Tỷ lệ Abstract |\n|:---:|:---:|:---:|:---:|\n"
    for yr, cnt, abs_cnt in years:
        if yr and yr.isdigit() and int(yr) >= 1990:
            rate = abs_cnt / cnt * 100 if cnt > 0 else 0
            md_content += f"| {yr} | {cnt:,} | {abs_cnt:,} | {rate:.1f}% |\n"

    report_path = HERE / f"bao_cao_tu_dong_{timestamp_tag}.md"
    latest_path = HERE / "BAO_CAO_TONG_HOP_THU_THAP.md"
    
    report_path.write_text(md_content, encoding="utf-8")
    latest_path.write_text(md_content, encoding="utf-8")
    print(f"Report generated successfully: {latest_path}")
    print(f"Timestamped archive: {report_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
