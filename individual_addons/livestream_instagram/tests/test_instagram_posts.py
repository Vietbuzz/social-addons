import json
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.livestream_facebook.models import graph_api

from .common import InstagramCommon


def ig_post_comment(comment_id="IGP1", media_id="MEDIA_POST1", product_type="FEED", text="còn size M không ạ"):
    return json.dumps({"object": "instagram", "entry": [{"id": "IG1", "time": 1795330000, "changes": [{
        "field": "comments", "value": {
            "from": {"id": "IGSID5", "username": "tranthib"}, "comment_id": comment_id, "text": text,
            "media": {"id": media_id, "media_product_type": product_type}}}]}]}).encode()


@tagged("post_install", "-at_install", "livestream")
class TestInstagramPosts(InstagramCommon):
    def _posts(self):
        return self.env["livestream.session"].search([("account_id", "=", self.ig.id), ("source_type", "=", "post")])

    def test_ig_post_comment_creates_post_session(self):
        info = {"caption": "Váy hoa mùa hè 🌸 inbox shop", "permalink": "https://instagram.com/p/abc"}
        with patch.object(graph_api, "_request", return_value=info) as req:
            self._deliver_body(ig_post_comment())
            self._deliver_body(ig_post_comment(comment_id="IGP2"))
        self.assertEqual(req.call_count, 1)
        self.assertEqual(req.call_args.args[1], "MEDIA_POST1")
        post = self._posts()
        self.assertEqual((post.external_post_id, post.permalink_url, post.state),
                         ("MEDIA_POST1", "https://instagram.com/p/abc", "live"))
        self.assertTrue(post.name.startswith("Váy hoa"))
        self.assertEqual(self.Comment.search_count([("session_id", "=", post.id)]), 2)

    def test_ig_live_product_type_goes_to_live_session(self):
        with patch.object(graph_api, "_request", return_value={}):
            self._deliver_body(ig_post_comment(media_id="MEDIA_LIVE9", product_type="LIVE", text="69"))
        self.assertFalse(self._posts())
        live = self.env["livestream.session"].search([("external_video_id", "=", "MEDIA_LIVE9")])
        self.assertEqual(live.source_type, "live")

    def test_ig_comment_on_ended_post_ignored(self):
        with patch.object(graph_api, "_request", return_value={"caption": "Bài"}):
            self._deliver_body(ig_post_comment())
        self._posts().action_end()
        with patch.object(graph_api, "_request", return_value={"caption": "Bài"}):
            self._deliver_body(ig_post_comment(comment_id="IGP3"))
        self.assertEqual(len(self._posts()), 1)
        self.assertFalse(self.Comment.search([("external_id", "=", "IGP3")]))

    def test_ig_private_reply_on_post_allowed(self):
        with patch.object(graph_api, "_request", return_value={"caption": "Bài"}):
            self._deliver_body(ig_post_comment())
        comment = self.Comment.search([("external_id", "=", "IGP1")])
        comment.session_id.action_end()  # a post closed by the manager still allows replying to existing comments
        channel = self.env["discuss.channel"].browse(comment.action_open_conversation()["channel_id"])
        with patch.object(graph_api, "_request", return_value={"recipient_id": "IGSID5"}) as req:
            channel.message_post(body="Chào bạn", message_type="comment", subtype_xmlid="mail.mt_comment")
        self.assertEqual(req.call_args.kwargs["json"]["recipient"], {"comment_id": "IGP1"})
        self.assertEqual(comment.customer_id.psid, "IGSID5")

    def test_cron_does_not_end_post_sessions(self):
        with patch.object(graph_api, "_request", return_value={"caption": "Bài"}):
            self._deliver_body(ig_post_comment())

        def no_live(method, path, token, **kw):
            return {"data": []}

        for _i in range(3):
            with patch.object(graph_api, "_request", side_effect=no_live):
                self.env["livestream.session"]._ig_cron_sync()
        self.assertEqual(self._posts().state, "live")
