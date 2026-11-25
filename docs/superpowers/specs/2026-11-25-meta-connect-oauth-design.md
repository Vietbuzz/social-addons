# Kết nối với Facebook (OAuth) + kiểm tra sức khoẻ token — thiết kế ngắn

Ngày: 2026-11-25 · Mở rộng `livestream_facebook` / `livestream_instagram`

## Mục đích
Token ngắn hạn dán tay đã hết hạn và Odoo âm thầm ngừng nhận bình luận. Chủ shop chọn: một nút "Kết nối với Facebook" lấy Page token dài hạn tự động cho Page và Instagram liên kết, cùng cơ chế phát hiện token mất hiệu lực để kết nối lại bằng một cú bấm. (Không thể "tự lấy token khi hết hạn" vì Meta luôn cần người dùng đăng nhập.)

## Mục tiêu / Ngoài phạm vi / Không được để xảy ra
- Mục tiêu: nút OAuth trên tài khoản kết nối → chọn Page (và IG liên kết) → Odoo lưu Page token dài hạn; cron kiểm tra token mỗi giờ; cảnh báo trên tài khoản và trên màn hình điều hành khi cần kết nối lại; vẫn cho nhập token tay (System User token).
- Ngoài phạm vi: Facebook Login for Business (config_id), tự tạo System User, quản lý Meta App từ Odoo.
- Không được: callback OAuth bị giả mạo (CSRF) gắn token lạ vào tài khoản; lộ token/App Secret ra trình duyệt hoặc log; token hỏng mà không ai biết.

## Cách làm
- Đã chọn: OAuth chuẩn (Manual Login Flow) qua `https://www.facebook.com/v27.0/dialog/oauth` → `GET /oauth/access_token` (code → user token) → đổi `fb_exchange_token` (user token dài hạn) → `GET /me/accounts?fields=id,name,access_token,instagram_business_account{id,username}` (Page token từ user token dài hạn không hết hạn theo thời gian).
- Đã loại: dán user token rồi đổi (chủ shop chọn OAuth); System User tự động (cần Business Manager).

## Thiết kế
- Nút **"Kết nối với Facebook"** trên form tài khoản (platform facebook/instagram, quản lý): cần App ID + App Secret trên tài khoản đó; mở dialog OAuth với `state` ký HMAC (account id, user id, thời điểm; hết hạn sau 15 phút) và `redirect_uri = {web.base.url}/livestream/facebook/oauth/callback`.
- Callback (`auth="user"`, chỉ quản lý): kiểm tra `state`, đổi code → token dài hạn → danh sách Page; tạo wizard `livestream.meta.connect.wizard` (giữ user token dài hạn trong bản ghi tạm, chỉ group quản lý đọc) với một dòng mỗi Page (tick sẵn Page đã có tài khoản), rồi chuyển hướng về form wizard trong Odoo.
- Wizard "Áp dụng": với mỗi Page được chọn → tạo/cập nhật tài khoản `facebook` (`external_id`=Page ID, token, App ID/Secret, verify token); nếu Page có IG Business → tạo/cập nhật tài khoản `instagram` (`external_id`=IG id, `fb_page_id`, cùng token). Đặt trạng thái token = hợp lệ.
- Sức khoẻ token: field `token_state` (`unknown`/`valid`/`invalid`), `token_checked_at`, `token_error`. Cron mỗi giờ gọi `GET /debug_token?input_token=<token>&access_token=<app_id>|<app_secret>`; `is_valid=false` hoặc lỗi 190 → `invalid`. Nút "Kiểm tra token" chạy ngay.
- Cảnh báo: form/list tài khoản có badge đỏ "Cần kết nối lại"; `livestream.console.load` trả `token_alerts` (tài khoản đang có phiên/không hợp lệ) và màn hình điều hành hiện dải đỏ kèm tên Page.
- Meta App: thêm `{web.base.url}/livestream/facebook/oauth/callback` vào "Valid OAuth Redirect URIs" (tunnel nhanh đổi URL thì phải cập nhật).

## Để người xây quyết định
- Danh sách scope: `pages_show_list, pages_read_engagement, pages_manage_metadata, pages_messaging, pages_read_user_content, instagram_basic, instagram_manage_comments, instagram_manage_messages, business_management`.
