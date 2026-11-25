# Livestream Sale — Hướng dẫn cài đặt & test

Bộ 3 module cho Odoo 20:

| Module | Vai trò |
|---|---|
| `livestream_sale` | Lõi: phiên live, mã tag, bình luận, chat (Discuss), đơn hàng, cọc, khớp tiền, Bảng điều hành 3 cột, bộ giả lập |
| `livestream_sepay` | Nhận biến động số dư từ SePay (webhook + cron kéo bù 5 phút/lần) |
| `livestream_facebook` | Bình luận live trên Facebook Page, private reply, Messenger 2 chiều |
| `livestream_instagram` | Bình luận Instagram Live, private reply trong lúc live, Instagram Direct (qua Page liên kết) |

## 1. Cài đặt

```bash
cd "/Users/buzz/odoo 20"
docker compose up -d
# Tạo DB (tên phải bắt đầu bằng odoo20_ vì dbfilter), rồi cài module:
docker compose run --rm odoo odoo -d odoo20_shop -i livestream_sale,livestream_sepay,livestream_facebook,livestream_instagram --stop-after-init
```

Phân quyền (Thiết lập › Người dùng › tab Livestream):
- **Trợ lý livestream**: xem bình luận, chat, lên đơn, khớp tay giao dịch.
- **Quản lý livestream**: cấu hình, gỡ khớp (bắt buộc ghi lý do), bỏ qua giao dịch, xác nhận đơn khi chưa đủ cọc (có ghi log).

## 2. Ngân hàng, VietQR, tiền cọc

1. **Kế toán › Cấu hình › Sổ nhật ký**: mở sổ Ngân hàng và gắn **Tài khoản ngân hàng** của shop. Trên tài khoản ngân hàng đó nhập:
   - Ngân hàng có **BIC** là mã BIN Napas (VD Vietcombank `970436`)
   - **Loại QR** = *Bank Account*, **Giá trị proxy** = số tài khoản
   - Bật "Include reference"
   - Đối tác chủ tài khoản phải có thành phố
2. **Kế toán › Cấu hình › Nhà cung cấp thanh toán › SePay**:
   - Bật (Active), chọn **Sổ nhật ký** = sổ Ngân hàng ở bước 1.
   - Tab Cấu hình: nhập **Webhook API Key** (tự đặt), **API Token** (lấy ở my.sepay.vn › Cấu hình công ty › API Access), **Số tài khoản**.
   - Sao chép **Sepay Webhook Url**.
3. **Livestream › Cấu hình › Tài khoản kết nối**: chọn **Nhà cung cấp thu cọc** = SePay, rồi bấm **"Ghi tiền cọc thẳng vào tài khoản ngân hàng"**. Bản Community không có công cụ đối soát sao kê, nên tiền cọc được ghi thẳng vào tài khoản ngân hàng.
4. Trên **my.sepay.vn**:
   - Tạo webhook: URL = Sepay Webhook Url, xác thực **API Key** = key ở bước 2, chỉ gửi **tiền vào**.
   - Mục *Cấu hình công ty › Nhận diện mã thanh toán*: thêm tiền tố **`LS`**. Mã chuyển khoản của mỗi đơn có dạng `LS000123`.

Tham số hệ thống (Thiết lập › Kỹ thuật › Tham số):
- `livestream_sale.default_deposit_amount`: tiền cọc mặc định. Nếu không đặt thì lấy 30% giá trị đơn.
- `livestream_sale.deposit_message_template`: mẫu tin nhắn yêu cầu cọc. Dùng được các biến `{order} {amount} {account_number} {bank} {holder} {ref}`.
- `livestream_sale.simulator_enabled` = `True`: cho Trợ lý dùng nút giả lập. Quản lý luôn dùng được.

## 3. Facebook (Meta App riêng của shop)

Quyền của Pancake không dùng lại được, shop cần **Meta App riêng**.

1. Tạo app tại developers.facebook.com (loại *Business*) và để ở **Development mode** trong lúc test.
2. Thêm sản phẩm **Webhooks** và **Messenger**.
3. Lấy **Page access token dài hạn** cho Page, cần các quyền `pages_read_engagement`, `pages_manage_metadata`, `pages_messaging`, `pages_read_user_content`.
4. **Livestream › Cấu hình › Tài khoản kết nối › Tạo mới**:
   - Nền tảng *Facebook Page*, External ID = **Page ID**, Access Token = Page token.
   - Nhập App ID và App Secret.
   - Sao chép **Webhook URL** và **Verify Token** sang mục cấu hình Webhooks của app (object *Page*, các field `feed`, `live_videos`, `messages`).
5. Bấm **"Đăng ký webhook cho Page"**.
6. Khi bắt đầu live, bấm **"Đồng bộ video live"** (hoặc chờ webhook `live_videos`) để phiên live xuất hiện. Sau đó nhập **mã tag → sản phẩm** cho phiên.

Lưu ý về giới hạn của Meta:
- Mỗi bình luận chỉ gửi được **1 tin nhắn riêng** (trong 7 ngày). Khách trả lời thì mới mở **cửa sổ 24h**. Bảng điều hành hiển thị trạng thái này.
- Khi app ở Development mode, chỉ tài khoản có vai trò trong app (Admin/Developer/Tester) mới bình luận và nhắn tin được. Muốn bán thật thì phải qua **App Review**.

## 3a. Kết nối với Facebook (khuyến nghị, thay cho dán token)

1. Trong Meta App › **Facebook Login** › Settings › **Valid OAuth Redirect URIs**, thêm `https://<URL tunnel hoặc domain>/livestream/facebook/oauth/callback`. URL này phải trùng với tham số `web.base.url` của Odoo. Tunnel nhanh `trycloudflare.com` đổi URL mỗi lần chạy, nên mỗi lần đổi phải cập nhật lại cả hai chỗ.
2. Tạo một tài khoản kết nối (Facebook hoặc Instagram), nhập **App ID** và **App Secret**, rồi bấm **"Kết nối với Facebook"**.
3. Đăng nhập Facebook và đồng ý cấp quyền. Odoo hiện danh sách Page bạn quản lý (kèm Instagram liên kết, nếu có). Tick các Page cần dùng rồi bấm **"Kết nối các Page đã chọn"**.
4. Odoo tự tạo hoặc cập nhật tài khoản Facebook và Instagram với **Page token dài hạn**. Page token loại này không hết hạn theo thời gian, nhưng sẽ mất hiệu lực nếu người kết nối đổi mật khẩu, bị gỡ quyền quản trị Page, hoặc thu hồi quyền của app.
5. Bấm **"Đăng ký webhook cho Page"** trên từng tài khoản.

Odoo kiểm tra token **mỗi giờ**. Khi token mất hiệu lực:
- tài khoản chuyển sang trạng thái đỏ **"Cần kết nối lại"**;
- màn hình điều hành hiện dải cảnh báo đỏ.

Lúc đó chỉ cần bấm lại "Kết nối với Facebook". Muốn kiểm tra ngay thì bấm **"Kiểm tra token"**. Ô Access Token vẫn nhập tay được, ví dụ để dán System User token từ Business Manager.

## 3b. Instagram Live (qua Facebook Page)

Page Facebook chỉ là cầu nối kỹ thuật, **không cần follower, không cần live trên Facebook**. Buổi live và người bình luận đều ở Instagram.

1. Tài khoản Instagram phải là **Business/Creator**, để **công khai**, và **liên kết với Page** (Instagram › Cài đặt › Tài khoản đã liên kết, hoặc Meta Business Suite).
2. Trong Meta App (cùng app với Facebook): thêm quyền `instagram_basic`, `instagram_manage_comments`, `instagram_manage_messages`, `pages_messaging`, `pages_read_engagement`, `pages_manage_metadata`, `pages_show_list`. `live_comments` cần **Advanced Access**, nên khi chạy thật phải đưa vào App Review.
3. Webhooks › object **Instagram**: Callback URL lấy ở ô **Ig Webhook Url** trên tài khoản kết nối, dùng cùng Verify Token. Đăng ký field `live_comments` và `messages`.
4. **Livestream › Cấu hình › Tài khoản kết nối › Tạo mới**:
   - Nền tảng *Instagram*.
   - External ID = **ID tài khoản Instagram Business** (`GET /{page-id}?fields=instagram_business_account`).
   - Linked Facebook Page ID = ID của Page.
   - Access Token = Page token. Nhập App Secret.
5. Bắt đầu live trên app Instagram (hoặc Live Producer). Trong vòng 1 phút, cron sẽ tự tạo phiên live (badge **IG**). Bạn nhập **mã tag → sản phẩm** cho phiên này. Bình luận đổ về bảng điều hành như Facebook.

Lưu ý riêng của Instagram:
- **Chỉ nhắn riêng (private reply) được trong lúc đang live.** Live tắt thì chỉ nhắn được cho khách đã nhắn Direct cho shop trong 24h qua. Màn hình có dòng nhắc màu đỏ.
- Mỗi tin tối đa 1000 byte, tin dài được tự tách. Ảnh QR được tải lên Meta rồi gửi kèm.

## 3c. Bình luận bài viết (Facebook + Instagram)

Mỗi bài viết bán hàng được xử lý như một buổi live:
- Bình luận đầu tiên trên một bài sẽ tự tạo phiên **Bài viết**, đặt tên theo nội dung bài và có liên kết "Mở bài viết".
- Mã tag là tuỳ chọn, nhập trong form phiên như với live.
- Trợ lý có thể chốt **bất kỳ sản phẩm nào** bằng ô "Tìm sản phẩm" trong khung đơn.

Cấu hình webhook:
- **Facebook**: không cần thêm gì, field `feed` của Page đã gửi cả bình luận bài viết.
- **Instagram**: đăng ký thêm field **`comments`** trong mục Webhooks › Instagram của Meta App.

Trên màn hình điều hành:
- Mặc định là **"★ Tất cả nguồn đang mở"**, gộp bình luận mới của mọi live và bài viết đang mở.
- Mỗi bình luận có badge **LIVE / POST** và tên nguồn.
- Khi chọn xem một nguồn cụ thể, ô chọn nguồn hiện **(+N)** cho các nguồn khác có bình luận mới.
- Quản lý bấm **Kết thúc** trên phiên bài viết để ngừng nhận bình luận của bài đó. Với khách đã bình luận trước đó, trợ lý vẫn nhắn riêng được trong giới hạn 7 ngày của Meta.

## 4. Chạy local: cần tunnel để nhận webhook

Meta và SePay không gọi được vào `localhost`. Có hai cách:

```bash
cloudflared tunnel --url http://localhost:8069
```

Đặt `proxy_mode = True` trong `config/odoo.conf` khi chạy sau tunnel. Đặt tham số `web.base.url` = URL tunnel, rồi dùng URL đó cho webhook.

Không có tunnel thì vẫn chạy được, chỉ chậm hơn: cron kéo bình luận Facebook mỗi 1 phút (khi phiên đang live) và kéo giao dịch SePay mỗi 5 phút.

## 5. Phát live để test (không cần camera)

1. Vào Live Producer của **Page test**, chọn *Streaming software*, lấy Stream key.
2. Phát lặp một file video:
   ```bash
   ffmpeg -re -stream_loop -1 -i sample.mp4 -c:v libx264 -preset veryfast -b:v 2500k -c:a aac -f flv "rtmps://live-api-s.facebook.com:443/rtmp/<STREAM_KEY>"
   ```
   Có thể dùng OBS thay cho ffmpeg.

## 6. Kịch bản kiểm thử từ đầu đến cuối

1. Mở **Livestream › Bảng điều hành** trên 2 tab trình duyệt.
2. Từ tài khoản tester, bình luận `69 x2` dưới video live (hoặc bấm **Giả lập › Comment**). Bình luận xuất hiện real-time ở cột trái trên cả 2 tab.
3. Lọc tag `69`, bấm **Mở hội thoại & Chốt**. Cột giữa mở chat, có bình luận gốc ở trên cùng.
4. Nhắn "Chào anh…". Tin này đi bằng private reply.
5. Tester trả lời trên Messenger (hoặc bấm **Giả lập › Reply**). Badge chuyển sang "Cửa sổ chat còn …".
6. Cột phải: sản phẩm đã điền sẵn SL 2. Nhập SĐT, địa chỉ, tiền cọc, bấm **Tạo đơn hàng**. Mã QR và mã CK `LS…` hiện ra.
7. Bấm **Gửi yêu cầu cọc & Mã QR**. Khách nhận tin nhắn có số tài khoản, nội dung chuyển khoản và ảnh QR.
8. Chuyển thật 2.000đ với đúng nội dung `LS…` (hoặc **Giả lập › Transfer**). Giao dịch hiện màu xanh, đơn tự **xác nhận** khi đủ cọc, có `account.payment` trong sổ ngân hàng.
9. Chuyển một khoản ghi sai nội dung. Giao dịch hiện màu vàng, bấm **Gắn vào <đơn đang mở>** hoặc nút gợi ý.
10. Quản lý mở giao dịch (Livestream › Tiền chuyển khoản), bấm **Gỡ khớp**, nhập lý do. Payment bị hủy và giao dịch có thể được khớp lại.

## 7. Chạy song song với Pancake

Page có thể nối cùng lúc với Pancake và app của shop: cả hai đều nhận bình luận và tin nhắn. Trong giai đoạn chuyển tiếp, shop cần thống nhất **bên nào trả lời khách** để tránh nhắn trùng. Mỗi bình luận chỉ có 1 private reply, bên nào gửi trước thì bên kia không gửi được nữa.

## 8. Chạy test tự động

```bash
docker compose run --rm odoo odoo -d odoo20_lstest -i livestream_sale,livestream_sepay,livestream_facebook,livestream_instagram \
  --test-enable --test-tags /livestream_sale,/livestream_sepay,/livestream_facebook,/livestream_instagram --stop-after-init --no-http
```
