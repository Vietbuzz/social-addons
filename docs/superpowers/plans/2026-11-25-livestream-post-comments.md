# Post Comments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bắt bình luận bài viết Facebook/Instagram như một phiên live, xem gộp mọi nguồn đang mở, và tạo đơn với sản phẩm bất kỳ.

**Architecture:** `livestream.session` thêm `source_type` (`live`/`post`); connector tạo phiên `post` khi có bình luận trên bài chưa biết. Console có chế độ `"all"` gộp các phiên đang mở (`state = live`), và API tìm sản phẩm.

**Tech Stack:** Odoo 20, Graph API v27.0, OWL 3.

**Spec:** `docs/superpowers/specs/2026-11-25-livestream-post-comments-design.md`

## Global Constraints
- Phiên bài viết: `source_type="post"`, tạo ở `state="live"` ("Đang mở"); tên tối đa 60 ký tự từ nội dung bài, fallback `"Bài viết dd/mm"`.
- Chế độ tất cả: `load("all")`, tối đa 200 bình luận mới nhất của tối đa 50 phiên đang mở (sắp theo `last_comment_at`).
- Bỏ qua bình luận của chính Page/IG account. Quy tắc "chỉ nhắn riêng trong lúc live" (Instagram) chỉ áp dụng cho `source_type="live"`.
- Lệnh test: `t.sh <mods> <tags>` như trước, mods = 4 module livestream.

## Review Focus
1. Bình luận bài viết trên Page đang có live → không lẫn vào phiên live. → `test_post_comment_creates_post_session_not_live` (Task 2).
2. Không đọc được nội dung bài (lỗi Graph) → vẫn tạo phiên với tên dự phòng, không mất bình luận. → `test_post_name_fallback_on_graph_error` (Task 2).
3. Instagram bình luận bài viết khi phiên bài đã "kết thúc" → không tạo phiên mới trùng media, bỏ qua. → `test_ig_comment_on_ended_post_ignored` (Task 3).
4. Chế độ "Tất cả": bình luận của phiên đã kết thúc không hiện; không vượt giới hạn. → `test_load_all_only_open_sessions` (Task 1).
5. Tìm sản phẩm không trả về sản phẩm không bán được (`sale_ok=False`) hoặc công ty khác. → `test_search_products_sale_ok_only` (Task 1).

---

### Task 1: Lõi — source_type, last_comment_at, chế độ "all", tìm sản phẩm
**Files:** `livestream_sale/models/{livestream_session,livestream_comment,livestream_console}.py`, `views/livestream_session_views.xml`; Test `tests/test_post_sessions.py`.
**Interfaces:**
- `livestream.session`: `source_type` Selection `[("live","Live"),("post","Post")]` required default `live`; `permalink_url` Char; `last_comment_at` Datetime index. `_get_or_create_post(account, external_post_id: str, name: str, permalink: str|None) -> session` (tìm theo `external_post_id`, kể cả đã kết thúc; tạo mới nếu chưa có).
- `livestream.comment._ingest` cập nhật `session.last_comment_at`; `_console_format()` thêm `source_type`, `session_name`.
- `livestream.console.load(session_id: int | "all" | False)`: `False` → `"all"`. Chế độ all trả `session = {"id": "all", "name": ..., "account_ids": [...], "tags": []}`, `sessions[]` có `source_type`, `last_comment_at`; bình luận như Global Constraints; giao dịch của mọi provider của các account liên quan.
- `load_more_comments(session_id: int | "all", before_id, tag_code)`.
- `order_panel(comment_id)` thêm `"tags"` (mã tag của phiên của bình luận) và `"permalink_url"`.
- `search_products(query: str, limit: int = 20) -> list[{product_id, product_name, price_unit}]` (`sale_ok`, công ty hiện tại hoặc dùng chung).
- [ ] Test (`test_post_session_get_or_create`, `test_ingest_updates_last_comment_at`, `test_load_all_only_open_sessions`, `test_load_default_is_all`, `test_order_panel_tags_from_comment_session`, `test_search_products_sale_ok_only`) → FAIL → cài đặt → PASS (cả suite livestream_sale). Commit.

### Task 2: Facebook — bình luận bài viết
**Files:** `livestream_facebook/models/{livestream_webhook_event,livestream_session}.py`; Test `tests/test_facebook_posts.py`.
**Interfaces:** `_fb_feed`: không khớp phiên live → `_fb_post_session(account, post_id) -> session` (gọi `GET {post_id}?fields=message,permalink_url`, lỗi → tên dự phòng) → `_ingest`. Bỏ qua bình luận mà `from.id == page id`. Phiên `post` đã kết thúc → bỏ qua bình luận.
- [ ] Test (`test_post_comment_creates_post_session_not_live`, `test_post_name_fallback_on_graph_error`, `test_second_comment_reuses_post_session`, `test_comment_on_ended_post_ignored`) → FAIL → cài đặt → PASS. Commit.

### Task 3: Instagram — bình luận bài viết
**Files:** `livestream_instagram/models/{livestream_webhook_event,livestream_account}.py`; Test `tests/test_instagram_posts.py`.
**Interfaces:** field `comments` → `_ig_post_comment(account, value)`: `media_product_type == "LIVE"` → đường live cũ; còn lại → phiên `post` (tên từ `GET {media_id}?fields=caption,permalink`). `_livestream_private_reply` chỉ chặn khi `source_type == "live"` và phiên không còn live.
- [ ] Test (`test_ig_post_comment_creates_post_session`, `test_ig_comment_on_ended_post_ignored`, `test_ig_private_reply_on_post_allowed_after_end_of_lives`) → FAIL → cài đặt → PASS. Commit.

### Task 4: Màn hình điều hành
**Files:** `livestream_sale/static/src/console/{console_model.js,console_action.js,comment_feed.js,order_panel.js,conversation_panel.js,console.xml,console.scss}`.
- Ô chọn nguồn: "Tất cả nguồn đang mở" + optgroup Live / Bài viết; badge số bình luận mới chưa xem theo phiên (`state.unseen[sessionId]`) khi đang xem một phiên.
- Chế độ all: nhận bus của mọi account trong `session.account_ids`; mỗi bình luận hiện badge LIVE/BÀI VIẾT + tên nguồn.
- Khung đơn: chọn mã tag dùng `panel.tags`; ô tìm sản phẩm (gõ ≥ 2 ký tự → `search_products`) để thêm dòng.
- Khung chat: liên kết "Mở bài viết" khi có `permalink_url`; nhắc IG chỉ khi phiên của bình luận là live IG đang chạy.
- Giả lập bình luận ở chế độ all dùng phiên live/bài đầu tiên đang mở.
- [ ] Kiểm tra cú pháp JS/XML + bundle biên dịch; chạy suite. Commit.

### Task 5: Tài liệu, dịch, cài đặt
- [ ] README: mục bình luận bài viết (đăng ký field `feed` Page, `comments` Instagram). vi.po (gộp, không làm mất bản dịch cũ). Chạy toàn bộ test 4 module; cài vào `odoo20_livestream`. Commit.
