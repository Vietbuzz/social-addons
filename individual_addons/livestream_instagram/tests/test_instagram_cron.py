from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.livestream_facebook.models import graph_api

from .common import InstagramCommon


def fake_graph(live_ids, comments):
    def _fake(method, path, token, **kw):
        if path.endswith("/live_media"):
            return {"data": [{"id": mid, "media_product_type": "LIVE"} for mid in live_ids]}
        if path.endswith("/ordered_comments"):
            return {"data": comments}
        return {}
    return _fake


@tagged("post_install", "-at_install", "livestream")
class TestInstagramCron(InstagramCommon):
    COMMENTS = [
        {"id": "IGC21", "text": "69 x2", "timestamp": "2026-11-24T07:00:01+0000", "from": {"id": "U21", "username": "a21"}},
        {"id": "IGC20", "text": "12", "timestamp": "2026-11-24T07:00:00+0000", "from": {"id": "U20", "username": "b20"}},
        {"id": "IGC22", "text": "cam on", "timestamp": "2026-11-24T07:00:02+0000", "from": {"id": "IG1", "username": "shop"}},
    ]

    def _sessions(self):
        return self.env["livestream.session"].search([("account_id", "=", self.ig.id)])

    def test_cron_creates_live_session_and_pulls_comments(self):
        with patch.object(graph_api, "_request", side_effect=fake_graph(["MEDIA5"], self.COMMENTS)) as req:
            self.env["livestream.session"]._ig_cron_sync()
            self.env["livestream.session"]._ig_cron_sync()  # second run: no duplicates
        paths = [c.args[1] for c in req.call_args_list]
        self.assertIn("IG1/live_media", paths)
        self.assertIn("MEDIA5/ordered_comments", paths)
        session = self._sessions()
        self.assertEqual((session.external_video_id, session.state), ("MEDIA5", "live"))
        comments = self.Comment.search([("session_id", "=", session.id)])
        self.assertEqual(sorted(comments.mapped("external_id")), ["IGC20", "IGC21"])  # shop's own skipped
        self.assertEqual(comments.filtered(lambda c: c.external_id == "IGC21").customer_id.name, "a21")

    def test_cron_ends_missing_live(self):
        with patch.object(graph_api, "_request", side_effect=fake_graph(["MEDIA5"], [])):
            self.env["livestream.session"]._ig_cron_sync()
        for _i in range(2):  # two consecutive misses end the live
            with patch.object(graph_api, "_request", side_effect=fake_graph([], [])):
                self.env["livestream.session"]._ig_cron_sync()
        self.assertEqual(self._sessions().state, "ended")

    def test_cron_bad_row_does_not_lose_batch(self):
        Comment = self.registry["livestream.comment"]
        real = Comment._ingest

        def flaky(model, session, external_id, *args, **kwargs):
            if external_id == "IGC20":
                raise ValueError("race")
            return real(model, session, external_id, *args, **kwargs)

        with patch.object(graph_api, "_request", side_effect=fake_graph(["MEDIA5"], self.COMMENTS)), \
                patch.object(Comment, "_ingest", autospec=True, side_effect=flaky), \
                mute_logger("odoo.addons.livestream_instagram.models.livestream_session"):
            self.env["livestream.session"]._ig_cron_sync()
        self.assertTrue(self.Comment.search([("external_id", "=", "IGC21")]))

    def test_cron_skips_account_without_token(self):
        self.ig.access_token = False
        with patch.object(graph_api, "_request") as req:
            self.env["livestream.session"]._ig_cron_sync()
        req.assert_not_called()
