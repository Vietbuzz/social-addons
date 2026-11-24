# Livestream Instagram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa bình luận Instagram Live và Instagram Direct vào màn hình điều hành, dùng lại lõi đơn/cọc/SePay.

**Architecture:** Module `livestream_instagram` phụ thuộc `livestream_facebook` (dùng lại `graph_api`, field Meta App, kiểm tra chữ ký). Tài khoản kết nối platform `instagram`, `external_id` = IG account id, gửi/nhận qua Page token của Page liên kết (Instagram qua Facebook Login).

**Tech Stack:** Odoo 20, Graph API v27.0 (graph.facebook.com), OWL 3.

**Spec:** `docs/superpowers/specs/2026-11-24-livestream-instagram-design.md` (mở rộng `2026-11-22-livestream-sale-design.md`)

## Global Constraints
- Module trong `individual_addons/livestream_instagram`, version `20.0.1.0.0`, LGPL-3.
- Webhook `object = "instagram"`, `entry[].id` = IG account id; field `live_comments` dạng `changes[]` với `value.comment_id`, `value.from{id,username}`, `value.text`, `value.media{id}`.
- Private reply chỉ khi phiên còn `live`; tin văn bản ≤ 1000 byte UTF-8 (tách nếu dài).
- Ảnh: upload `POST /{page_id}/message_attachments` (`platform=instagram`, multipart `filedata`) → `attachment_id` → gửi `message.attachment {type: image, payload: {attachment_id}}`.
- Kéo bù bình luận: `GET /{media_id}/ordered_comments?fields=id,text,timestamp,from{id,username}`; phát hiện live: `GET /{ig_id}/live_media?fields=id,media_product_type,timestamp`.
- Lệnh test: như kế hoạch trước, `<mods>=livestream_sale,livestream_sepay,livestream_facebook,livestream_instagram`, `<tags>=/livestream_instagram`.

## Review Focus
1. Webhook `messages` đến dạng `messaging[]` hoặc `changes[field=messages]` → cả hai đều nhận được, không trùng. → `test_message_both_shapes` (Task 1).
2. Khách bình luận rồi nhắn Direct: IGSID trùng `from.id` → cùng một khách, không tạo khách thứ hai. → `test_comment_then_dm_same_customer` (Task 1).
3. Trợ lý nhắn khi live đã tắt mà khách chưa nhắn → báo lỗi rõ, không gửi. → `test_private_reply_after_live_ended_refused` (Task 2).
4. Tin yêu cầu cọc tiếng Việt dài > 1000 byte → tách nhiều tin, không cắt giữa ký tự UTF-8. → `test_long_message_split_utf8` (Task 2).
5. Live kết thúc mà không có webhook → cron đánh dấu `ended` khi media biến mất khỏi `live_media`. → `test_cron_ends_missing_live` (Task 3).

---

### Task 1: Module, tài khoản Instagram, webhook nhận bình luận & tin nhắn
**Files:** Create `livestream_instagram/{__init__,__manifest__}.py`, `models/{__init__,livestream_account,livestream_session,livestream_webhook_event}.py`, `controllers/{__init__,main}.py`, `views/livestream_account_views.xml`, `tests/{__init__,test_instagram}.py`, `tests/payloads/{live_comment,message}.json`. Modify `livestream_facebook/controllers/main.py` (tách `verify_meta_signature(body: bytes, header: str, secret: str) -> bool` ra hàm module-level dùng chung).

**Interfaces:**
- `livestream.account`: `platform` `selection_add=[("instagram","Instagram")]`; field `fb_page_id` Char (Page liên kết; dùng cho các call `/{page_id}/...`).
- `livestream.session._ig_upsert_live(account, media_id: str, live: bool) -> session` (draft→live được; ended không mở lại).
- `livestream.webhook.event.source` thêm `instagram`; `_process_instagram(entry)`: `changes[field=live_comments]` → `_ingest(session, value.comment_id, value.from.id, value.from.username, value.text, time=entry.time)` (bỏ qua `from.id == account.external_id`; tạo/đặt live phiên theo `value.media.id`); tin nhắn ở `messaging[]` hoặc `changes[field=messages].value` → `_ig_message(account, sender_id, message)` (bỏ `is_echo`/`is_self`).
- `_ig_customer_for_igsid(account, igsid) -> livestream.customer`: ưu tiên customer có `psid == igsid`, rồi `external_user_id == igsid` (đặt `psid`), rồi khách đang chờ cùng `username` (lấy qua `GET /{igsid}?fields=username,name`), cuối cùng tạo mới.
- Controller `GET/POST /livestream/instagram/webhook`: verify token theo account platform instagram; chữ ký theo account có `external_id == entry.id`.

- [ ] Test (`test_verify_challenge`, `test_signature_required`, `test_live_comment_ingested` (tag 69 x2, phiên tạo ở trạng thái live theo media id), `test_own_comment_ignored`, `test_message_both_shapes`, `test_comment_then_dm_same_customer`, `test_dm_links_pending_by_username`, `test_echo_ignored`) → chạy → FAIL.
- [ ] Cài đặt → chạy → PASS. Commit `feat(livestream_instagram): account, webhooks for live comments and Direct`.

### Task 2: Gửi tin: private reply, Direct, tách tin, ảnh
**Files:** Modify `livestream_instagram/models/livestream_account.py`; Create `models/ig_api.py`; Test `tests/test_instagram_send.py`.

**Interfaces:**
- `ig_api.split_utf8(text: str, limit: int = 1000) -> list[str]` (tách theo dòng/khoảng trắng, không vượt byte, không cắt ký tự).
- `ig_api.send_image(token, page_id, igsid, filename, content, mimetype) -> dict` (upload rồi gửi theo Global Constraints; tên file ASCII).
- `_livestream_private_reply` (platform instagram): phiên của comment phải `live`, không thì `UserError`; gửi phần đầu của `split_utf8(body)` bằng `recipient.comment_id`; trả `recipient_id`.
- `_livestream_send_message` (instagram): cửa sổ phải `open` (như Facebook); gửi từng phần văn bản, rồi ảnh.
- [ ] Test (`test_private_reply_sets_igsid`, `test_private_reply_after_live_ended_refused`, `test_long_message_split_utf8`, `test_send_message_outside_window_raises`, `test_send_image_uploads_then_sends`) → FAIL → cài đặt → PASS. Commit `feat(livestream_instagram): private replies and Direct messages`.

### Task 3: Cron phát hiện live & kéo bù bình luận
**Files:** Modify `models/livestream_session.py`; Create `data/ir_cron.xml`; Test `tests/test_instagram_cron.py`.

**Interfaces:** `livestream.session._ig_cron_sync()`: với mỗi account instagram có token → `live_media`; media trả về → `_ig_upsert_live(..., True)` rồi kéo `ordered_comments` (mỗi dòng một savepoint, bỏ comment của shop); phiên IG đang `live` mà media không còn → `ended`. Cron 1 phút.
- [ ] Test (`test_cron_creates_live_session_and_pulls_comments`, `test_cron_ends_missing_live`, `test_cron_bad_row_does_not_lose_batch`) → FAIL → cài đặt → PASS. Commit `feat(livestream_instagram): live discovery and comment pull cron`.

### Task 4: Badge nền tảng trên màn hình điều hành
**Files:** Modify `livestream_sale/models/livestream_console.py`, `models/livestream_comment.py` (`_console_format` thêm `platform`), `static/src/console/{console.xml,console.scss}`; Test `livestream_sale/tests/test_console.py`.

**Interfaces:** `load()` trả `sessions[].platform`, `session.platform`; `comment._console_format()["platform"]`. UI: badge `FB` (xanh dương) / `IG` (gradient hồng-cam) / `SIM` ở dropdown phiên, mỗi bình luận và tiêu đề khung chat; phiên IG đang live hiện dòng nhắc "Instagram: chỉ nhắn riêng được trong lúc live".
- [ ] Test (`test_console_platform_fields`) → FAIL → cài đặt → PASS; kiểm tra bundle CSS/JS biên dịch. Commit `feat(livestream_sale): platform badges in console`.

### Task 5: Tài liệu, bản dịch, chạy toàn bộ
- [ ] README: mục Instagram (liên kết IG với Page, quyền, webhook object Instagram + field `live_comments`, `messages`, tài khoản công khai, live từ app hoặc Live Producer).
- [ ] Export/dịch `livestream_instagram/i18n/vi.po` + chuỗi mới của `livestream_sale`.
- [ ] Chạy toàn bộ test 4 module → PASS; cài vào `odoo20_livestream`. Commit `docs(livestream_instagram): setup guide and translations`.
