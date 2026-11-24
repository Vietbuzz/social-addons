# Livestream Sale — Instagram Live (thiết kế ngắn)

Ngày: 2026-11-24 · Mở rộng của `2026-11-22-livestream-sale-design.md`

## Mục đích
Shop có nhiều follower trên Instagram và live trên Instagram; Page Facebook tương ứng ít follow. Cần đưa bình luận Instagram Live vào cùng màn hình 3 cột, nhắn riêng qua Instagram Direct, chốt đơn, thu cọc SePay như Facebook.

## Mục tiêu / Ngoài phạm vi / Không được để xảy ra
- Mục tiêu: bình luận Instagram Live real-time (webhook `live_comments` + cron kéo bù), private reply trong lúc live, Direct 2 chiều (24h), gửi yêu cầu cọc + ảnh QR, hiển thị rõ nền tảng (FB/IG) trên màn hình.
- Ngoài phạm vi: bình luận trên bài đăng/reels thường, story mentions, đăng nhập Instagram riêng (cách B), tag HUMAN_AGENT.
- Không được: gửi tin cho khách IG ngoài quy tắc của Meta rồi im lặng thất bại; nhầm khách IG với khách FB.

## Ràng buộc (theo tài liệu Meta, 11/2026)
- Bình luận live chỉ được báo trong lúc đang phát; **private reply chỉ gửi được trong lúc live** (Meta từ chối khi live đã tắt).
- Mỗi bình luận 1 private reply; khách trả lời → cửa sổ 24h. Tin nhắn tối đa 1000 byte UTF-8.
- Tài khoản IG phải là Business/Creator, **công khai**, liên kết với Page. Quyền `instagram_basic`, `instagram_manage_comments`, `instagram_manage_messages`, `pages_read_engagement`, `pages_manage_metadata`, `pages_show_list`; `live_comments` cần Advanced Access (App Review khi chạy thật).
- Page Facebook chỉ là cầu nối kỹ thuật (token, quyền, Messenger-style API): **không cần follower, không cần live trên Facebook**.

## Cách làm
- **Đã chọn: A — Instagram qua Facebook Login** (dùng chung Meta App + Page token).
- Đã loại: B — Instagram Login riêng (thêm bộ token, không lợi gì cho shop đã có Page).

## Thiết kế
- Module mới `livestream_instagram` (phụ thuộc `livestream_facebook` để dùng lại `graph_api`, kiểm tra chữ ký, các field Meta App trên tài khoản kết nối).
- `livestream.account` thêm platform `instagram`: `external_id` = IG business account id, `fb_page_id` = Page liên kết, token = Page token, dùng chung App Secret/Verify token.
- Phiên live: cron 1 phút gọi `GET /{ig-user-id}/live_media` → tạo/đặt `live` cho media đang phát; media không còn trong danh sách → `ended`. Kéo bù bình luận `GET /{media-id}/comments`.
- Webhook `POST /livestream/instagram/webhook` (object `instagram`): `live_comments` → `_ingest` (bỏ qua bình luận của chính shop); `messages` (IGSID) → `_receive_message`, nối khách đang chờ theo `username` nếu private reply không trả `recipient_id`.
- Gửi: private reply `POST /{page-id}/messages` với `recipient.comment_id` (từ chối rõ ràng nếu phiên đã kết thúc); tin thường gửi tới IGSID trong cửa sổ 24h; tin dài hơn 1000 byte được tách nhiều tin; ảnh QR gửi dạng attachment.
- Màn hình 3 cột: badge nền tảng (FB/IG) ở danh sách phiên, ở bình luận và ở khung chat; với IG đang live hiện nhắc "chỉ nhắn riêng được trong lúc live".
- Test: như `livestream_facebook` (payload mẫu, chữ ký, chống trùng, private reply khi live/đã tắt, tách tin dài, cron live_media).

## Để người xây quyết định
- Cách upload ảnh QR cho Instagram (attachment upload API hay URL công khai qua tunnel) — kiểm tra tài liệu lúc viết.
- Payload mẫu thật của `live_comments` (trang ví dụ webhook của Meta) trước khi viết test.
