# HƯỚNG DẪN CHUYỂN SANG MÁY KHÁC ĐỂ TIẾP TỤC THU THẬP DỮ LIỆU
*VCU Biomedical Library - Kho Dữ Liệu Y Sinh Học Hơn 1.14 Triệu Bản Ghi*

---

Toàn bộ mã nguồn, trạng thái đợt thu thập, và cơ sở dữ liệu đã được nén chia nhỏ `< 45 MB` đẩy lên nhánh `main` của GitHub:
**Repository:** `https://github.com/carbvantu/baitaplonctdl.git`

Khi chuyển sang máy tính mới (Windows, Linux, hoặc macOS), bạn chỉ cần thực hiện 4 bước đơn giản dưới đây:

---

## BƯỚC 1: Tải kho mã nguồn về máy mới

Mở Terminal (hoặc PowerShell / Command Prompt) trên máy mới và chạy:

```bash
git clone https://github.com/carbvantu/baitaplonctdl.git
cd baitaplonctdl
```

---

## BƯỚC 2: Giải nén cơ sở dữ liệu trên máy mới

Tất cả các tệp CSDL lớn (SQLite 3.2 GB, CSV 2.0 GB, JSONL 2.3 GB) đã được chia nhỏ thành các tệp `.zip.part*` an toàn trên GitHub. Bạn chỉ cần chạy lệnh giải nén tự động:

```bash
python unpack_library.py
```

> **Kết quả:** Script sẽ tự động ghép 17 phần zip và khôi phục trọn vẹn:
> - `library_data/vcu_biomedical_library.sqlite` (1,147,230 bản ghi)
> - `library_data/metadata_pubmed.csv`
> - `library_data/metadata_pubmed.jsonl`

---

## BƯỚC 3: Cấu hình mã xác thực GitHub (Để tự động Commit & Push)

Để hệ thống trên máy mới tự động đóng gói `< 45 MB`, commit và push lên GitHub sau mỗi đợt:

1. Tạo một tệp tên là `.git_token` ngay tại thư mục gốc của dự án.
2. Dán mã GitHub Personal Access Token (PAT) của bạn vào tệp đó và lưu lại:
   - Trên Windows PowerShell:
     ```powershell
     Set-Content -Path .git_token -Value "ghp_xxxxxxxxxxxxxxxxxxxx" -NoNewline
     ```
   - Trên Linux/macOS:
     ```bash
     echo -n "ghp_xxxxxxxxxxxxxxxxxxxx" > .git_token
     ```

*(Tệp `.git_token` đã được đưa vào `.gitignore`, tuyệt đối bảo mật và không bị commit lên GitHub).*

---

## BƯỚC 4: Tiếp tục tiến trình thu thập dữ liệu

Hệ thống sẽ tự động đọc `library_data/harvester_state.json` và tiếp tục thu thập chính xác từ **Round 50 (Chu kỳ 5)**:

### Lựa chọn 1: Chạy chuỗi đợt liên tục (Khuyên dùng)
Chạy ví dụ 5 đợt tiếp theo (Rounds 50 – 54):
```bash
python vcu_continuous_rounds_harvester.py --rounds 5
```

### Lựa chọn 2: Chạy quét vét kiểm tra từ đầu rồi tiếp tục Chu kỳ 5
```bash
python vcu_sweep_from_start_and_run_cycle5.py --cycle5-rounds 5
```

---

## 💡 Lưu ý quan trọng:
- Toàn bộ các script đều sử dụng thư viện chuẩn của Python (`sqlite3`, `urllib`, `xml`, `json`, `csv`, `hashlib`...), không cần cài đặt các thư viện nặng phức tạp.
- Bộ lọc thông minh đã được tích hợp sẵn: **Tuyệt đối không tải lại dữ liệu cũ, chỉ thu thập các bản ghi mới bị bỏ sót**.
- Mỗi vòng chạy xong sẽ tự động nén, cắt nhỏ `< 45 MB`, tạo báo cáo và push ngay lập tức lên GitHub.
