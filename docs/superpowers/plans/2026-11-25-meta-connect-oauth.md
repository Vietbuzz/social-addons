# Meta Connect (OAuth) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nút "Kết nối với Facebook" lấy Page token dài hạn cho Page + IG, và cảnh báo khi token mất hiệu lực.

**Architecture:** Trong `livestream_facebook`: model hàm `meta_oauth` (URL, state HMAC, đổi token), controller callback, wizard chọn Page; field sức khoẻ token + cron trên `livestream.account`; `livestream_sale` console trả `token_alerts` (field `token_state` khai báo ở lõi để lõi đọc được).

**Tech Stack:** Odoo 20, Graph API v27.0, OWL 3.

**Spec:** `docs/superpowers/specs/2026-11-25-meta-connect-oauth-design.md`

## Global Constraints
- `redirect_uri = {web.base.url}/livestream/facebook/oauth/callback`; dialog `https://www.facebook.com/v27.0/dialog/oauth`.
- `state` = payload `{"a": account_id, "u": uid, "t": unix}` + HMAC (`odoo.tools.misc.hmac(env(su=True), "livestream-meta-oauth", payload)`), hết hạn 900 s.
- Token/secret không bao giờ xuất hiện trong URL trả về trình duyệt, log hay message.
- Chỉ `livestream_sale.group_livestream_manager` dùng nút/callback/wizard.

## Review Focus
1. `state` sai/hết hạn/thuộc user khác → 403, không đổi token. → `test_callback_rejects_bad_state` (Task 1).
2. Meta trả lỗi khi đổi code (code đã dùng) → báo lỗi rõ, không tạo wizard. → `test_callback_exchange_error` (Task 1).
3. Page có IG liên kết nhưng tài khoản IG đã tồn tại → cập nhật, không tạo trùng. → `test_wizard_updates_existing_ig` (Task 2).
4. Cron kiểm tra: một tài khoản lỗi mạng không làm hỏng các tài khoản khác; lỗi mạng ≠ token hỏng. → `test_health_network_error_not_invalid` (Task 3).
5. Tài khoản simulator/không token bị bỏ qua khi kiểm tra. → `test_health_skips_simulator` (Task 3).

---
### Task 1: OAuth URL, state, callback, đổi token
Files: `livestream_facebook/models/meta_oauth.py` (AbstractModel `livestream.meta.oauth`), `controllers/oauth.py`, `models/livestream_account.py` (`action_meta_connect`), tests `tests/test_meta_oauth.py`.
Interfaces: `livestream.meta.oauth._make_state(account) -> str`, `_check_state(state) -> account` (raise `AccessDenied`), `_authorize_url(account) -> str`, `_exchange_code(account, code) -> long_lived_user_token`, `_list_pages(account, user_token) -> list[{page_id, name, token, ig_id, ig_username}]`. `account.action_meta_connect() -> act_url`. Route `GET /livestream/facebook/oauth/callback` → tạo wizard → redirect `/odoo/action-livestream_facebook.action_meta_connect_wizard?...` (hoặc `/odoo/livestream.meta.connect.wizard/<id>`).
- [ ] Tests (`test_authorize_url_contains_state_and_scopes`, `test_callback_creates_wizard_with_pages`, `test_callback_rejects_bad_state`, `test_callback_exchange_error`) → FAIL → implement → PASS → commit.

### Task 2: Wizard chọn Page
Files: `wizard/meta_connect_wizard.py` + view, ACL. Interfaces: `livestream.meta.connect.wizard` (`source_account_id`, `user_token` groups manager, `line_ids`), line (`page_id`, `name`, `page_token`, `ig_id`, `ig_username`, `selected`). `action_apply()` tạo/cập nhật account FB + IG, `token_state='valid'`.
- [ ] Tests (`test_wizard_creates_fb_and_ig_accounts`, `test_wizard_updates_existing_ig`, `test_wizard_unselected_page_untouched`) → FAIL → implement → PASS → commit.

### Task 3: Sức khoẻ token + cảnh báo
Files: `livestream_sale/models/livestream_account.py` (fields `token_state`, `token_checked_at`, `token_error`), `livestream_facebook/models/livestream_account.py` (`_check_token_health()`, `action_check_token`, cron hourly), `livestream_sale/models/livestream_console.py` (`token_alerts`), console UI banner, account views badge.
- [ ] Tests (`test_health_marks_invalid`, `test_health_marks_valid`, `test_health_network_error_not_invalid`, `test_health_skips_simulator`, `test_console_token_alerts`) → FAIL → implement → PASS → commit.

### Task 4: README, dịch, cài đặt
- [ ] README mục Kết nối với Facebook (Valid OAuth Redirect URIs), vi.po (gộp), toàn bộ test, cài `odoo20_livestream`. Commit.
