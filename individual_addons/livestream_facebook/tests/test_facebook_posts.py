import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.livestream_facebook.models import graph_api

from .common import FacebookCommon, raw


def post_payload(post_id="PAGE1_POST7", comment_id="POST7_C1", author=("FBUSER5", "Tran Thi B"), message="còn size M không shop"):
    payload = json.loads(raw("feed_comment.json"))
    value = payload["entry"][0]["changes"][0]["value"]
    value.update({
        "post_id": post_id, "parent_id": post_id, "comment_id": comment_id, "message": message,
        "from": {"id": author[0], "name": author[1]},
        "post": {"status_type": "added_photos", "is_published": True, "id": post_id},
    })
    return json.dumps(payload).encode()


@tagged("post_install", "-at_install", "livestream")
class TestFacebookPosts(FacebookCommon):
    def _post_comment(self, body):
        self.assertEqual(self._post(body).status_code, 200)
        self.Event._cron_process()

    def _sessions(self):
        return self.env["livestream.session"].search([("account_id", "=", self.fb.id), ("source_type", "=", "post")])

    def test_post_comment_creates_post_session_not_live(self):
        info = {"message": "Áo khoác gió mới về, inbox shop nhé", "permalink_url": "https://facebook.com/PAGE1/posts/POST7"}
        with patch.object(graph_api, "_request", return_value=info) as req:
            self._post_comment(post_payload())
        self.assertEqual(req.call_args.args[1], "PAGE1_POST7")
        post = self._sessions()
        self.assertEqual(len(post), 1)
        self.assertEqual((post.state, post.external_post_id, post.permalink_url),
                         ("live", "PAGE1_POST7", "https://facebook.com/PAGE1/posts/POST7"))
        self.assertTrue(post.name.startswith("Áo khoác gió"))
        comment = self.Comment.search([("external_id", "=", "POST7_C1")])
        self.assertEqual(comment.session_id, post)
        self.assertFalse(self.Comment.search([("session_id", "=", self.fb_session.id)]))

    def test_post_name_fallback_on_graph_error(self):
        with patch.object(graph_api, "_request", side_effect=UserError("no permission")):
            self._post_comment(post_payload())
        post = self._sessions()
        self.assertTrue(post.name)
        self.assertTrue(self.Comment.search([("external_id", "=", "POST7_C1")]))

    def test_second_comment_reuses_post_session(self):
        with patch.object(graph_api, "_request", return_value={"message": "Bài 7"}) as req:
            self._post_comment(post_payload())
            self._post_comment(post_payload(comment_id="POST7_C2", author=("FBUSER6", "Le C")))
        self.assertEqual(req.call_count, 1)
        self.assertEqual(len(self._sessions()), 1)
        self.assertEqual(self.Comment.search_count([("session_id", "=", self._sessions().id)]), 2)

    def test_comment_on_ended_post_ignored(self):
        with patch.object(graph_api, "_request", return_value={"message": "Bài 7"}):
            self._post_comment(post_payload())
        self._sessions().action_end()
        with patch.object(graph_api, "_request", return_value={"message": "Bài 7"}):
            self._post_comment(post_payload(comment_id="POST7_C3"))
        self.assertFalse(self.Comment.search([("external_id", "=", "POST7_C3")]))
        self.assertEqual(len(self._sessions()), 1)

    def test_page_reply_on_post_ignored(self):
        with patch.object(graph_api, "_request", return_value={"message": "Bài 7"}):
            self._post_comment(post_payload(author=("PAGE1", "Shop")))
        self.assertFalse(self._sessions())
