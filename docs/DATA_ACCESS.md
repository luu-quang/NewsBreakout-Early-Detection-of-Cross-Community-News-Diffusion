# Lấy dữ liệu đã thu thập - không cần SSH vào VM

Dành cho ai cần dữ liệu tin tức đã thu thập (VD: để phân tích độ trễ lan
truyền - "Hình 5") nhưng không có quyền SSH vào VM Azure đang chạy collector.
Toàn bộ quy trình chỉ chạy trên máy của bạn, từ lúc clone repo tới lúc có file
`.parquet` để phân tích.

File output ở đây (`data/processed/v2/articles_master_v2_<ngày>.parquet`)
**khác** với `data/processed/master/articles_master.parquet` - đó là bản dữ
liệu đông cứng của Phase 2A (snapshot từ đúng 1 lần chạy collector, ngày
2026-09-20 - mỗi branch domestic/international chỉ chạy đúng 1 lần, không
phải một cửa sổ pilot 48h), không đụng tới. File `_v2_` là bản snapshot liên
tục, cập nhật được nhiều lần, dùng cho phân tích Phase 5 trở đi.

## Bước 0: Clone repo và cài đặt

```bash
git clone https://github.com/luu-quang/NewsBreakout-Early-Detection-of-Cross-Community-News-Diffusion.git
cd NewsBreakout-Early-Detection-of-Cross-Community-News-Diffusion
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Bước 1: Lấy bản backup mới nhất về máy (`scripts/pull_snapshot.py`)

Dữ liệu thô (`data/raw/v2/`) được backup mỗi ngày từ VM lên Google Drive (xem
`deploy/backup_daily.sh`). Có 2 cách lấy về:

**Cách A - có rclone và remote riêng của bạn trỏ vào cùng thư mục Drive:**

```bash
python3 scripts/pull_snapshot.py --rclone-remote gdrive:newsbreakout-backups
```

**Cách B - không có rclone, tải tay:**

```bash
python3 scripts/pull_snapshot.py
```

Lệnh trên (không tham số) sẽ in hướng dẫn: mở thư mục Drive được chia sẻ, tải
file mới nhất dạng `newsbreakout-v2-YYYY-MM-DD.tar.gz`, rồi chạy lại:

```bash
python3 scripts/pull_snapshot.py --local-tarball /đường/dẫn/newsbreakout-v2-2026-09-27.tar.gz
```

Cả 2 cách đều giải nén thẳng vào `data/raw/v2/` (thư mục này đã có trong
`.gitignore`, không lo commit nhầm dữ liệu thô). Mỗi bản backup là snapshot
đầy đủ tại thời điểm đó (không phải phần bù), nên chỉ cần bản mới nhất, không
cần gộp nhiều ngày.

## Bước 2: Build snapshot đã làm sạch (`scripts/build_snapshot.py`)

```bash
python3 scripts/build_snapshot.py
```

Lệnh này tự động chạy nối tiếp đúng pipeline Phase 1 hiện có (không đổi gì cả
- `build_candidate_table` -> `clean_vn.py`/`clean_intl.py` -> `build_master.py`)
trên toàn bộ dữ liệu vừa tải về, rồi ghi ra:

- `data/processed/v2/articles_master_v2_<ngày>.parquet` - bài đã lọc quan hệ
  Việt Nam, đã gộp cả 2 nhánh domestic/international, đúng schema chuẩn của
  `build_master.py` (`SHARED_SCHEMA`) **cộng thêm 1 cột `is_pre_start`**.
- `data/processed/v2/articles_audit_v2_<ngày>.parquet` - bản đầy đủ kể cả bài
  bị loại (kèm `rejection_reason`), cũng có `is_pre_start`.
- `data/processed/v2/articles_master_v2_<ngày>.manifest.json` - để tra cứu:
  `sha256` của file parquet, số dòng, khoảng thời gian (`first_seen_at`/
  `published_at`), số bài theo nhánh/theo publisher, số bài
  `is_pre_start=True/False/unknown`, và danh sách từng feed kèm
  `feed_started_at` (thời điểm collector lần đầu thấy feed đó có bài).

Lọc theo khoảng thời gian thu thập (không phải thời gian đăng bài) bằng
`--since`/`--until` (ISO date/datetime, `--since` gồm cả mốc đó, `--until`
không gồm):

```bash
python3 scripts/build_snapshot.py --since 2026-09-27 --until 2026-09-28
```

### Cột `is_pre_start` nghĩa là gì

`True` = bài này được đăng (`published_at`) **trước** lần đầu tiên collector
thấy feed đó ra bài (`feed_started_at`) - tức là bài "backlog" bị RSS trả về
ngay ở lần poll đầu tiên (VD: Vietnamnet có RSS sâu ~30 ngày), không phải bài
được bắt real-time. `False` = bài đến sau khi feed đã bắt đầu, coi là dữ liệu
thời gian thực hợp lệ. `None`/`unknown` = không xác định được (feed đó chưa
từng ghi nhận `feed_started_at`, hoặc bài thiếu `published_at`) - **luôn coi
là "không chắc", không được ngầm hiểu là `False`**.

Cho phân tích Hình 5 (độ trễ lan truyền): lọc `is_pre_start == False` trước
khi tính, để không tính nhầm bài cũ vào tốc độ lan truyền.

## Bước 3: Đọc dữ liệu

```python
import pandas as pd

df = pd.read_parquet("data/processed/v2/articles_master_v2_2026-09-27.parquet")
df_realtime = df[df["is_pre_start"] == False]   # loại backlog
```

Các cột đúng như `SHARED_SCHEMA` trong `build_master.py`: `article_id`,
`title`, `url`, `canonical_url`, `publisher_domain`, `publisher_id`,
`publisher_group_id`, `source_system`, `first_seen_at`, `published_at`,
`timestamp_confidence`, `language`, `publisher_country`, `description`,
`category`, `vietnam_relevance`, `duplicate_family_id`, `branch`,
`collection_mode`, `raw_payload_ref`, cộng thêm `is_pre_start`.

## Sự cố thường gặp

- **"No candidate rows found in data/raw/v2/"**: chưa chạy Bước 1, hoặc
  `--since`/`--until` không khớp dữ liệu có sẵn.
- **Thiếu `feedparser`/`dateutil`**: chạy `pip install -r requirements.txt`
  trong đúng venv đang active.
- Cần xem nhanh log/lệnh khác (SSH, push/PR/tag) - xem `docs/CHEATSHEET.md`.
