# VCU Biomedical Library Starter Pack

Ngày phát hành gói: 2026-10-17 (Asia/Bangkok). Đây là **đợt kiểm kê khởi đầu**, không phải toàn bộ tri thức y học.

## Số liệu có thật trong gói khởi đầu

- 12 bản ghi thư mục PubMed được đối chiếu từ kết quả tìm kiếm web, gồm 10 chuyên ngành mục tiêu và 2 bản ghi giao thoa về AI/chẩn đoán.
- 21 nguồn/đầu mối nguồn được đưa vào danh mục (`source_registry.csv`). Đây là số mục nguồn đã đăng ký, không phải 21 kho dữ liệu đã thu thập.
- 0 bài toàn văn được tải hàng loạt; 0 hồ sơ bệnh nhân/dữ liệu cá nhân; 0 tập dữ liệu biến thể gene được tải.
- Không lấy được tổng số kết quả live của E-utilities trong phiên này do kết nối mạng của môi trường chạy không phân giải được tên miền API. Vì vậy số `search_count` trực tiếp từ PubMed được để trống/chưa đo, không suy đoán.
- Bản ghi VCU-PUB-0010 còn thiếu danh sách tác giả đầy đủ; bộ collector có nhiệm vụ bổ sung metadata đó từ EFetch.

## Tạo cơ sở dữ liệu từ mẫu đã xác minh

Cài Python 3.10+ trên máy có quyền truy cập Internet, mở Terminal trong thư mục này và chạy:

```bash
python vcu_collect_pubmed.py --seed-only
```

Lệnh này tạo SQLite từ 12 bản ghi mẫu, không gọi API.

## Thu thập metadata mới từ PubMed

Điền email liên hệ thực của người vận hành (không dùng email giả), rồi chạy:

```bash
python vcu_collect_pubmed.py --email EMAIL_CUA_BAN --max-per-topic 50 --no-abstracts
```

Muốn lấy metadata kèm tóm tắt để nghiên cứu nội bộ:

```bash
python vcu_collect_pubmed.py --email EMAIL_CUA_BAN --max-per-topic 50
```

Có thể giới hạn ngày xuất bản:

```bash
python vcu_collect_pubmed.py --email EMAIL_CUA_BAN --date-from 2024/01/01 --date-to 2026/10/17 --max-per-topic 100
```

Biến môi trường được hỗ trợ: `NCBI_EMAIL`, `NCBI_TOOL`, `NCBI_API_KEY`. Không chia sẻ API key. Tôn trọng giới hạn truy vấn NCBI; mặc định script cố ý giới hạn tốc độ yêu cầu dưới 3 request/giây.

## Tệp đầu ra

Thư mục `library_data/`:

- `vcu_biomedical_library.sqlite`: cơ sở dữ liệu SQLite với bảng `records`, `search_runs`, `source_registry`.
- `metadata_pubmed.jsonl`: metadata tích lũy, một JSON mỗi dòng.
- `metadata_pubmed.csv`: bản xuất để kiểm tra trong Excel.
- `specialty_inventory.csv`: tổng kết từng truy vấn, số kết quả hiện có, số bản ghi thật sự lấy được, số mới/cập nhật, lỗi và mốc thời gian.
- `collection_runs.jsonl`: nhật ký bất biến theo từng đợt chạy.
- `pipeline_status.json`: trạng thái tổng quan.

## Chính sách dữ liệu

1. PMID là khóa đối chiếu chính; DOI/PMCID là định danh phụ. Trùng lặp cần khử theo PMID, sau đó DOI và các trường title/author/year.
2. Số kết quả `search_count` là tổng kết quả trả về tại thời điểm truy vấn; `fetched_count` chỉ là số bản ghi thực tế đã lấy về trong giới hạn `--max-per-topic`. Không được gọi hai số này là cùng một đại lượng.
3. Script không tải toàn văn hàng loạt từ nhà xuất bản. Với PMC, chỉ dùng kênh tự động được PMC cho phép và đọc license từng bài trước khi tái sử dụng hoặc phân phối.
4. Nguồn giáo dục, trang thông tin bệnh nhân, trang thuốc, tạp chí khoa học và cơ sở dữ liệu sinh học có vai trò khác nhau; không đánh đồng nội dung phổ thông với bằng chứng lâm sàng gốc.
5. Không nhập hồ sơ nhận dạng bệnh nhân. Nếu tương lai xử lý dữ liệu người bệnh, cần quyền truy cập, căn cứ pháp lý, đạo đức nghiên cứu, giảm định danh và kiểm soát bảo mật riêng.
6. Nội dung y tế do hệ thống tổng hợp phải có trích dẫn nguồn, ngày cập nhật, mức bằng chứng, phạm vi áp dụng, đối tượng và cờ cảnh báo. Không dùng kho này tự động thay thế quyết định chuyên môn/chẩn đoán/điều trị.

## Hướng mở rộng có thể kiểm toán

Đợt 1: PubMed metadata + khử trùng lặp.
Đợt 2: PMC Open Access subset, chỉ các bài phù hợp license.
Đợt 3: Europe PMC, ClinicalTrials.gov, WHO ICTRP và các nguồn gene/protein/structure chuyên biệt.
Đợt 4: tạp chí Việt Nam — lập chỉ mục metadata trước; chỉ tải full text khi được phép.
Đợt 5: mô hình gene-protein-pathway-cell-disease-drug-clinical-trial với provenance và mapping định danh.
Đợt 6: RAG có trích dẫn, đánh giá độ đầy đủ, độ mới, độ tin cậy và kiểm thử an toàn y khoa.

Không đặt mục tiêu số trang. Đo độ bao phủ bằng số bản ghi duy nhất, số nguồn, số trường hoàn thiện, tỷ lệ trùng, tỷ lệ truy xuất được toàn văn hợp pháp, mốc cập nhật, số bản ghi có license và tỷ lệ chuyên ngành còn thiếu.
