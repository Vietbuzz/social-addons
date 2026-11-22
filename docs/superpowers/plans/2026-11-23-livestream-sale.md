# Livestream Sale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Module Odoo 20 cho bán hàng livestream (Facebook) với màn hình điều hành 3 cột, chat 1-1, lên đơn và thu cọc bằng giao dịch SePay thật được khớp vào `sale.order`.

**Architecture:** Lõi `livestream_sale` chứa model, logic khớp tiền, bộ giả lập và OWL client action. Hai module kết nối `livestream_sepay` (payment provider + webhook/cron) và `livestream_facebook` (webhook/Graph API) ghi đè các hook theo `platform`. Chat là `discuss.channel` với `channel_type='livestream'`. Cọc là `payment.transaction` → Odoo tự tạo `account.payment` và tự xác nhận đơn khi đủ `prepayment_amount`.

**Tech Stack:** Odoo 20 Community (Python 3, ORM, `odoo.tests`), OWL 2 + `@mail` Thread/Composer, `bus` service, `requests` cho HTTP ra ngoài, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-22-livestream-sale-design.md`

## Global Constraints

- Tất cả module nằm trong `individual_addons/` (mount `/mnt/extra-addons`). Không sửa `addons/` (chỉ là nguồn đọc tham khảo).
- `version` manifest: `20.0.1.0.0`, `license`: `LGPL-3`.
- Tiền tệ VND. QR dùng `res.partner.bank.build_qr_code_base64('emv_qr', ...)` của `l10n_vn` + `account_qr_code_emv`.
- `livestream_payment_ref` = `LS` + 6 chữ số, duy nhất.
- Một `livestream.bank.transaction` chỉ gắn với **một** đơn; một đơn nhận được nhiều giao dịch.
- Dữ liệu gốc của giao dịch ngân hàng (`external_id, date, amount, content, reference, account_number, gateway, raw_payload`) không ai sửa được sau khi tạo.
- Gỡ khớp và xác nhận đơn không cọc: chỉ `livestream_sale.group_livestream_manager`, bắt buộc có lý do / ghi log.
- Controller webhook: ghi `livestream.webhook.event` rồi trả 200 ngay; xử lý ở cron được trigger.
- So sánh secret bằng `hmac.compare_digest`. Token/secret chỉ group manager đọc được (`groups=` trên field).
- Mọi model có `company_id` + record rule multi-company.
- Chuỗi giao diện viết bằng tiếng Anh trong code (`_()`), kèm file `i18n/vi.po` ở task cuối.

**Lệnh test chung** (thay `<mods>` và `<tags>`):
```bash
cd "/Users/buzz/odoo 20" && docker compose run --rm odoo odoo -d odoo20_lstest -i <mods> \
  --test-enable --test-tags <tags> --stop-after-init --no-http --log-level=test
```
Chạy lần đầu sẽ tạo DB `odoo20_lstest`. Khi cần DB sạch: `docker compose run --rm odoo odoo db drop odoo20_lstest` hoặc dùng `dropdb` trên Postgres host.

## Review Focus

1. **Webhook đến trùng lặp hoặc đến không theo thứ tự** (Meta/SePay gửi lại cùng một event). Kỳ vọng: không sinh comment/giao dịch/payment trùng. → test `test_ingest_duplicate_comment`, `test_sepay_webhook_idempotent` (Task 2, 8).
2. **Hai trợ lý cùng bấm gắn một giao dịch vào hai đơn khác nhau gần như cùng lúc.** Kỳ vọng: chỉ một lần thành công, lần kia báo lỗi rõ ràng. → `test_match_twice_raises` + khóa `FOR UPDATE` (Task 5).
3. **Nội dung chuyển khoản bị ngân hàng biến dạng** (chữ thường, thêm khoảng trắng/dấu chấm, `LS 000123`, `ls000123`, có dấu tiếng Việt, kèm chuỗi khác; hoặc chứa 2 mã đơn). Kỳ vọng: khớp khi có đúng một mã; không tự khớp khi có 0 hoặc ≥2 mã. → `test_auto_match_normalizes_content`, `test_auto_match_ambiguous_skipped` (Task 5).
4. **Tiền về ít hơn hoặc nhiều hơn tiền cọc yêu cầu.** Kỳ vọng: vẫn ghi nhận vào `amount_paid`; đơn chỉ tự xác nhận khi tổng ≥ `prepayment_amount`. → `test_partial_deposit_keeps_quotation`, `test_two_transfers_confirm_order` (Task 5).
5. **Comment không đúng cú pháp tag** (`69x2`, `69 sl2`, `#69`, `mã 69`, `ok`, emoji, số điện thoại trong comment). Kỳ vọng: parse đúng tag và SL khi có thể; SĐT không bị nhận nhầm là tag; comment không có tag vẫn hiện ở cột 1. → `test_parse_tag_variants` (Task 1).

---

### Task 0: Khởi tạo repo và khung module lõi

**Files:**
- Create: `.gitignore` (bỏ qua `addons/`, `__pycache__/`, `*.pyc`, `.DS_Store`)
- Create: `individual_addons/livestream_sale/__init__.py`, `__manifest__.py`, `models/__init__.py`, `security/livestream_security.xml`, `security/ir.model.access.csv`, `tests/__init__.py`, `tests/test_install.py`

**Interfaces:**
- Produces: groups `livestream_sale.group_livestream_user` ("Livestream Assistant", implies `sales_team.group_sale_salesman`), `livestream_sale.group_livestream_manager` (implies user). Category `livestream_sale.module_category_livestream`.
- Manifest `depends`: `["sale_management", "mail", "bus", "account_payment", "l10n_vn"]`.

- [ ] **Step 1:** `git init` ở `/Users/buzz/odoo 20`, tạo `.gitignore`, commit spec + plan.
- [ ] **Step 2: Test cài đặt**
```python
@tagged("post_install", "-at_install", "livestream")
class TestInstall(TransactionCase):
    def test_groups_exist(self):
        mgr = self.env.ref("livestream_sale.group_livestream_manager")
        user = self.env.ref("livestream_sale.group_livestream_user")
        self.assertIn(user, mgr.implied_ids)
```
- [ ] **Step 3:** Chạy lệnh test với `<mods>=livestream_sale`, `<tags>=/livestream_sale` → FAIL (module chưa có).
- [ ] **Step 4:** Viết manifest + groups. Chạy lại → PASS.
- [ ] **Step 5:** Commit `feat(livestream_sale): scaffold module and security groups`.

---

### Task 1: Account, session, tag, customer + parse tag

**Files:**
- Create: `models/livestream_account.py`, `models/livestream_session.py`, `models/livestream_customer.py`, `models/tag_parser.py`, `views/livestream_account_views.xml`, `views/livestream_session_views.xml`, `views/menus.xml`
- Test: `tests/test_tag_parser.py`, `tests/common.py`

**Interfaces:**
- `livestream.account`: `name`, `platform` = `fields.Selection([("simulator", "Simulator")], required=True)` (module kết nối dùng `selection_add`), `external_id` Char, `access_token` Char (`groups="livestream_sale.group_livestream_manager"`), `company_id`, `active`, `payment_provider_id` M2o `payment.provider` (provider dùng để thu cọc / sinh QR). Ràng buộc duy nhất `(platform, external_id)`.
- `livestream.session`: `name`, `account_id`, `external_video_id`, `external_post_id`, `state` `[draft, live, ended]`, `date_start`, `date_end`, `tag_ids` O2m, `user_ids` M2m `res.users`, `company_id` related account. Phương thức `action_start()`, `action_end()`.
- `livestream.session.tag`: `session_id`, `code` Char required, `product_id` (`product.product`) required, `price_unit` Float (onchange mặc định `lst_price`), `note`. Unique `(session_id, code)`.
- `livestream.customer`: `account_id`, `external_user_id`, `psid`, `name`, `avatar_url`, `partner_id`, `channel_id` (M2o `discuss.channel`, điền ở Task 3), `company_id`. Unique `(account_id, external_user_id)`. `@api.model _get_or_create(account, external_user_id: str, name: str, avatar_url: str | None = None) -> livestream.customer`.
- `tag_parser.parse_tag(message: str, codes: set[str] | None = None) -> tuple[str | None, int]`: hàm thuần, trả về `(code, qty)`, mặc định qty=1. Khi có `codes` thì chỉ nhận code thuộc tập đó. Cú pháp nhận: `69`, `#69`, `mã 69`, `ma69`, `69 x2`, `69x2`, `69 sl 2`, `69 sl2`, `69*2`, `69 - 2c`. Bỏ qua chuỗi số dài ≥ 8 chữ số (SĐT) và số dính chữ/số khác.
- `tests/common.py`: `class LivestreamCommon(TransactionCase)` với `setUpClass` tạo: công ty VN tiền VND, sổ ngân hàng `bank_journal`, `res.partner.bank` VN (bank có `bic`, `proxy_type='bank_acc'`, `proxy_value`, `allow_out_payment=True`), một `payment.provider` (`code='none'`, `state='test'`, `journal_id=bank_journal`, gắn một `payment.method`), `account` (platform `simulator`, `payment_provider_id`), `session` state `live`, product `Áo thun đỏ` giá 150000, tag `69`. Các task sau đều kế thừa class này.

- [ ] **Step 1: Test**
```python
class TestTagParser(TransactionCase):
    def test_parse_tag_variants(self):
        cases = {
            "69": ("69", 1), "#69": ("69", 1), "mã 69": ("69", 1), "69 x2": ("69", 2),
            "69x2": ("69", 2), "69 sl 3": ("69", 3), "69*2": ("69", 2), "chốt 69 nha": ("69", 1),
            "ok": (None, 1), "0912345678": (None, 1), "😍😍": (None, 1),
            "0912345678 lấy 69": ("69", 1),
        }
        for msg, expected in cases.items():
            self.assertEqual(parse_tag(msg), expected, msg)

    def test_parse_tag_restricted_codes(self):
        self.assertEqual(parse_tag("12 69", codes={"69"}), ("69", 1))
        self.assertEqual(parse_tag("12", codes={"69"}), (None, 1))
```
Cộng thêm `test_customer_get_or_create_dedup` (gọi 2 lần → cùng record) và `test_tag_code_unique_per_session` (raise `IntegrityError` hoặc `ValidationError`).
- [ ] **Step 2:** Chạy test → FAIL.
- [ ] **Step 3:** Cài đặt model, `parse_tag` (regex), view list/form cho account, session (bảng tag editable), menu gốc "Livestream" (Cấu hình → Tài khoản kết nối; Phiên live). Access CSV: user đọc account/ghi session, tag, customer; manager toàn quyền. Record rule company.
- [ ] **Step 4:** Chạy test → PASS.
- [ ] **Step 5:** Commit `feat(livestream_sale): accounts, sessions, tags, customers, tag parser`.

---

### Task 2: Webhook event queue + nhận comment + bus

**Files:**
- Create: `models/livestream_webhook_event.py`, `models/livestream_comment.py`, `data/ir_cron.xml`, `views/livestream_comment_views.xml`
- Test: `tests/test_comment_ingest.py`

**Interfaces:**
- `livestream.webhook.event`: `source` Selection `[("simulator","Simulator")]` (mở rộng bằng `selection_add`), `payload` Json, `state` `[pending, done, error]`, `error` Text, `account_id`, `company_id`. `@api.model _enqueue(source: str, payload: dict, account=None) -> record` (tạo + `self.env.ref("livestream_sale.ir_cron_process_webhook_events")._trigger()`). `_process()` gọi `getattr(self, f"_process_{source}")(payload)` cho từng record, mỗi record bọc trong savepoint, lỗi → `state='error'` (không làm hỏng record khác). Cron `ir_cron_process_webhook_events` gọi `_cron_process(limit=200)`.
- `livestream.comment`: field như spec §5.2: `session_id`, `external_id` (unique `(session_id, external_id)`), `customer_id`, `message`, `tag_code`, `quantity`, `tag_id` (compute stored theo `tag_code` + `session_id.tag_ids`), `comment_time` Datetime, `state` `[new, contacted, ordered, ignored]`, `channel_id`, `sale_order_id`, `private_reply_sent` Bool, `company_id`.
- `@api.model _ingest(session, external_id: str, external_user_id: str, author_name: str, message: str, comment_time: datetime, avatar_url: str | None = None) -> livestream.comment` → trả về record có sẵn nếu trùng; tạo mới thì parse tag (giới hạn trong mã của phiên khi phiên có tag) và gọi `_notify_console("livestream/comment", [self._console_format()])`.
- `_console_format() -> dict` với keys: `id, session_id, customer_id, customer_name, avatar_url, message, tag_code, quantity, product_name, state, comment_time (ISO), channel_id, sale_order_id`.
- Helper dùng chung (đặt ở `models/livestream_account.py`): `livestream.account._notify_console(notification_type: str, payload)` → `self.env.ref("livestream_sale.group_livestream_user")._bus_send(notification_type, {"account_id": self.id, "company_id": self.company_id.id, "items": payload})`. Client tự lọc theo `account_id`.

- [ ] **Step 1: Test**
```python
def test_ingest_duplicate_comment(self):
    c1 = self.Comment._ingest(self.session, "c1", "u1", "Nguyễn Văn A", "69 x2", now)
    c2 = self.Comment._ingest(self.session, "c1", "u1", "Nguyễn Văn A", "69 x2", now)
    self.assertEqual(c1, c2)
    self.assertEqual((c1.tag_id.code, c1.quantity), ("69", 2))
    self.assertEqual(c1.customer_id.external_user_id, "u1")

def test_ingest_sends_bus(self):
    with self.mock_bus():  # hoặc patch bus.bus._sendone, đếm số lần gọi với 'livestream/comment'
        self.Comment._ingest(self.session, "c2", "u2", "Trần B", "69", now)

def test_event_error_isolated(self):
    bad = self.Event._enqueue("simulator", {"kind": "broken"})
    good = self.Event._enqueue("simulator", {"kind": "comment", ...})
    (bad | good)._process()
    self.assertEqual((bad.state, good.state), ("error", "done"))
```
- [ ] **Step 2:** Chạy test → FAIL.
- [ ] **Step 3:** Cài đặt. `_process_simulator(payload)` hỗ trợ `kind="comment"` (task này) và `kind="bank"` (Task 6). Kind lạ thì raise `UserError`.
- [ ] **Step 4:** Chạy test → PASS.
- [ ] **Step 5:** Commit `feat(livestream_sale): webhook event queue and comment ingest`.

---

### Task 3: Kênh chat `livestream` (discuss.channel)

**Files:**
- Create: `models/discuss_channel.py`, `models/mail_message.py` (nếu cần), `static/src/core/thread_icon_patch.js` (icon Facebook trên kênh)
- Modify: `models/livestream_customer.py`, `models/livestream_comment.py`
- Test: `tests/test_conversation.py`

**Interfaces:**
- `discuss.channel`: `channel_type` `selection_add=[("livestream", "Livestream")]`, `ondelete={"livestream": "cascade"}`. Field mới: `livestream_customer_id`, `livestream_origin_comment_id`, `livestream_window_expires_at` Datetime, `livestream_window_state` compute `[waiting, open, closed]` (`waiting` = chưa có `psid`; `open` = now < expires; còn lại `closed`).
- `livestream.customer._get_or_create_channel() -> discuss.channel`: một kênh cho mỗi customer. Thành viên: partner của khách (tạo partner tạm `name=customer.name` nếu chưa có `partner_id`) + user hiện tại. Kênh đã có thì thêm user hiện tại làm thành viên nếu chưa là thành viên.
- `livestream.comment.action_open_conversation() -> dict` trả `{"channel_id": int, "comment": self._console_format()}`, đặt `channel.livestream_origin_comment_id = self`, `state` `new→contacted`.
- **Gửi ra ngoài:** override `discuss.channel._message_post_after_hook(message, msg_vals)`. Với kênh `livestream`, nếu `message.author_id` không phải partner của khách, `message_type == 'comment'` **và** `message.subtype_id == mail.mt_comment` (note nội bộ `mail.mt_note` không bao giờ gửi ra ngoài) thì gọi `self._livestream_deliver(message)`. Test thêm `test_internal_note_not_delivered`.
- `discuss.channel._livestream_deliver(message) -> None`: nếu customer chưa có `psid` và comment gốc chưa `private_reply_sent` → `account._livestream_private_reply(comment, body_text, attachments)`; nếu đã có `psid` → `account._livestream_send_message(customer, body_text, attachments)`. Chưa có `psid` mà đã dùng private reply → `UserError("Waiting for the customer to reply on Messenger")`. Lỗi gửi → raise `UserError` (rollback, tin không được lưu).
- Hook trên `livestream.account` (mặc định cho `simulator`: ghi log, coi như gửi thành công; private reply trên simulator sẽ gán `psid = "sim-" + external_user_id`):
  - `_livestream_private_reply(comment, body: str, attachments) -> str | None` (trả về psid nếu nền tảng cho biết)
  - `_livestream_send_message(customer, body: str, attachments) -> None`
- **Nhận vào:** `livestream.customer._receive_message(text: str, external_message_id: str, attachments: list[tuple[name, bytes]] | None = None) -> mail.message`: post vào kênh với `author_id=partner khách`, `message_type='comment'`, chống trùng theo `external_message_id` (lưu ở field `livestream_external_id` trên `mail.message`, unique khi not null), cập nhật `livestream_window_expires_at = now + 24h`.

- [ ] **Step 1: Test**
```python
def test_open_conversation_reuses_channel(self): ...  # 2 comment của cùng khách → cùng channel_id; comment.state == "contacted"
def test_first_message_uses_private_reply(self):
    ch = self.env["discuss.channel"].browse(comment.action_open_conversation()["channel_id"])
    with patch.object(type(self.account), "_livestream_private_reply", return_value="psid-1") as pr:
        ch.message_post(body="Chào anh", message_type="comment")
    pr.assert_called_once()
    self.assertEqual(customer.psid, "psid-1"); self.assertTrue(comment.private_reply_sent)
def test_second_message_before_reply_blocked(self): ...  # psid None (platform không trả về) → message_post lần 2 raise UserError
def test_receive_message_opens_window(self): ...  # state "open", expires ≈ now+24h, gọi trùng external id thì không post lại
def test_customer_message_not_echoed(self): ...  # _receive_message không gọi _livestream_send_message
```
- [ ] **Step 2:** Chạy test → FAIL.
- [ ] **Step 3:** Cài đặt. Đọc `addons/im_livechat/models/discuss_channel.py` làm mẫu để thêm `channel_type`, xem cách `_to_store` thêm field để client đọc được. Thêm `livestream_window_state`, `livestream_window_expires_at`, `livestream_customer_id` vào dữ liệu store của kênh.
- [ ] **Step 4:** Chạy test → PASS.
- [ ] **Step 5:** Commit `feat(livestream_sale): livestream discuss channel with outbound/inbound hooks`.

---

### Task 4: Đơn hàng từ comment, chặn xác nhận, VietQR

**Files:**
- Create: `models/sale_order.py`, `models/res_partner.py`, `data/ir_sequence.xml`, `views/sale_order_views.xml`
- Test: `tests/test_sale_order.py`

**Interfaces:**
- `sale.order` thêm: `livestream_session_id`, `livestream_comment_ids` O2m (`livestream.comment.sale_order_id`), `livestream_channel_id`, `livestream_payment_ref` Char (readonly, copy=False, unique khi not null, lấy từ sequence `livestream.payment.ref` với prefix `LS`, padding 6), `livestream_bank_transaction_ids` O2m (Task 5), `livestream_deposit_due` Monetary compute = `max(prepayment_amount - amount_paid, 0)`, `is_livestream` compute stored = `bool(livestream_session_id)`.
- `res.partner._livestream_find_or_create(name: str, phone: str, street: str | None) -> res.partner`: chuẩn hóa SĐT (bỏ khoảng trắng/dấu chấm, `+84`→`0`), tìm partner có `phone` chuẩn hóa trùng; không thấy thì tạo mới.
- `livestream.comment.action_create_order(lines: list[dict], phone: str, name: str, street: str, deposit_amount: float) -> int` (`lines` = `[{"product_id", "quantity", "price_unit"}]`): tạo partner → gán `customer.partner_id` (cập nhật thành viên kênh) → tạo `sale.order` (`require_payment=True`, `require_signature=False`, `prepayment_amount=deposit_amount`, gán session/channel, `livestream_payment_ref`) → `comment.state='ordered'`, `comment.sale_order_id` → trả về `order.id`. Phải đặt `prepayment_amount` **sau khi** đã tạo dòng đơn (vì nó tính lại `prepayment_percent`).
- `sale.order._generate_vietqr_url() -> str` (data URI `data:image/png;base64,...`): `bank = self.livestream_session_id.account_id.payment_provider_id.journal_id.bank_account_id`; gọi `bank.build_qr_code_base64(amount=self.livestream_deposit_due, free_communication=self.livestream_payment_ref, structured_communication=self.livestream_payment_ref, currency=self.currency_id, debtor_partner=self.partner_id, qr_method="emv_qr")`. Kiểm tra chữ ký thật của hàm trong `addons/account/models/res_bank.py` trước khi gọi. Thiếu tài khoản thì raise `UserError`.
- `sale.order.livestream_deposit_message() -> str`: tin nhắn mẫu (số tiền, STK, tên ngân hàng, nội dung CK = `livestream_payment_ref`) từ `ir.config_parameter` `livestream_sale.deposit_message_template` (có mặc định tiếng Việt, dùng `{amount} {account_number} {bank} {holder} {ref}`).
- `sale.order.action_livestream_send_deposit_request() -> None`: post vào `livestream_channel_id` (author = user hiện tại) nội dung `livestream_deposit_message()` + ảnh QR làm attachment → đi qua `_livestream_deliver` (Task 3).
- Override `action_confirm()`: với đơn `is_livestream` và `amount_paid < prepayment_amount`: user không thuộc manager → `UserError("Deposit not received: %s remaining")`; user manager → cho qua nhưng `message_post` ghi "Confirmed without full deposit by <user>". Odoo tự xác nhận đơn qua `payment.transaction` vẫn chạy được vì khi đó đã đủ tiền.

- [ ] **Step 1: Test**
```python
def test_create_order_from_comment(self):
    oid = comment.action_create_order([{"product_id": p.id, "quantity": 2, "price_unit": 150000}],
                                      "0912 345 678", "Nguyễn Văn A", "1 Lê Lợi", 100000)
    so = self.env["sale.order"].browse(oid)
    self.assertEqual((so.amount_untaxed, so.prepayment_amount), (300000, 100000))  # sản phẩm test không có thuế
    self.assertRegex(so.livestream_payment_ref, r"^LS\d{6}$")
    self.assertEqual(comment.state, "ordered")
def test_partner_merge_by_phone(self): ...  # partner có sẵn "+84 912345678" → tái dùng
def test_confirm_blocked_without_deposit(self): ...  # with_user(assistant) → UserError
def test_manager_confirm_without_deposit_logged(self): ...
def test_vietqr_generated(self): self.assertTrue(so._generate_vietqr_url().startswith("data:image/png;base64,"))
def test_send_deposit_request_posts_to_channel(self): ...  # patch _livestream_send_message/_private_reply; kiểm tra có attachment
```
- [ ] **Step 2:** Chạy test → FAIL.
- [ ] **Step 3:** Cài đặt + view: trên form `sale.order` thêm tab "Livestream" (phiên, mã CK, cọc còn thiếu, giao dịch).
- [ ] **Step 4:** Chạy test → PASS.
- [ ] **Step 5:** Commit `feat(livestream_sale): order from comment, deposit guard, VietQR`.

---

### Task 5: Giao dịch ngân hàng, tự khớp, khớp tay, gỡ khớp

**Files:**
- Create: `models/livestream_bank_transaction.py`, `wizard/livestream_unmatch_wizard.py` + view, `views/livestream_bank_transaction_views.xml`
- Modify: `models/sale_order.py` (thêm `livestream_bank_transaction_ids` O2m `livestream.bank.transaction.sale_order_id`)
- Test: `tests/test_bank_matching.py`

**Interfaces:**
- `livestream.bank.transaction` (`_inherit = ["mail.thread"]`): field như spec §5.2, unique `(provider_id, external_id)`. `IMMUTABLE_FIELDS = {"provider_id","external_id","date","amount","content","reference","account_number","gateway","raw_payload"}`. `write()` raise `UserError` khi đổi field trong tập này (kể cả với sudo, trừ khi context `livestream_allow_immutable_write` do chính code gắn). `unlink()` raise trừ khi `state == 'ignored'` và user là manager.
- `@api.model _register(provider, vals: dict) -> record`: idempotent theo `(provider, external_id)`. Tạo mới thì gọi `_try_auto_match()` và `_notify()`.
- `@staticmethod _normalize(text: str) -> str`: bỏ dấu (`unicodedata` NFKD), viết hoa, bỏ mọi ký tự không phải `A-Z0-9`.
- `_find_ref_orders() -> sale.order`: tìm mọi `LS\d{6}` trong `_normalize(content)`, trả các đơn có `livestream_payment_ref` khớp.
- `_try_auto_match() -> bool`: đúng **một** đơn (chưa hủy) → `_match_to_order(order, "auto")`; 0 hoặc ≥2 → giữ `unmatched`.
- `_match_to_order(order, method: Literal["auto","manual"]) -> payment.transaction`:
  1. `self.env.cr.execute("SELECT id FROM livestream_bank_transaction WHERE id = %s FOR UPDATE NOWAIT", ...)`, gặp lỗi lock thì raise `UserError` "đang được xử lý"; đọc lại `state`, khác `unmatched` thì raise `UserError`.
  2. `order.state == 'cancel'` → `UserError`.
  3. Tạo `payment.transaction` (`provider_id`, `payment_method_id = provider.payment_method_ids[:1]`, `amount`, `currency_id` VND, `partner_id = order.partner_id`, `sale_order_ids=[(6,0,[order.id])]`, `reference = f"{order.livestream_payment_ref}-{self.external_id}"`, `provider_reference = self.external_id`) → `tx._set_done()` → `tx._post_process()`.
  4. Ghi `state='matched'`, `sale_order_id`, `payment_transaction_id`, `match_method`, `matched_by`, `matched_at`. `message_post` lên giao dịch, lên đơn và lên kênh chat (note nội bộ `subtype_xmlid="mail.mt_note"`, Task 3 đã lọc nên không gửi ra ngoài).
  5. `_notify()`.
- `action_match_manual(order_id: int) -> dict` (gọi từ console) = `_match_to_order(order, "manual")` + trả `_console_format()`.
- `_suggest_orders(limit: int = 5) -> list[dict]`: chấm điểm các đơn `is_livestream` trạng thái draft/sent/sale có `livestream_deposit_due > 0` trong cùng công ty, tạo trong 7 ngày gần nhất: +50 nếu `amount == livestream_deposit_due`, +30 nếu nội dung chuẩn hóa chứa SĐT chuẩn hóa của khách, +20 nếu chứa phần số của mã đơn (bỏ số 0 đầu), +10 nếu nội dung chứa ≥2 từ trong tên khách đã chuẩn hóa, +10 nếu đơn tạo trong 24h. Trả về `[{"order_id","name","partner_name","deposit_due","score"}]` sắp xếp giảm dần, chỉ lấy score > 0.
- `_console_format() -> dict`: `id, date, amount, content, state, match_method, sale_order_id, sale_order_name, partner_name, suggestions` (chỉ có khi unmatched).
- `_notify()` → `provider` không có account → bắn tới mọi account cùng công ty có `payment_provider_id = provider`, type `livestream/bank_transaction`.
- Wizard `livestream.unmatch.wizard` (`transaction_id`, `reason` required): `action_confirm()` chỉ manager. Chặn nếu đơn có hóa đơn posted không phải down payment, hoặc có picking `done`. Thực hiện: `payment_transaction_id.payment_id.action_draft()` + `action_cancel()`, `payment_transaction_id._set_canceled()` (dùng `extra_allowed_states=("done",)`), ghi giao dịch về `unmatched`, xóa liên kết, log lý do.
- `ignored`: `action_ignore()` (manager, ví dụ tiền không phải cọc).

- [ ] **Step 1: Test**
```python
def test_auto_match_exact_ref(self): ...  # content f"CK {so.livestream_payment_ref}" → matched, so.amount_paid == amount
def test_auto_match_normalizes_content(self):
    for content in [f"ls {n}", f"L S{n}", f"Ls.{n} chuyen tien", f"thanh toán LS{n}"]: ...  # mỗi case là một giao dịch mới, đều khớp
def test_auto_match_ambiguous_skipped(self): ...  # 2 mã của 2 đơn → unmatched
def test_partial_deposit_keeps_quotation(self): ...  # 50k/100k → so.state in ("draft","sent"), deposit_due == 50000
def test_two_transfers_confirm_order(self): ...  # 50k + 50k → so.state == "sale"
def test_match_twice_raises(self):
    tx._match_to_order(so1, "manual")
    with self.assertRaises(UserError): tx._match_to_order(so2, "manual")
def test_immutable_fields(self): ...  # write amount → UserError, kể cả sudo
def test_register_idempotent(self): ...  # cùng external_id 2 lần → 1 record, 1 payment.transaction
def test_suggestions_rank_amount_and_phone(self): ...
def test_unmatch_by_manager(self): ...  # payment state cancel, tx unmatched, so.amount_paid == 0
def test_unmatch_forbidden_for_assistant(self): ...
def test_payment_created_in_bank_journal(self): ...  # tx.payment_id.journal_id == bank_journal, partner == so.partner_id
```
- [ ] **Step 2:** Chạy test → FAIL.
- [ ] **Step 3:** Cài đặt. Nếu `_create_payment` của `account_payment` yêu cầu thêm cấu hình (payment method line trên journal) thì bổ sung trong `tests/common.py` và trong hướng dẫn cấu hình. Theo spec §5.4, đặt outstanding account của payment method line = tài khoản ngân hàng: ghi thành bước trong hướng dẫn cài đặt (Task 10) và hàm `livestream.account.action_setup_provider_journal()` (manager) để tự cấu hình.
- [ ] **Step 4:** Chạy test → PASS. Chạy lại toàn bộ `/livestream_sale` → PASS.
- [ ] **Step 5:** Commit `feat(livestream_sale): bank transactions, auto/manual matching, unmatch`.

---

### Task 6: Bộ giả lập

**Files:**
- Create: `models/livestream_simulator.py` (AbstractModel `livestream.simulator`)
- Modify: `models/livestream_webhook_event.py` (`_process_simulator` kind `bank`)
- Test: `tests/test_simulator.py`

**Interfaces:**
- `livestream.simulator.simulate_comment(session_id: int, message: str | None = None, author_name: str | None = None) -> int`: tạo event `simulator` kind `comment` (tên khách ngẫu nhiên trong danh sách tên Việt mẫu, message mặc định là tag ngẫu nhiên của phiên + `x1..3`) rồi xử lý ngay. Trả về comment id.
- `livestream.simulator.simulate_customer_reply(channel_id: int, text: str) -> None` → `customer._receive_message` (gán `psid = "sim-..."` nếu chưa có).
- `livestream.simulator.simulate_bank(account_id: int, amount: float, content: str) -> int` → `livestream.bank.transaction._register_transfer(provider, {...external_id: "SIM-<uuid>"...})`.
- Mọi hàm trên chỉ manager gọi được, hoặc khi `ir.config_parameter` `livestream_sale.simulator_enabled` = `True`; không thỏa thì `AccessError`.

- [ ] **Step 1: Test** `test_simulate_comment_creates_comment`, `test_simulate_bank_auto_matches` (content chứa mã đơn → matched), `test_simulator_disabled_for_assistant` (AccessError).
- [ ] **Step 2:** Chạy → FAIL. **Step 3:** Cài đặt. **Step 4:** Chạy → PASS.
- [ ] **Step 5:** Commit `feat(livestream_sale): simulator`.

---

### Task 7: Màn hình điều hành 3 cột (OWL)

**Files:**
- Create: `models/livestream_console.py` (AbstractModel `livestream.console`), `data/client_action.xml`
- Create: `static/src/console/console_action.{js,xml,scss}` (root, đăng ký `registry.category("actions").add("livestream_console", ...)`), `static/src/console/comment_feed.{js,xml}`, `static/src/console/conversation_panel.{js,xml}`, `static/src/console/order_panel.{js,xml}`, `static/src/console/bank_feed.{js,xml}`, `static/src/console/console_model.js` (state reactive dùng chung)
- Modify: `__manifest__.py` (`assets: web.assets_backend: livestream_sale/static/src/**/*`)
- Test: `tests/test_console.py`, `static/tests/tours/console_tour.js` + `tests/test_console_tour.py` (HttpCase)

**Interfaces (server, mọi hàm gọi qua `orm.call`):**
- `livestream.console.load(session_id: int | False) -> dict`: `{"sessions": [{id,name,state}], "session": {id,name,state,account_id,tags:[{code,product_id,product_name,price_unit}]}, "comments": [comment._console_format() ... 200 cái mới nhất], "bank_transactions": [tx._console_format() ... 50 cái mới nhất của provider]}`. Thiếu `session_id` thì lấy phiên `live` mới nhất user được giao, không có thì lấy phiên mới nhất.
- `livestream.console.load_more_comments(session_id: int, before_id: int, tag_code: str | False) -> list[dict]`
- `livestream.console.order_panel(comment_id: int) -> dict`: `{"comment":..., "customer": {name, phone, street, partner_id}, "lines": [{product_id, product_name, quantity, price_unit}] (lấy từ tag + qty), "order": None | {id, name, state, amount_total, prepayment_amount, amount_paid, deposit_due, payment_ref, qr_url, transactions:[...]}}`
- Dùng lại: `livestream.comment.action_open_conversation`, `action_create_order`, `sale.order.action_livestream_send_deposit_request`, `livestream.bank.transaction.action_match_manual`, `livestream.simulator.*`.

**Hành vi client:**
- Thanh trên: chọn phiên, badge trạng thái, chip lọc tag (các mã của phiên + "Tất cả" + "Không tag"), ô tìm theo tên khách. Lọc làm phía client trên danh sách đã tải; khi cuộn xuống thì gọi `load_more_comments`.
- Cột 1: comment mới nhất ở trên, mỗi dòng có avatar/tên/tag/SL/giờ/badge trạng thái và nút "Mở hội thoại & Chốt". Comment mới đến qua bus được chèn lên đầu, có highlight 2 giây.
- Cột 2: dùng `useService("mail.store")`; `thread = await store["discuss.channel"].getOrFetch(channelId)`. Render khung comment gốc (sticky), `<Thread thread="thread" .../>`, `<Composer composer="thread.composer" thread="thread" mode="'extended'"/>`, badge cửa sổ 24h (`livestream_window_state`, đếm ngược). Nút "Gửi yêu cầu cọc & QR" chỉ bật khi đơn đã có.
- Cột 3 trên: form đơn (dòng sản phẩm sửa được SL/giá, thêm dòng theo tag khác), SĐT/tên/địa chỉ, tiền cọc (mặc định = `ir.config_parameter` `livestream_sale.default_deposit_amount`, nếu không có thì 30% tổng). Nút "Tạo đơn". Có đơn rồi thì hiện mã, trạng thái, đã cọc/còn thiếu, ảnh QR, nút "Copy nội dung CK", "Gửi vào chat", "Mở đơn" (mở form sale.order).
- Cột 3 dưới: danh sách giao dịch. Đã khớp → nền xanh + tên đơn. Chưa khớp → nền vàng, nút "Gắn vào đơn đang mở" (chỉ khi cột 3 đang có đơn) và tối đa 3 nút gợi ý `Gắn vào <SO> (<score>)`. Gặp lỗi thì hiện notification lỗi.
- Bus: `bus_service.subscribe("livestream/comment", ...)`, `subscribe("livestream/bank_transaction", ...)`; bỏ qua nếu `account_id` khác phiên đang xem. Giao dịch được khớp ứng với đơn đang mở thì reload `order_panel`.
- Menu "Bảng điều hành" mở client action. Thêm nút "Mở bảng điều hành" trên form phiên (truyền `session_id` qua `params`).
- Bố cục: 3 cột `grid-template-columns: minmax(280px, 1fr) minmax(360px, 1.4fr) minmax(320px, 1.1fr)`; màn hình < 992px chuyển sang tab.

- [ ] **Step 1: Test Python** `test_console_load_shapes` (đủ key), `test_order_panel_prefills_from_tag` (`lines[0] == {product: Áo thun đỏ, quantity: 2, price_unit: 150000}`), `test_order_panel_existing_order_has_qr`.
- [ ] **Step 2:** Chạy → FAIL. **Step 3:** Cài đặt `livestream.console`. **Step 4:** PASS.
- [ ] **Step 5:** Viết UI. Tour `livestream_console_tour`: mở action → thấy 3 cột → bấm "Giả lập comment" → comment xuất hiện → "Mở hội thoại & Chốt" → composer hiện → "Tạo đơn" → ảnh QR hiện → "Giả lập tiền về" với đúng mã → giao dịch xanh. `test_console_tour.py`: `HttpCase.start_tour("/odoo/action-livestream_sale.action_livestream_console", "livestream_console_tour", login="admin")`.
- [ ] **Step 6:** Chạy test với `<tags>=/livestream_sale` → PASS (kể cả tour).
- [ ] **Step 7:** Kiểm tra bằng mắt: `docker compose up -d`, tạo DB `odoo20_dev`, cài module, bật simulator, chạy luồng tour bằng tay trên 2 tab trình duyệt (tab 2 giả lập comment để xem real-time ở tab 1). Chụp màn hình.
- [ ] **Step 8:** Commit `feat(livestream_sale): 3-column operator console`.

---

### Task 8: `livestream_sepay`

**Files:**
- Create: `individual_addons/livestream_sepay/{__init__.py,__manifest__.py}`, `models/payment_provider.py`, `models/livestream_webhook_event.py`, `models/sepay_api.py`, `controllers/main.py`, `data/payment_method_data.xml`, `data/payment_provider_data.xml`, `data/ir_cron.xml`, `views/payment_provider_views.xml`
- Test: `tests/test_sepay.py`, `tests/payloads/webhook_in.json`, `tests/payloads/transactions_list.json`

**Interfaces:**
- Manifest `depends`: `["livestream_sale", "payment"]`.
- `payment.provider`: `code` `selection_add=[("sepay","SePay")]`, `ondelete={"sepay": "set default"}`. Field: `sepay_webhook_api_key` Char (groups=base.group_system), `sepay_api_token` Char (groups=base.group_system), `sepay_account_number` Char, `sepay_last_pulled_id` Integer. `_get_default_payment_method_codes()` → `{"sepay"}` khi code là `sepay`. Data: `payment.method` code `sepay` ("Chuyển khoản (SePay)"), provider `payment_provider_sepay` ở state `disabled`.
- `livestream.webhook.event.source` `selection_add=[("sepay","SePay")]`. `_process_sepay(payload)`: bỏ qua khi `transferType != "in"`; tìm provider qua `payload["_provider_id"]` (controller gắn vào) → `livestream.bank.transaction._register_transfer(provider, sepay_webhook_to_vals(payload))`.
- `sepay_api.sepay_webhook_to_vals(p: dict) -> dict`: `external_id=str(p["id"])`, `date` (parse `transactionDate` `"%Y-%m-%d %H:%M:%S"` theo giờ `Asia/Ho_Chi_Minh` → UTC naive), `amount=p["transferAmount"]`, `content=p["content"]`, `reference=p["referenceCode"]`, `account_number=p["accountNumber"]`, `gateway=p["gateway"]`, `raw_payload=p`.
- `sepay_api.sepay_api_to_vals(t: dict) -> dict` cho bản ghi của `transactions/list` (`id, transaction_date, amount_in, transaction_content, reference_number, account_number, bank_brand_name`); bỏ qua dòng `amount_in == 0`. Dùng cùng `external_id` với webhook (id SePay giống nhau), nên dữ liệu kéo bù không bị trùng.
- `sepay_api.fetch_transactions(token: str, account_number: str, since_id: int) -> list[dict]`: `GET https://my.sepay.vn/userapi/transactions/list`, header `Authorization: Bearer <token>`, params `account_number`, `since_id`, `limit=100`, timeout 15s. Lỗi HTTP thì raise.
- Controller `POST /livestream/sepay/webhook/<int:provider_id>` (`type="http"`, `auth="public"`, `csrf=False`): kiểm tra header `Authorization == "Apikey " + provider.sepay_webhook_api_key` bằng `hmac.compare_digest`, sai thì trả 401. Đúng thì `_enqueue("sepay", payload | {"_provider_id": id})` → trả JSON `{"success": true}` mã 200.
- Cron `ir_cron_sepay_pull` (5 phút): `payment.provider._sepay_cron_pull()` cho mọi provider `sepay` đang bật → `fetch_transactions` → `_register_transfer` → cập nhật `sepay_last_pulled_id`.
- **Trước khi viết code:** đối chiếu tên trường webhook và API với tài liệu SePay hiện hành (docs.sepay.vn). Nếu khác với ở trên thì sửa payload mẫu và ghi chú vào commit.

- [ ] **Step 1: Test**
```python
def test_sepay_webhook_idempotent(self):  # HttpCase: POST payload 2 lần → 1 giao dịch; header sai → 401
def test_webhook_out_ignored(self): ...  # transferType "out" → không tạo
def test_webhook_auto_matches_order(self): ...  # content chứa livestream_payment_ref → matched, đơn amount_paid tăng
def test_cron_pull_dedup_with_webhook(self): ...  # patch fetch_transactions trả cùng id → không trùng; sepay_last_pulled_id cập nhật
def test_date_timezone(self): ...  # "2026-11-22 14:02:37" → UTC 07:02:37
```
- [ ] **Step 2:** Chạy với `<mods>=livestream_sepay`, `<tags>=/livestream_sepay` → FAIL. **Step 3:** Cài đặt. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(livestream_sepay): SePay provider, webhook and pull cron`.

---

### Task 9: `livestream_facebook`

**Files:**
- Create: `individual_addons/livestream_facebook/{__init__.py,__manifest__.py}`, `models/livestream_account.py`, `models/livestream_session.py`, `models/livestream_webhook_event.py`, `models/graph_api.py`, `controllers/main.py`, `data/ir_cron.xml`, `views/livestream_account_views.xml`
- Test: `tests/test_facebook.py`, `tests/payloads/feed_comment.json`, `tests/payloads/messages_text.json`, `tests/payloads/live_videos.json`

**Interfaces:**
- `GRAPH_VERSION`: hằng số trong `graph_api.py`, lấy bản ổn định mới nhất lúc viết code (kiểm tra trên developers.facebook.com).
- `livestream.account`: `platform` `selection_add=[("facebook","Facebook Page")]`. Field: `fb_app_id`, `fb_app_secret` (groups manager), `fb_verify_token` (manager, mặc định sinh ngẫu nhiên), `access_token` (Page token dài hạn). Nút `action_fb_subscribe()` gọi `POST /{page-id}/subscribed_apps?subscribed_fields=feed,live_videos,messages,messaging_postbacks`. Nút `action_fb_sync_live_videos()` gọi `GET /{page-id}/live_videos?fields=id,status,title,video{id},creation_time` rồi tạo/cập nhật `livestream.session` (`external_video_id`, `external_post_id`).
- Hook override cho `platform == 'facebook'`:
  - `_livestream_private_reply(comment, body, attachments) -> psid`: `POST /{page-id}/messages` body `{"recipient": {"comment_id": comment.external_id}, "message": {"text": body}}` → trả về `response["recipient_id"]`. Nếu có ảnh thì gửi ảnh sau, bằng Send API khi đã có psid.
  - `_livestream_send_message(customer, body, attachments)`: `{"recipient": {"id": psid}, "messaging_type": "RESPONSE", "message": {"text": body}}`; ảnh gửi bằng multipart `filedata` + `message={"attachment":{"type":"image","payload":{"is_reusable":false}}}`. Cửa sổ đóng → `UserError` (không tự dùng tag `HUMAN_AGENT` ở bản 1).
- Controller:
  - `GET /livestream/facebook/webhook`: `hub.mode == "subscribe"` và `hub.verify_token` khớp với một account → trả `hub.challenge` (text/plain), không thì 403.
  - `POST /livestream/facebook/webhook`: kiểm tra `X-Hub-Signature-256 == "sha256=" + HMAC_SHA256(app_secret, raw_body)` với account có `external_id == entry.id`, sai thì 403. Đúng thì `_enqueue("facebook", payload, account)` cho từng `entry` → 200 `EVENT_RECEIVED`.
- `_process_facebook(payload)`:
  - `changes[].field == "feed"` và `value.item == "comment"`, `verb == "add"`: tìm session theo `value.post_id` (khớp `external_post_id`, hoặc khớp phần sau dấu `_` với `external_video_id`). Không thấy session thì bỏ qua (comment ở bài thường). Thấy thì `_ingest(session, value.comment_id, value.from.id, value.from.name, value.message, created_time)`. Bỏ qua comment do chính Page viết (`from.id == page id`).
  - `changes[].field == "live_videos"`: `status == "live"` → tạo/cập nhật session `live`; `status in ("live_stopped", "vod")` → `ended`.
  - `messaging[]` có `message` và không có `is_echo`: tìm customer theo `psid == sender.id`. Không có thì tạo customer mới (`external_user_id = "psid:"+sender.id`, tên lấy qua `GET /{psid}?fields=name,profile_pic`) → `_receive_message(text, mid, attachments đã tải về)`.
- Cron `ir_cron_fb_pull_comments` (1 phút, chỉ phiên `live`): `GET /{video-id}/comments?filter=stream&order=reverse_chronological&fields=id,from,message,created_time&limit=100` → `_ingest`. Để bù khi webhook không tới được, như lúc chạy local chưa có tunnel.

- [ ] **Step 1: Test** (patch `graph_api._request`, không gọi mạng)
```python
def test_verify_challenge(self): ...       # HttpCase GET đúng token → challenge; sai → 403
def test_signature_required(self): ...     # POST thiếu/sai chữ ký → 403, đúng → event pending
def test_feed_comment_ingested(self): ...  # payload feed_comment.json → comment tag 69
def test_page_own_comment_ignored(self): ...
def test_private_reply_sets_psid(self): ...  # _request trả {"recipient_id": "PSID1"} → customer.psid
def test_inbound_message_creates_or_reuses_customer(self): ...
def test_echo_ignored(self): ...
def test_live_status_updates_session(self): ...
```
- [ ] **Step 2:** Chạy với `<mods>=livestream_facebook`, `<tags>=/livestream_facebook` → FAIL. **Step 3:** Cài đặt. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(livestream_facebook): page webhook, comments, Messenger send/receive`.

---

### Task 10: Hướng dẫn cài đặt & test thật, bản dịch

**Files:**
- Create: `individual_addons/livestream_sale/README.md`, `individual_addons/livestream_sale/i18n/vi.po` (và `livestream_sepay/i18n/vi.po`, `livestream_facebook/i18n/vi.po`)

- [ ] **Step 1:** README (tiếng Việt) gồm:
  1. Cài 3 module.
  2. Cấu hình sổ ngân hàng + tài khoản VietQR (bank BIC, `proxy_type=bank_acc`) + `action_setup_provider_journal`.
  3. SePay: API key/token, URL webhook, tiền tố mã thanh toán `LS`.
  4. Tạo Meta App ở Development mode, thêm tester, Page test chưa xuất bản, subscribe webhook.
  5. Tunnel: `cloudflared tunnel --url http://localhost:8069` (lưu ý `proxy_mode = True` khi chạy sau tunnel).
  6. Phát live bằng OBS/ffmpeg phát lặp file mp4 vào stream key.
  7. Kịch bản test end-to-end: comment `69 x2` → chốt → gửi QR → chuyển 2.000đ thật → đơn xanh.
  8. Chạy song song với Pancake.
- [ ] **Step 2:** Xuất `vi.po` (`odoo --i18n-export`) rồi dịch các chuỗi giao diện chính.
- [ ] **Step 3:** Chạy toàn bộ test 3 module → PASS.
- [ ] **Step 4:** Commit `docs: setup and live testing guide, Vietnamese translations`.
