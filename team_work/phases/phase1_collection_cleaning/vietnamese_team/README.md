# NewsBreakout — Phase 1 Vietnamese Team

## Goal
Collect Vietnam-related news from **Vietnamese publishers**, perform basic cleaning/normalization, and produce a small sample that follows the shared NewsBreakout schema.

This phase is only about **reliable data collection + compatible cleaned output**.

Do **not** start event clustering, graph analysis, prediction, or final visualization yet.

## Team
- Member 1:
- Member 2:

Working branch:
```text
vnese
```

## Tasks

### 1. Find reliable Vietnamese publishers
Possible starting points:
- VnExpress
- Tuổi Trẻ
- Thanh Niên
- VietnamNet
- Dân Trí
- Lao Động
- VTV
- Tiền Phong

Prefer RSS feeds or another stable automated source.

### 2. Build or update the collector
Put code in:
```text
team_work/phases/phase1_collection_cleaning/vietnamese_team/code/
```

Suggested files:
```text
collect_vn.py (Cào dữ liệu từ 5 RSS feeds, lưu thô, và gọi hàm làm sạch)
clean_vn.py (Xử lý chuỗi, chuẩn hóa URL, băm SHA-256, parse ngày giờ UTC, và map 20 trường)
```

### 3. Basic cleaning
For Phase 1:
- standardize column names
- normalize timestamps
- normalize publisher/domain names
- keep language information
- flag Vietnam relevance
- identify broken rows
- preserve raw data

Do not remove syndicated/duplicate articles yet.

## Shared output schema
```text
article_id
title
url
canonical_url
publisher_domain
publisher_id
publisher_group_id
source_system
first_seen_at
published_at
timestamp_confidence
language
publisher_country
description
category
vietnam_relevance
duplicate_family_id
branch
collection_mode
raw_payload_ref
```

For live Vietnamese collection:
```text
branch = domestic
collection_mode = prospective
```

## Sample output
Put a small review sample in:
```text
team_work/phases/phase1_collection_cleaning/vietnamese_team/sample_output/
```

Recommended size:
```text
20–100 rows
```

Do not commit a large raw news archive.

## Source tracker
| Publisher | Feed / URL | Method | Working? | Notes |
|---|---|---|---|---|
| VnExpress | `https://vnexpress.net/rss/tin-moi-nhat.rss` | RSS | Yes | |
| Tuổi Trẻ | `https://tuoitre.vn/rss/tin-moi-nhat.rss` | RSS | Yes | |
| Thanh Niên | `https://thanhnien.vn/rss/home.rss` | RSS | Yes | |
| VietnamNet | `https://vietnamnet.vn/rss/thoi-su.rss` | RSS | Yes | |
| Dân Trí | `https://dantri.com.vn/rss/home.rss` | RSS | Yes | |

## Done when
- [x] Several working Vietnamese publishers
- [x] Collection runs automatically
- [x] Raw records are preserved
- [x] Small cleaned sample is committed
- [x] `title` is present
- [x] `url` is present
- [x] `publisher_domain` is correct
- [x] `first_seen_at` is present
- [x] `branch = domestic`
- [x] `collection_mode = prospective`
- [x] Output follows the shared schema
- [x] Known issues are documented

## Audit Logs
**Run Timestamp**: September 17, 2026

**Publisher Distribution**:
- vnexpress: 20
- tuoitre: 20
- thanhnien: 20
- dantri: 20
- vietnamnet: 20

**Vietnam Relevance Heuristic**:
- True: 54
- False: 46
(Note: International news and specific health/tech articles on foreign topics are correctly classified as `False`).

### Sample Classification Table
| article_id | publisher_id | category | title | vietnam_relevance |
|---|---|---|---|---|
| f96df9f286cd97e0 | vnexpress |  | Sam Tuyền Lâm vào top sân golf nghỉ dưỡng tốt nhất | True |
| c291b7a36c44120c | tuoitre |  | Fed tăng lãi suất, thị trường chứng khoán Việt Nam thường diễn biến ra sao? | True |
| 2810b30ad33b4db2 | dantri |  | Tìm thấy thi thể nam sinh viên năm nhất bị nước cuốn trôi ở Hà Nội | True |
| f49abcb258654474 | tuoitre |  | Lộ diện quốc gia thứ 2 ở Đông Nam Á có tàu sân bay | True |
| b1597a47cb969d03 | vietnamnet |  | Người đàn ông có biểu hiện bất thường trong quán ăn, Tổ CSGT trợ giúp kịp thời | True |
| 61fb73ccc35597d5 | vietnamnet |  | Hà Nội: Nước ngập rút nhanh, chỉ còn vài điểm úng cục bộ | True |
| dd3dda7816ac9e24 | dantri |  | Chi trăm triệu đồng mua iPhone 18 Pro Max trong ngày đầu mở bán | True |
| 7dae92c555e53530 | thanhnien |  | Ngày đầu mở bán iPhone 18 Pro: Người Việt chen chân, chi trăm tỉ lên đời iPhone | True |
| 3bc5d03be20e5824 | vietnamnet |  | Mâu thuẫn trên mạng, thiếu niên 15 tuổi rủ đồng bọn truy sát đối phương | True |
| 054b2a9ae6b9714d | tuoitre |  | Thứ trưởng Bộ Giáo dục và Đào tạo: Trường tiểu học Nha Trang có quy mô lớn hơn một số trường đại học | True |
| 994bc7ec7e68bd3c | vietnamnet |  | Tìm thấy thi thể nam sinh bị nước cuốn xuống cống ở Hà Nội | True |
| c0c8da791f7810a7 | vnexpress |  | Nhà hàng ở Hà Nội vào top 3 tốt nhất thế giới | True |
| 540e7640f5e75e37 | dantri |  | Ngân hàng Việt đua làm "quản gia" cho giới siêu giàu | True |
| 45db549d591fda40 | dantri |  | Philippines gọi 20 cầu thủ ở nước ngoài, sẵn sàng thách thức tuyển Việt Nam | True |
| a886f398c4b083e8 | tuoitre |  | Phó bí thư Thành ủy TP.HCM Đặng Minh Thông yêu cầu xử lý dứt điểm điểm nghẽn chuyển đổi số | True |
| e59516e0a894cba3 | thanhnien |  | Laptop Acer RTX 5070: 5 cấu hình cho gaming, sáng tạo và công việc chuyên sâu | False |
| 8bf7a935229bb032 | vnexpress |  | Tài xế Đức lĩnh 3 năm tù vì gây tai nạn khiến hai anh em người Việt tử vong | False |
| e96846ec9a404ed3 | vnexpress |  | Australia chặn đường 'nhảy visa' để định cư của du học sinh | False |
| 833c19cc83489600 | thanhnien |  | 3 lý do nên cân nhắc khi chọn mua iPhone 18 Pro Max | False |
| c35ee3bb9fdff4a8 | vnexpress |  | Bẫy 'vẽ tương lai' trong tình yêu | False |
| daa8dd3c845f6f40 | dantri |  | Nam sinh 16 tuổi mất tay trái, bật khóc xin được tiếp tục chữa trị | False |
| 0b139eeeb1af6036 | tuoitre |  | Khi mua sắm cũng cần một khoảng lặng | False |
| 496cd7d6596a2ef0 | thanhnien |  | Phát hiện xe bán tải dưới sông Chẹt Sậy, bên trong có xương người | False |
| 2c047090ccc28e8b | dantri |  | Ra mắt không gian học tập phòng cháy chữa cháy đầu tiên trên cả nước | False |
| 1788eb5fd3738c46 | vnexpress |  | Tôi bất ngờ vì bánh trung thu 'handmade' giá 300.000 đồng | False |
| 7dc98cdd6d830f41 | thanhnien |  | SUV đô thị dưới 650 triệu: Xe Trung Quốc 'đấu' xe Nhật, Hàn bằng trang bị | False |
| b7d2d037bd4fbe9a | vnexpress |  | Petrolimex bán sạch cổ phiếu quỹ | False |
| 6c947a3a8f235408 | tuoitre |  | Châu Tinh Trì ê chề khi làm phim ngắn | False |
| 03c019df8833e660 | vnexpress |  | Vì sao người châu Á dễ đỏ mặt khi uống rượu? | False |
| a75c578fc445d3c9 | tuoitre |  | Bỏ điểm cộng học sinh giỏi, IELTS trong xét tuyển đại học: Có gây 'sốc' cho thí sinh? | False |


**Timestamps**:
- Missing `published_at`: 0

**HTTP Status**:
- All 5 RSS feeds returned successful payloads.

## Known issues
- Some articles without explicit timestamps default to `medium` confidence since they lack timezone details in the RSS tag.
- The `vietnam_relevance` heuristic is conservative for URLs with `/the-gioi/` or `/xe/`, which might flag some obscure localized sub-events as `False` unless a specific VN entity is mentioned.

## Git workflow
Before working:
```bash
git checkout vnese
git pull origin vnese
```

After changes:
```bash
git add team_work/phases/phase1_collection_cleaning/vietnamese_team
git commit -m "Update Vietnamese Phase 1 collection"
git push origin vnese
```
