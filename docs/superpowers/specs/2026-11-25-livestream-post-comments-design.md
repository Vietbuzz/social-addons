# Bình luận bài viết (Facebook + Instagram) — thiết kế ngắn

Ngày: 2026-11-25 · Mở rộng `2026-11-22-livestream-sale-design.md` và `2026-11-24-livestream-instagram-design.md`

## Mục đích
Giống Pancake: ngoài bình luận live, bắt cả bình luận trên bài viết bán hàng thường. Chủ shop: "mỗi bài đối xử như 1 livestream" — khách hỏi còn hàng không, trợ lý trao đổi, có thể chốt mặt hàng khác bằng cách tạo đơn tay, hoặc gắn mã tag với sản phẩm có sẵn.

## Mục tiêu / Ngoài phạm vi / Không được để xảy ra
- Mục tiêu: bình luận bài viết Facebook Page và Instagram (bài, reels) vào màn hình điều hành; mỗi bài là một phiên; mã tag tuỳ chọn; lên đơn với bất kỳ sản phẩm nào; không bỏ sót bình luận ở bài khác đang không mở.
- Ngoài phạm vi (để sau): ẩn bình luận có SĐT, trả lời công khai/like/xoá bình luận, tự động trả lời, xuất bình luận, đồng bộ bình luận cũ trước khi bật tính năng.
- Không được: bình luận bài viết làm sai lệch phiên live đang chạy; trợ lý bỏ sót bình luận vì đang xem bài khác.

## Cách làm
- **Đã chọn: dùng chung `livestream.session`** với field mới `source_type` (`live` / `post`). Toàn bộ luồng chat, đơn, cọc, màn hình dùng lại.
- Đã loại: model `livestream.post` riêng — lặp lại toàn bộ luồng, không lợi gì.

## Thiết kế
- `livestream.session`: thêm `source_type` (mặc định `live`), `permalink_url`, `last_comment_at` (cập nhật khi có bình luận mới). Bài viết tạo ra ở trạng thái `live` (hiển thị "Đang mở"); quản lý bấm "Kết thúc" để ngừng nhận bình luận vào bài đó.
- Facebook: bình luận `feed` trên bài chưa có phiên → tạo phiên `post` (tên = 60 ký tự đầu nội dung bài lấy qua `GET /{post_id}?fields=message,permalink_url`, lỗi thì "Bài viết dd/mm"). Bỏ qua bình luận của chính Page và bình luận trả lời của Page. Video live vẫn đi theo phiên live như cũ.
- Instagram: đăng ký thêm field `comments`; bình luận trên media không phải live → phiên `post` (tên lấy từ `caption`, `permalink`). Quy tắc "chỉ nhắn riêng trong lúc live" chỉ áp dụng cho phiên `live`; bài viết theo giới hạn 7 ngày của Meta (Meta tự từ chối nếu quá hạn, lỗi hiện rõ cho trợ lý).
- Màn hình điều hành:
  - Ô chọn nguồn có 3 nhóm: **"Tất cả nguồn đang mở"** (mặc định, gộp bình luận mới nhất của mọi phiên đang mở), **Live**, **Bài viết** (sắp theo `last_comment_at`); badge LIVE / BÀI VIẾT và FB / IG trên từng bình luận và tên nguồn.
  - Bus đẩy bình luận của mọi phiên; ở chế độ "Tất cả" chúng xuất hiện ngay; ở chế độ một phiên, ô chọn nguồn hiện số bình luận mới của các nguồn khác.
  - Khung đơn: thêm ô **tìm sản phẩm bất kỳ** (theo tên/mã) bên cạnh "thêm theo mã tag", để chốt mặt hàng khác.
  - Liên kết "Mở bài viết" (permalink) trên khung hội thoại.
- Mã tag cho bài viết: thêm tay trong form phiên như live (tuỳ chọn).

## Để người xây quyết định
- Giới hạn số phiên/bình luận tải ở chế độ "Tất cả" (đề xuất 200 bình luận mới nhất của tối đa 50 phiên đang mở).
- Payload `comments` của Instagram: cùng dạng `live_comments` (`value.media.id`, `comment_id`, `from`, `text`), kiểm tra lại khi viết test.
