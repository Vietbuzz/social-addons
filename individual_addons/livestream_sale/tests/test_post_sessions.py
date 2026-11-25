from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import LivestreamCommon


@tagged("post_install", "-at_install", "livestream")
class TestPostSessions(LivestreamCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Session = cls.env["livestream.session"]
        cls.Comment = cls.env["livestream.comment"]
        cls.Console = cls.env["livestream.console"]

    def test_post_session_get_or_create(self):
        s1 = self.Session._get_or_create_post(self.ls_account, "PAGE_POST1", "Áo thun mới về", "https://fb.com/p/1")
        s2 = self.Session._get_or_create_post(self.ls_account, "PAGE_POST1", "other", None)
        self.assertEqual(s1, s2)
        self.assertEqual((s1.source_type, s1.state, s1.name, s1.permalink_url),
                         ("post", "live", "Áo thun mới về", "https://fb.com/p/1"))
        self.assertEqual(self.session.source_type, "live")
        s1.action_end()
        self.assertEqual(self.Session._get_or_create_post(self.ls_account, "PAGE_POST1", "x", None), s1)

    def test_post_name_truncated(self):
        s = self.Session._get_or_create_post(self.ls_account, "P2", "x" * 200, None)
        self.assertLessEqual(len(s.name), 60)

    def test_ingest_updates_last_comment_at(self):
        before = fields.Datetime.now() - timedelta(seconds=1)
        self.Comment._ingest(self.session, "c1", "u1", "A", "69", fields.Datetime.now())
        self.assertGreaterEqual(self.session.last_comment_at, before)

    def test_load_all_only_open_sessions(self):
        post = self.Session._get_or_create_post(self.ls_account, "P3", "Bài 3", None)
        ended = self.Session._get_or_create_post(self.ls_account, "P4", "Bài 4", None)
        c_live = self.Comment._ingest(self.session, "c1", "u1", "A", "69", fields.Datetime.now())
        c_post = self.Comment._ingest(post, "c2", "u2", "B", "còn hàng không", fields.Datetime.now())
        c_ended = self.Comment._ingest(ended, "c3", "u3", "C", "giá?", fields.Datetime.now())
        ended.action_end()
        data = self.Console.load("all")
        ids = {c["id"] for c in data["comments"]}
        self.assertEqual(ids & {c_live.id, c_post.id, c_ended.id}, {c_live.id, c_post.id})
        self.assertEqual(data["session"]["id"], "all")
        self.assertIn(self.ls_account.id, data["session"]["account_ids"])
        post_item = next(c for c in data["comments"] if c["id"] == c_post.id)
        self.assertEqual((post_item["source_type"], post_item["session_name"]), ("post", "Bài 3"))
        self.assertEqual(post_item["account_id"], self.ls_account.id)
        self.assertTrue(all("source_type" in s for s in data["sessions"]))

    def test_load_default_is_all(self):
        self.assertEqual(self.Console.load(False)["session"]["id"], "all")

    def test_load_more_comments_all(self):
        post = self.Session._get_or_create_post(self.ls_account, "P5", "Bài 5", None)
        c1 = self.Comment._ingest(post, "c1", "u1", "A", "x", fields.Datetime.now())
        c2 = self.Comment._ingest(self.session, "c2", "u2", "B", "69", fields.Datetime.now())
        res = self.Console.load_more_comments("all", c2.id + 1, False)
        self.assertEqual({c["id"] for c in res} & {c1.id, c2.id}, {c1.id, c2.id})

    def test_order_panel_tags_from_comment_session(self):
        post = self.Session._get_or_create_post(self.ls_account, "P6", "Bài 6", "https://fb.com/p/6")
        comment = self.Comment._ingest(post, "c1", "u1", "A", "còn size M?", fields.Datetime.now())
        panel = self.Console.order_panel(comment.id)
        self.assertEqual(panel["tags"], [])
        self.assertEqual(panel["permalink_url"], "https://fb.com/p/6")
        live_comment = self.Comment._ingest(self.session, "c2", "u2", "B", "69", fields.Datetime.now())
        self.assertEqual([t["code"] for t in self.Console.order_panel(live_comment.id)["tags"]], ["69"])

    def test_search_products_sale_ok_only(self):
        self.env["product.product"].create({"name": "Áo khoác nội bộ", "sale_ok": False})
        other_company = self.env["res.company"].create({"name": "Other Co"})
        self.env["product.product"].create({"name": "Áo khoác công ty khác", "company_id": other_company.id})
        jacket = self.env["product.product"].create({"name": "Áo khoác gió", "lst_price": 250000})
        res = self.Console.search_products("áo khoác")
        self.assertEqual([r["product_id"] for r in res], [jacket.id])
        self.assertEqual(res[0]["price_unit"], 250000)
        self.assertEqual(self.Console.search_products("a"), [])  # too short

    def test_last_comment_at_throttled(self):
        self.Comment._ingest(self.session, "t1", "u1", "A", "69", fields.Datetime.now())
        first = self.session.last_comment_at
        self.Comment._ingest(self.session, "t2", "u2", "B", "69", fields.Datetime.now())
        self.assertEqual(self.session.last_comment_at, first)

    def test_event_transient_error_retried(self):
        Event = self.env["livestream.webhook.event"]
        ev = Event._enqueue("simulator", {"kind": "comment", "session_id": self.session.id, "comment_id": "x",
                                          "user_id": "u", "name": "n", "message": "69"}, self.ls_account)
        transient = patch.object(type(Event), "_process_simulator", side_effect=RuntimeError("could not serialize"))
        with transient, mute_logger("odoo.addons.livestream_sale.models.livestream_webhook_event"):
            ev._process()
        self.assertEqual((ev.state, ev.attempts), ("pending", 1))
        with transient, mute_logger("odoo.addons.livestream_sale.models.livestream_webhook_event"):
            ev._process()
            ev._process()
        self.assertEqual((ev.state, ev.attempts), ("error", 3))

    def test_load_all_excludes_other_company(self):
        other_company = self.env["res.company"].create({"name": "Other Shop"})
        other_account = self.env["livestream.account"].create({
            "name": "Other", "platform": "simulator", "external_id": "other", "company_id": other_company.id,
        })
        other = self.Session.create({"name": "Other live", "account_id": other_account.id, "state": "live"})
        self.Comment._ingest(other, "o1", "u9", "Z", "69", fields.Datetime.now())
        data = self.Console.with_context(allowed_company_ids=[self.company_data["company"].id]).load("all")
        self.assertNotIn(other.id, [s["id"] for s in data["sessions"]])
        self.assertNotIn("o1", [c["message"] for c in data["comments"]])

    def test_search_products_uses_given_company(self):
        other_company = self.env["res.company"].create({"name": "Other Co 2"})
        self.env["product.product"].create({"name": "Mũ len công ty 2", "company_id": other_company.id})
        self.env.user.company_ids |= other_company
        res = self.Console.with_context(allowed_company_ids=[other_company.id, self.company_data["company"].id]) \
            .search_products("mũ len", company_id=self.company_data["company"].id)
        self.assertEqual(res, [])

    def test_console_format_has_session_state(self):
        c = self.Comment._ingest(self.session, "s1", "u1", "A", "69", fields.Datetime.now())
        self.assertEqual(c._console_format()["session_state"], "live")
