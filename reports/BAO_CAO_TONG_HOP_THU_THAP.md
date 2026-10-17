# BÁO CÁO TỔNG HỢP KHO DỮ LIỆU Y SINH HỌC VCU (LŨY KẾ 2 ĐỢT)
**Hệ thống Kho Dữ liệu Y Sinh học VCU (VCU Biomedical Library)**  
*Đợt chạy mới nhất: `vcu_20261017T155105Z` (Giai đoạn 2020 – 2024) | Ngày cập nhật: 17/10/2026*

---

## 1. Thông Tin Tổng Quan Tiến Trình Thu Thập

- **Cơ quan thu thập:** VCU Biomedical Library Pipeline
- **Email vận hành:** `dotu020806@gmail.com`
- **Công cụ:** `VCUBiomedicalLibrary/1.0` (tuân thủ NCBI E-utilities Policy $\le$ 3 req/s)
- **Lịch sử các đợt chạy đã hợp nhất thành công:**
  1. **Đợt 1 (Mới nhất):** Thu thập 500 bài/chuyên ngành $\rightarrow$ nạp 4,522 bài duy nhất.
  2. **Đợt 2 (Giai đoạn 2020 – 2024):** Thu thập 1,000 bài/chuyên ngành $\rightarrow$ bổ sung **9,138 bài mới**, nâng tổng số lên **13,660 bài duy nhất**.

---

## 2. Bảng Kiểm Kê Dữ Liệu Theo 10 Chuyên Ngành Y Học (Lũy Kế)

| STT | Chuyên ngành | Số kết quả trên PubMed (2020–2024) | Đã lấy đợt 2 (`fetched_count`) | Bài mới bổ sung (`new_count`) | Tổng bản ghi tích lũy trong CSDL | Tình trạng |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|
| 1 | **Xét nghiệm chẩn đoán** *(Laboratory diagnostics)* | 48,624 | 1,000 | 730 | **1,501** | Hoàn tất |
| 2 | **Miễn dịch học** *(Immunology)* | 37,638 | 1,000 | 949 | **1,501** | Hoàn tất |
| 3 | **Ung thư** *(Cancer)* | 55,343 | 999 | 999 | **1,500** | Hoàn tất |
| 4 | **Giải phẫu học** *(Anatomy)* | 27,654 | 1,000 | 982 | **1,500** | Hoàn tất |
| 5 | **Sinh học tính toán** *(Computational biology)* | 7,921 | 999 | 816 | **1,500** | Hoàn tất |
| 6 | **Ngoại khoa** *(Surgery)* | 84,546 | 1,000 | 820 | **1,497** | Hoàn tất |
| 7 | **Nội khoa** *(Internal medicine)* | 29,576 | 996 | 940 | **1,497** | Hoàn tất |
| 8 | **Dược lý học** *(Pharmacology)* | 4,359 | 999 | 986 | **1,497** | Hoàn tất |
| 9 | **Bệnh học** *(Pathology)* | 4,033 | 998 | 972 | **1,497** | Hoàn tất |
| 10 | **Di truyền học** *(Genetics)* | 12,896 | 959 | 944 | **1,440** | Hoàn tất |
| -- | **Tổng cộng (Khử trùng lặp qua PMID)** | **312,590 bài** | **9,950 lượt lấy** | **9,138 bài mới** | **13,660 bài duy nhất** | **100% Thành công** |

---

## 3. Chỉ Số Chất Lượng Siêu Dữ Liệu (Metadata Quality Metrics)

Toàn bộ kho dữ liệu đã đạt các tiêu chuẩn định danh học thuật khắt khe:

- **Tổng số bản ghi duy nhất:** **13,660 bài báo y sinh học**
- **Độ phủ mã định danh DOI:** **13,612 / 13,660 bài (99.6%)** — đảm bảo tính trích dẫn và liên kết trực tiếp tới bài báo gốc.
- **Bản ghi có mã PMCID (PubMed Central):** **5,380 bài (39.4%)** — sẵn sàng cho khai thác toàn văn hợp pháp qua Open Access.
- **Bản ghi có thuật ngữ chuẩn hóa MeSH:** **10,954 bài (80.2%)** — phục vụ phân loại chủ đề, tìm kiếm ngữ nghĩa và xây dựng Knowledge Graph y khoa.

---

## 4. Top 10 Tạp Chí Y Học Có Số Bài Lớn Nhất Trong Kho

| STT | Tên Tạp chí Y học | Số bài trong kho |
|:---:|:---|:---:|
| 1 | *Journal of ethnopharmacology* | 108 |
| 2 | *Annals of medicine* | 94 |
| 3 | *International journal of molecular sciences* | 88 |
| 4 | *Frontiers in immunology* | 87 |
| 5 | *Interventional neuroradiology* | 83 |
| 6 | *Cancers* | 70 |
| 7 | *Cureus* | 66 |
| 8 | *Abdominal radiology* | 65 |
| 9 | *Journal of endovascular therapy* | 60 |
| 10 | *Human vaccines & immunotherapeutics* | 56 |

---

## 5. Phân Bố Thời Gian Xuất Bản

- **2027 (Ahead of Print / Xuất bản sớm):** 104 bài
- **2026:** 4,792 bài
- **2025:** 5,468 bài
- **2024:** 3,250 bài
- **2023:** 44 bài
- **2022:** 2 bài

---

## 6. Danh Mục Tệp Dữ Liệu Hiện Tại

- **Kho lưu trữ chính:**
  - [vcu_biomedical_library.sqlite](file:///c:/VCU_Library_Starter_Pack/library_data/vcu_biomedical_library.sqlite) (**~13.2 MB**): Cơ sở dữ liệu SQLite chính.
  - [metadata_pubmed.csv](file:///c:/VCU_Library_Starter_Pack/library_data/metadata_pubmed.csv) (**~8.7 MB**): Bảng dữ liệu mở trong Excel.
  - [metadata_pubmed.jsonl](file:///c:/VCU_Library_Starter_Pack/library_data/metadata_pubmed.jsonl) (**~13.1 MB**): Dữ liệu dòng JSON cho AI/RAG.
- **Thư mục báo cáo (`reports/`):**
  - [BAO_CAO_TONG_HOP_THU_THAP.md](file:///c:/VCU_Library_Starter_Pack/reports/BAO_CAO_TONG_HOP_THU_THAP.md): Báo cáo tổng hợp chi tiết dạng Markdown.
  - [specialty_summary_report.csv](file:///c:/VCU_Library_Starter_Pack/reports/specialty_summary_report.csv): Bảng tóm tắt số liệu chuyên ngành.
  - [generate_report.py](file:///c:/VCU_Library_Starter_Pack/reports/generate_report.py): Công cụ tự động cập nhật báo cáo.
