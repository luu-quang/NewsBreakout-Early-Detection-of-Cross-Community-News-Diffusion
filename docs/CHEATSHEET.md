# Cheatsheet — các lệnh hay dùng

Tập hợp lệnh thao tác thường xuyên: SSH vào VM, kiểm tra trạng thái, và quy
trình push/PR/tag/redeploy khi thêm feed hoặc thay đổi code collector. Chi
tiết đầy đủ từng bước deploy nằm ở [deploy/README.md](../deploy/README.md) -
file này chỉ là bản rút gọn để copy-paste nhanh.

## Trạng thái hiện tại (cập nhật 2026-09-27)

- Tag đang chạy trên VM: **`collector-v2.1`** (PR #13, merge `8ae4e29`).
- 10 feed VN đang chạy: 5 feed gốc (vnexpress, tuoitre, thanhnien, dantri,
  vietnamnet) + 5 feed Phase 5 batch 1 (vietnamplus, baotintuc, tienphong,
  sggp, nhandan) - đã verify fresh thật trên VM sau redeploy.
- Batch 2 (chưa làm): VTC News đang bị giữ lại (feed "tin-moi-nhat" nhưng bài
  top đứng yên ở 24/09 qua 2 lần check độc lập - cần theo dõi thêm trước khi
  thêm). Còn thiếu ứng viên cho: Znews (chưa tìm ra feed), VOV (chỉ có feed cũ
  2025 hoặc feed chuyên mục, không dùng được), Vietnamnet feed thứ 2 (chưa tìm
  ra URL). Lao Động, Người Lao Động, Pháp Luật TP.HCM đã bị loại hẳn (xem mục
  8 bên dưới) - không cần tìm lại trừ khi có URL khác.

## 1. SSH vào VM

```bash
ssh -i /path/to/your-key.pem azureuser@20.222.20.253
```

Thay `/path/to/your-key.pem` bằng đường dẫn thật tới file `.pem` bạn tải về
(không commit file này vào repo).

## 2. Kiểm tra trạng thái collector đang chạy trên VM

```bash
you@vm$ systemctl status collector-runner.timer collector-runner.service
you@vm$ systemctl list-timers | grep newsbreakout
you@vm$ tail -50 /var/log/newsbreakout/collector.log
you@vm$ tail -20 /var/log/newsbreakout/backup.log
you@vm$ cat /opt/newsbreakout/data/raw/v2/heartbeat/$(hostname)-$(date -u +%Y-%m).jsonl | tail -5
```

## 3. Chạy tay một lần để verify (trước khi tin tưởng timer)

```bash
you@vm$ sudo -u newsbreakout /opt/newsbreakout/.venv/bin/python3 /opt/newsbreakout/scripts/run_collectors.py --fetch-timeout 20 --child-timeout 120
```

Nhìn dòng `[rss] fetching <id>: <url>` cho từng feed - có báo `fetch failed`
không, và cuối cùng là JSON heartbeat (`overall_ok`, per-child `ok` /
`duration_seconds` / counts / `error`).

## 4. Verify một feed RSS mới trước khi thêm vào code (chạy trên VM)

```bash
you@vm$ /opt/newsbreakout/.venv/bin/python3 -c "
import feedparser
d = feedparser.parse('URL_FEED_CAN_CHECK')
print('status=', d.get('status'), 'entries=', len(d.entries))
if d.entries:
    print('sample:', d.entries[0].get('published'), '|', d.entries[0].get('link'))
"
```

Dùng đúng venv (`/opt/newsbreakout/.venv/bin/python3`), không dùng `python3`
hệ thống - thiếu `feedparser`. Cũng không cần `requests`, `feedparser.parse(url)`
tự fetch qua urllib.

## 5. Push branch, mở PR

```bash
git push -u origin <ten-branch>
gh pr create --title "..." --body "..."   # nếu có gh CLI
```

Nếu không có `gh`, mở PR thủ công trên GitHub từ branch vừa push.

## 6. Sau khi PR merge: tag phiên bản mới

```bash
git checkout main && git pull
git tag collector-vX.Y <merge-commit-sha>
git push origin collector-vX.Y
```

Quy ước: tăng số phụ (`v2.0` -> `v2.1` -> `v2.2` ...) mỗi khi thêm một batch
feed mới (tối đa 5 feed/batch). Chỉ tăng số chính khi có thay đổi kiến trúc
lớn (đổi contract, đổi cách lưu trữ...).

## 7. Redeploy tag mới lên VM

```bash
you@vm$ sudo systemctl stop collector-runner.timer
you@vm$ sudo bash /opt/newsbreakout/deploy/setup.sh collector-vX.Y
you@vm$ sudo systemctl start collector-runner.timer
```

`setup.sh` idempotent, không đụng `data/raw/`. Sau khi start lại timer, chạy
lại bước 3 (verify tay) một lần trước khi để timer tự chạy.

## 8. Quy trình thêm feed mới (Phase 5, tóm tắt)

1. Không sửa/xóa feed đang chạy - chỉ thêm feed mới, mỗi feed một `feed_id`
   riêng.
2. Verify từng feed ứng viên TỪ VM (bước 4 ở trên): HTTP status, số entry,
   có `pubDate` không, định dạng timezone, mẫu URL bài viết. Loại feed nào
   không có `published_at` - Hình 5 (độ trễ lan truyền) cần trường này.
3. Loại các site chỉ đăng lại nội dung báo khác (kể cả do sáp nhập, như
   trường hợp NLD/PLO hiện đăng lại nội dung Tuổi Trẻ).
4. Đưa bảng đề xuất (báo, URL, entry count, có pubDate, ghi chú) để duyệt
   trước khi sửa code.
5. Thêm tối đa 5 feed/batch, mỗi batch một tag mới (`collector-v2.1`,
   `collector-v2.2`, ...), redeploy theo bước 6-7 ở trên.
