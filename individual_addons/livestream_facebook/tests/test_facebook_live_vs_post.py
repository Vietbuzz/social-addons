import json
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.livestream_facebook.models import graph_api

from .common import FacebookCommon, raw


def feed(post_id, comment_id, status_type="added_video"):
    payload = json.loads(raw("feed_comment.json"))
    value = payload["entry"][0]["changes"][0]["value"]
    value.update({"post_id": post_id, "parent_id": post_id, "comment_id": comment_id,
                  "post": {"status_type": status_type, "is_published": True, "id": post_id}})
    return json.dumps(payload).encode()


def graph(live_video_id="LIVE9", video_id="VID9", status="LIVE"):
    def _fake(method, path, token, **kw):
        if path == f"{live_video_id}":
            return {"id": live_video_id, "video": {"id": video_id}, "title": "Live tối nay"}
        if path.endswith("/live_videos"):
            return {"data": [{"id": live_video_id, "status": status, "video": {"id": video_id}}]}
        return {"message": "some post"}
    return _fake


@tagged("post_install", "-at_install", "livestream")
class TestFacebookLiveVsPost(FacebookCommon):
    def _send(self, body):
        self.assertEqual(self._post(body).status_code, 200)
        self.Event._cron_process()

    def _sessions(self, source_type):
        return self.env["livestream.session"].search([("account_id", "=", self.fb.id), ("source_type", "=", source_type)])

    def test_live_from_webhook_resolves_video_and_gets_comments(self):
        webhook_live = {"object": "page", "entry": [{"id": "PAGE1", "time": 1, "changes": [
            {"field": "live_videos", "value": {"id": "LIVE9", "status": "live"}}]}]}
        with patch.object(graph_api, "_request", side_effect=graph()):
            self._send(json.dumps(webhook_live).encode())
            self._send(feed("PAGE1_VID9", "VID9_C1"))
        live = self.env["livestream.session"].search([("external_video_id", "=", "LIVE9")])
        self.assertEqual(live.external_post_id, "PAGE1_VID9")
        self.assertEqual(self.Comment.search([("external_id", "=", "VID9_C1")]).session_id, live)
        self.assertFalse(self._sessions("post").filtered(lambda s: s.external_post_id == "PAGE1_VID9"))

    def test_comment_before_sync_goes_to_live_found_via_graph(self):
        with patch.object(graph_api, "_request", side_effect=graph()):
            self._send(feed("PAGE1_VID9", "VID9_C1"))
        live = self.env["livestream.session"].search([("external_video_id", "=", "LIVE9")])
        self.assertEqual(live.source_type, "live")
        self.assertEqual(self.Comment.search([("external_id", "=", "VID9_C1")]).session_id, live)
        self.assertFalse(self._sessions("post").filtered(lambda s: s.external_post_id == "PAGE1_VID9"))

    def test_existing_post_session_merged_when_live_learns_video(self):
        post = self.env["livestream.session"]._get_or_create_post(self.fb, "PAGE1_VID9", "early", None)
        c = self.Comment._ingest(post, "VID9_C0", "U0", "A", "69", self.env.cr.now())
        with patch.object(graph_api, "_request", side_effect=graph()):
            live = self.env["livestream.session"]._fb_upsert_live(self.fb, {"id": "LIVE9", "status": "LIVE"})
        self.assertEqual(c.session_id, live)
        self.assertEqual(post.state, "ended")

    def test_regular_video_post_still_post_session(self):
        def _fake(method, path, token, **kw):
            if path.endswith("/live_videos"):
                return {"data": []}
            return {"message": "Video giới thiệu sản phẩm"}
        with patch.object(graph_api, "_request", side_effect=_fake):
            self._send(feed("PAGE1_VID77", "VID77_C1"))
        self.assertEqual(self.Comment.search([("external_id", "=", "VID77_C1")]).session_id.source_type, "post")
