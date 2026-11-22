# Livestream Sale — Thiết kế (bản 1)

Ngày: 2026-11-22 · Odoo 20 Community (Docker, addons tự viết trong `individual_addons/`)

## 1. Mục đích và lý do

Người bán hàng qua livestream trên Facebook (sau này thêm Instagram) cần một chỗ trong Odoo để: xem comment chạy real-time, nhắn tin 1-1 với khách, chốt đơn và **thu cọc bằng giao dịch ngân hàng có thật**.

Đây là vấn đề lớn nhất khi dùng Pancake hiện nay: khách gửi **ảnh chụp chuyển khoản** để báo đã cọc. Ảnh làm giả được, không gắn với đơn hay khách, và không đi vào kế toán, nên dễ bị lừa và độ tin cậy thấp. Ngoài ra, dữ liệu trên Pancake không chảy xuống phần quản lý và báo cáo của Odoo. Sau này còn cần quản lý vận đơn, xử lý sự cố giao hàng và tính lãi lỗ theo phí vận chuyển, nên dữ liệu đơn và tiền phải nằm đúng chuẩn Odoo ngay từ đầu.

**Thành công nghĩa là:** một đơn chỉ được coi là đã cọc khi có giao dịch SePay thật được gắn vào đơn. Mỗi giao dịch chỉ dùng được một lần, có lịch sử ai gắn, lúc nào. Tiền cọc hiện lên thành bút toán thanh toán chuẩn của Odoo, gắn với khách và đơn.

## 2. Mục tiêu / Ngoài phạm vi / Điều không được để xảy ra

**Mục tiêu bản 1**
- Kết nối Facebook Page: nhận comment trong livestream, private reply vào Messenger, chat 2 chiều.
- Kết nối SePay: nhận giao dịch tiền vào (webhook + cron kéo bù).
- Màn hình điều hành 3 cột (OWL client action), cập nhật real-time qua bus.
- Lên `sale.order` nhanh từ comment, yêu cầu cọc, sinh mã VietQR và gửi vào chat.
- Tự khớp tiền theo mã đơn trong nội dung chuyển khoản. Khớp tay 1 click cho giao dịch ghi sai cú pháp.
- Bộ giả lập comment và tiền về để dev, demo và test.

**Ngoài phạm vi bản 1** (làm sau): Instagram, quản lý vận đơn và hãng vận chuyển, đối soát phí ship, một giao dịch trả cho nhiều đơn, chatbot/AI tự trả lời, các nền tảng khác (TikTok, Zalo).

**Không được để xảy ra (dù tính năng vẫn "chạy")**
- Đơn được coi là đã cọc khi chưa có giao dịch ngân hàng thật.
- Một giao dịch được gắn vào hai đơn.
- Nhân viên sửa được số tiền hoặc nội dung của giao dịch gốc.
- Gỡ khớp mà không để lại dấu vết.
- Lưu tiền cọc thành một cờ riêng nằm ngoài kế toán Odoo.

## 3. Ràng buộc

- **Meta**: cần **Meta App riêng của chủ shop**. Quyền của Pancake không dùng lại được. Khi app ở Development mode, chỉ những tài khoản có vai trò trong app (admin/dev/tester) mới hoạt động được. Muốn bán thật thì phải qua App Review (`pages_read_engagement`, `pages_manage_metadata`, `pages_messaging`, `pages_read_user_content`).
- **Private reply**: mỗi comment chỉ được gửi **1** tin nhắn riêng, trong vòng 7 ngày. Khi khách nhắn lại thì mở cửa sổ 24h (`messaging_type=RESPONSE`). Ngoài 24h thì cần tag `HUMAN_AGENT` (phải xin quyền riêng). UI phải hiển thị trạng thái cửa sổ chat này.
- **Môi trường local**: Odoo chạy ở localhost, nên Meta và SePay chỉ gọi webhook vào được qua tunnel (cloudflared/ngrok). Vì vậy phải có cron kéo dữ liệu bù.
- Odoo chạy `workers = 0` → bus/websocket chạy ở chế độ threaded, chấp nhận được cho dev.
- VND, tài khoản ngân hàng VN; VietQR dùng lại phần có sẵn của `l10n_vn` + `account_qr_code_emv`.
- Có thể chạy song song với Pancake trong giai đoạn chuyển tiếp: cả hai cùng nhận comment/tin nhắn, nên shop phải tự thống nhất bên nào trả lời.

## 4. Các phương án đã cân nhắc

**Khung chat (cột giữa)**
- **A. Hội thoại là `discuss.channel` với `channel_type = 'livestream'`** (giống cách `im_livechat` thêm loại `livechat`). Cột giữa dùng lại component Thread/Composer của mail. Lịch sử chat nằm trong Odoo, gắn với khách. → **Đã chọn.**
- B. Model chat tự viết + UI OWL riêng: nhanh lúc đầu, nhưng phải tự làm lại đính kèm, trạng thái đã đọc... và tách rời hệ thống tin nhắn của Odoo. Bị loại vì đi ngược mục tiêu "dữ liệu chảy xuống dưới".
- Dùng `im_livechat` trực tiếp: bị loại vì nó làm cho chat trên website (visitor, rating, operator), không hợp với Messenger.

**Ghi nhận tiền cọc** (quyết định sau khi đọc code Odoo 20)
- **Dùng cơ chế thanh toán sẵn có: `payment.provider` mã `sepay` + `payment.transaction` gắn với `sale.order`.** → **Đã chọn.** Odoo 20 đã có sẵn:
  - `sale.order.prepayment_percent / prepayment_amount`: số tiền cọc yêu cầu.
  - `sale.order.amount_paid`: tổng tiền từ các transaction `done`.
  - `payment.transaction._post_process()` → `_check_amount_and_confirm_order()`: **tự xác nhận đơn khi tiền cọc đủ**.
  - `account_payment`: tự tạo `account.payment` cho transaction `done`. Nếu bật `sale_automatic_invoice` thì còn tạo hóa đơn cọc (down payment).
- Phương án loại: tự tạo `account.payment` rồi gắn bằng M2M riêng. Phải tự viết lại logic xác nhận đơn và tính số tiền đã trả mà Odoo đã có.

## 5. Thiết kế

### 5.1 Các module

| Module | Phụ thuộc | Nội dung |
|---|---|---|
| `livestream_sale` (lõi) | `sale_management`, `mail`, `bus`, `account_payment`, `l10n_vn` | Tài khoản kênh, phiên live, mã tag, comment, khách theo nền tảng, kênh chat `livestream`, giao dịch ngân hàng, logic khớp, màn hình 3 cột, bộ giả lập, phân quyền |
| `livestream_sepay` | `livestream_sale`, `payment` | `payment.provider` code `sepay`, controller webhook, cron kéo API, chuyển dữ liệu SePay thành `livestream.bank.transaction` |
| `livestream_facebook` | `livestream_sale` | Kết nối Page, webhook (verify + chữ ký `X-Hub-Signature-256`), nhận comment, private reply, gửi/nhận Messenger, cron kéo comment bù |

Lõi định nghĩa các **điểm nối (hook)** để module kết nối ghi đè theo `platform`:
`_livestream_send_message(channel, body, attachments)`, `_livestream_private_reply(comment, body)`, `_livestream_fetch_comments(session)`.
Riêng bộ giả lập là một "platform" tên `simulator` nằm trong lõi.

### 5.2 Model chính (lõi)

- **`livestream.account`**: một Page/tài khoản kết nối. `platform` (selection, module kết nối thêm giá trị), `name`, `external_id` (page id), token (chỉ group quản trị đọc được), `company_id`, `active`.
- **`livestream.session`**: một buổi live. `account_id`, `external_video_id`, `external_post_id`, `name`, `state` (draft/live/ended), `start/end`, `tag_line_ids`, `user_ids` (trợ lý trực).
- **`livestream.session.tag`**: `session_id`, `code` (vd `69`, duy nhất trong phiên), `product_id`, `price_unit`, `note`.
- **`livestream.customer`**: danh tính của khách trên nền tảng. `account_id`, `external_user_id` (id người comment), `psid` (Messenger page-scoped id, lấy từ kết quả private reply hoặc tin nhắn đến), `name`, `avatar_url`, `partner_id` (tự tạo `res.partner` khi lên đơn, hoặc gộp vào partner có sẵn nếu trùng SĐT). Ràng buộc duy nhất `(account_id, external_user_id)`.
- **`livestream.comment`**: `session_id`, `external_id` (duy nhất), `customer_id`, `message`, `tag_code` + `quantity` (parse từ message, vd `69`, `69 x2`, `69 sl 2`), `tag_id`, `create_time`, `state` (new/contacted/ordered/ignored), `channel_id`, `sale_order_id`, `private_reply_sent` (bool).
- **`discuss.channel`** (kế thừa): thêm `channel_type` = `livestream`, `livestream_customer_id`, `livestream_origin_comment_id`, `livestream_window_expires_at` (cập nhật mỗi khi khách nhắn). Mỗi khách trên một tài khoản có **một** kênh (dùng lại cho các lần live sau). Tin nhắn trợ lý gửi trong kênh được đẩy ra nền tảng qua hook. Tin khách gửi đến được `message_post` với author là partner của khách.
- **`livestream.bank.transaction`**: `provider_id`, `external_id` (id SePay, duy nhất theo provider), `date`, `amount`, `content`, `reference`, `account_number`, `gateway`, `raw_payload` (json), `state` (unmatched/matched/ignored), `sale_order_id`, `payment_transaction_id`, `match_method` (auto/manual), `matched_by`, `matched_at`. Dữ liệu gốc **readonly với mọi người** (chặn bằng `write` override). Lịch sử khớp/gỡ được ghi qua `mail.thread` tracking.
- **`sale.order`** (kế thừa): `livestream_session_id`, `livestream_comment_ids`, `livestream_channel_id`, `livestream_payment_ref` (mã chuyển khoản, vd `LS` + id 6 chữ số, duy nhất), `livestream_bank_transaction_ids`. Dùng lại `prepayment_amount` / `amount_paid` sẵn có.

### 5.3 Luồng chính

1. **Comment vào** (webhook hoặc cron bù): ghi event thô vào `livestream.webhook.event` (để replay và chống mất), xử lý → tạo/tìm `livestream.customer` → tạo `livestream.comment` (chống trùng theo `external_id`) → parse tag → `bus` gửi `livestream/comment` tới những ai đang mở màn hình của phiên.
2. **"Mở hội thoại & Chốt"**: tìm/tạo `discuss.channel` cho khách, gắn comment gốc làm ngữ cảnh. Tin nhắn đầu tiên trợ lý gửi khi chưa có PSID sẽ đi bằng **private reply** cho comment đó. Từ đó trở đi gửi bằng Send API với PSID. UI hiển thị: "Chờ khách trả lời" / "Còn hh:mm trong cửa sổ 24h" / "Hết cửa sổ".
3. **Tạo đơn**: cột 3 điền sẵn sản phẩm theo tag (số lượng parse từ comment). Trợ lý sửa SL, nhập SĐT/địa chỉ (tạo hoặc gộp `res.partner` theo SĐT) và tiền cọc (→ `prepayment_amount`), rồi bấm "Tạo đơn" → `sale.order` ở trạng thái quotation, sinh `livestream_payment_ref`.
4. **Yêu cầu cọc & QR**: `sale.order._generate_vietqr_url()` gọi `res.partner.bank.build_qr_code_base64('emv_qr', amount=cọc còn thiếu, free_communication=livestream_payment_ref, ...)` trên tài khoản ngân hàng gắn với provider SePay. Nút "Gửi yêu cầu cọc & QR" gửi tin nhắn mẫu (số tiền, STK, nội dung CK) kèm ảnh QR vào chat.
5. **Tiền về** (webhook SePay hoặc cron): chỉ nhận `transferType = in` → tạo `livestream.bank.transaction` (chống trùng theo id) → **tự khớp**: chuẩn hóa nội dung (bỏ dấu, khoảng trắng, chữ thường) rồi tìm đúng một `livestream_payment_ref` → `_match_to_order(order, method='auto')`. Không khớp thì để `unmatched` → bus `livestream/bank_transaction`.
6. **`_match_to_order`** (dùng chung cho tự khớp và khớp tay): khóa dòng (`SELECT ... FOR UPDATE`), kiểm tra giao dịch còn `unmatched` và đơn chưa hủy → tạo `payment.transaction` (provider sepay, amount, `sale_order_ids=[order]`, reference duy nhất) → `_set_done()` → `_post_process()`. Odoo tự tạo `account.payment` và tự xác nhận đơn nếu `amount_paid >= prepayment_amount`. Sau đó đăng tin xác nhận lên chatter đơn và lên kênh chat (nội bộ), rồi bus báo xanh.
7. **Khớp tay**: danh sách giao dịch chưa khớp, mỗi dòng có gợi ý đơn xếp theo điểm: số tiền = cọc còn thiếu (cao nhất), nội dung chứa SĐT/tên khách/phần mã đơn, đơn gửi QR trong vòng 24h. Nút "Gắn vào đơn đang mở" và "Gắn vào [đơn gợi ý]" đều gọi `_match_to_order(method='manual')`.
8. **Gỡ khớp**: chỉ group quản lý, bắt buộc nhập lý do. Hủy `account.payment` tương ứng (draft → cancel), đặt transaction về `canceled`, giao dịch ngân hàng trở về `unmatched`, ghi log. Không cho gỡ nếu đơn đã có hóa đơn cuối hoặc đã giao hàng.
9. **Chặn giao hàng khi chưa đủ cọc**: override `action_confirm` của đơn livestream. Nếu `amount_paid < prepayment_amount` thì báo lỗi, trừ khi user thuộc group quản lý (khi đó ghi log "xác nhận không cọc").

### 5.4 Kế toán

- Provider `sepay` gắn với **sổ Ngân hàng** của tài khoản nhận tiền. Nhờ đó `account.payment` sinh ra nằm đúng sổ, partner = khách, memo = `livestream_payment_ref`. Báo cáo công nợ, tiền trả trước và hóa đơn cọc chạy theo chuẩn Odoo.
- Khớp với dòng sao kê ngân hàng (`account.bank.statement.line`): bản Community **không có** công cụ đối soát sao kê. Ở bản 1, mình cấu hình outstanding account của phương thức thanh toán SePay = chính tài khoản ngân hàng, để `account.payment` ghi thẳng vào tài khoản ngân hàng mà không cần đối soát sao kê. *(Quyết định của mình, có thể đổi nếu sau này dùng Enterprise.)*

### 5.5 Màn hình 3 cột (`ir.actions.client`, tag `livestream_console`)

```
┌ Phiên: [Live 22/11 ▾]  ● LIVE   Lọc tag: [69] [12] [Tất cả]   🔍 ┐
├────────────────┬──────────────────────────┬────────────────────────┤
│ Comment live   │ Chat với Nguyễn Văn A    │ Đơn của khách           │
│ 69 · Ng.Văn A  │ ┌ Comment gốc: "69 x2" ┐ │ [69] Áo thun đỏ  x[2]  │
│  "69 x2"  [Mở] │ └──────────────────────┘ │ SĐT [..] Đ/c [.....]    │
│ 69 · Trần B    │ …tin nhắn…               │ Cọc [100.000]           │
│ 12 · Lê C      │ ⏱ Còn 23:41 cửa sổ chat   │ [Tạo đơn]  QR ▣ [Gửi]  │
│ …              │ [soạn tin…]  [Gửi cọc&QR]│─────────────────────────│
│                │                          │ Tiền về                 │
│                │                          │ ✓ 100k LS000123 → S0012 │
│                │                          │ ! 200k "ck ao do" [Gắn] │
└────────────────┴──────────────────────────┴────────────────────────┘
```
- Real-time: server gửi bus notification lên kênh riêng của từng tài khoản. Client subscribe qua `bus_service`.
- Cột 2 dùng lại `Thread` + `Composer` của mail trên `discuss.channel` đã chọn.
- Bộ giả lập (chỉ hiện ở chế độ dev hoặc với group quản lý): nút "Giả lập comment" và "Giả lập tiền về".

### 5.6 Bảo mật & phân quyền

- Group: **Trợ lý livestream** (xem/chat/tạo đơn/khớp tay) và **Quản lý livestream** (cấu hình, gỡ khớp, xác nhận không cọc, xem token).
- Webhook Facebook: kiểm tra `hub.verify_token` và chữ ký `X-Hub-Signature-256` (app secret). Webhook SePay: header `Authorization: Apikey <key>`, so sánh bằng `hmac.compare_digest`.
- Controller webhook ghi event thô rồi trả 200 ngay, xử lý sau (`ir.cron` trigger) để không timeout.
- Multi-company: mọi model có `company_id` + record rule.

### 5.7 Kiểm thử

- Unit test (`odoo.tests`): parse tag, chống trùng comment/giao dịch, tự khớp, khớp tay, không gắn được một giao dịch hai lần, gỡ khớp, chặn xác nhận khi thiếu cọc, xác nhận tự động khi đủ cọc, sinh QR.
- Payload mẫu Facebook và SePay để test controller (có thể replay qua Postman).
- Test tay theo hướng dẫn: Page test + app ở Development mode + tài khoản tester + OBS/ffmpeg phát live, tunnel cloudflared; chuyển khoản thật số tiền nhỏ vào tài khoản đã nối SePay.

## 6. Phần để người xây quyết định

- Payload SePay (webhook: `id, gateway, transactionDate, accountNumber, code, content, transferType, transferAmount, accumulated, referenceCode, description`; API `GET https://my.sepay.vn/userapi/transactions/list`, Bearer token): **kiểm tra lại theo tài liệu SePay hiện hành** trước khi viết.
- Phiên bản Graph API, cách subscribe webhook `feed` / `live_videos` / `messages`, và cơ chế kéo bù comment (`/{live-video-id}/comments`).
- Cách nhúng Thread/Composer của mail Odoo 20 vào client action (theo hướng patch nhỏ nhất).
- Mẫu tin nhắn yêu cầu cọc (cho phép chỉnh trong cấu hình).
- `payment.transaction` trong Odoo 20 bắt buộc có `payment_method_id`. Provider `sepay` cần gắn sẵn một `payment.method` (ưu tiên dùng lại phương thức chuyển khoản có sẵn của module `payment`, nếu không có thì tạo `sepay`).
- Đơn livestream đặt `require_signature = False`, vì `_check_amount_and_confirm_order` sẽ không tự xác nhận đơn nếu đơn cần ký.
- Định dạng `livestream_payment_ref`: đề xuất `LS` + 6 số. Cần cấu hình tiền tố này trong mục "nhận diện mã thanh toán" của SePay để SePay điền sẵn trường `code`.

## 7. Các giả định cần chủ shop xác nhận

- Chủ shop sẽ tạo Meta App riêng (Development mode để test, App Review để chạy thật).
- Một giao dịch chỉ gắn vào một đơn. Một đơn nhận được nhiều giao dịch.
- Trợ lý được tự tạo/gộp `res.partner` theo SĐT.
