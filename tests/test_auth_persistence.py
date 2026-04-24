import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils import auth


class _FakeCacheData:
    def __init__(self):
        self.clear_call_count = 0

    def clear(self):
        self.clear_call_count += 1


class _FakeStreamlit:
    def __init__(self, cookie_value=None, session_state=None):
        self.session_state = {} if session_state is None else dict(session_state)
        self.context = SimpleNamespace(cookies={})
        if cookie_value is not None:
            self.context.cookies[auth.AUTH_COOKIE_NAME] = cookie_value
        self.cache_data = _FakeCacheData()
        self.warning_messages = []
        self.caption_messages = []
        self.stop_call_count = 0

    def warning(self, message):
        self.warning_messages.append(message)

    def caption(self, message):
        self.caption_messages.append(message)

    def stop(self):
        self.stop_call_count += 1
        raise RuntimeError("streamlit stop")


class AuthPersistenceTest(unittest.TestCase):
    def test_dump_and_load_auth_cookie_payload_round_trips_tokens(self):
        cookie_value = auth._dump_auth_cookie_payload("access-1", "refresh-1")

        self.assertNotEqual(cookie_value, "")
        self.assertEqual(
            auth._load_auth_cookie_payload(cookie_value),
            {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
            },
        )

    def test_load_auth_cookie_payload_ignores_invalid_cookie(self):
        self.assertIsNone(auth._load_auth_cookie_payload(""))
        self.assertIsNone(auth._load_auth_cookie_payload("%7Bbroken"))
        self.assertIsNone(auth._load_auth_cookie_payload(auth._dump_auth_cookie_payload("", "refresh-1")))

    def test_init_auth_state_restores_session_from_cookie(self):
        cookie_value = auth._dump_auth_cookie_payload("access-1", "refresh-1")
        fake_st = _FakeStreamlit(cookie_value=cookie_value)

        with patch.object(auth, "st", fake_st):
            auth.init_auth_state()

        self.assertEqual(fake_st.session_state["sb_access_token"], "access-1")
        self.assertEqual(fake_st.session_state["sb_refresh_token"], "refresh-1")
        self.assertTrue(fake_st.session_state["sb_session_loaded"])
        self.assertFalse(fake_st.session_state["sb_skip_cookie_restore"])

    def test_init_auth_state_does_not_restore_cookie_after_explicit_logout(self):
        cookie_value = auth._dump_auth_cookie_payload("access-1", "refresh-1")
        fake_st = _FakeStreamlit(
            cookie_value=cookie_value,
            session_state={"sb_skip_cookie_restore": True},
        )

        with patch.object(auth, "st", fake_st):
            auth.init_auth_state()

        self.assertIsNone(fake_st.session_state["sb_access_token"])
        self.assertIsNone(fake_st.session_state["sb_refresh_token"])
        self.assertFalse(fake_st.session_state["sb_session_loaded"])
        self.assertTrue(fake_st.session_state["sb_skip_cookie_restore"])

    def test_sync_auth_cookie_writes_login_cookie(self):
        fake_st = _FakeStreamlit(
            session_state={
                "sb_access_token": "access-1",
                "sb_refresh_token": "refresh-1",
            }
        )
        rendered = {}

        def fake_components_html(source, height=0):
            rendered["source"] = source
            rendered["height"] = height

        with patch.object(auth, "st", fake_st), patch.object(auth, "components_html", fake_components_html):
            auth.sync_auth_cookie()

        self.assertEqual(rendered["height"], 0)
        self.assertIn(f"{auth.AUTH_COOKIE_NAME}=", rendered["source"])
        self.assertIn("Max-Age=2592000", rendered["source"])
        self.assertIn("SameSite=Lax", rendered["source"])

    def test_sync_auth_cookie_clears_cookie_when_logged_out(self):
        fake_st = _FakeStreamlit(
            session_state={
                "sb_access_token": None,
                "sb_refresh_token": None,
            }
        )
        rendered = {}

        def fake_components_html(source, height=0):
            rendered["source"] = source
            rendered["height"] = height

        with patch.object(auth, "st", fake_st), patch.object(auth, "components_html", fake_components_html):
            auth.sync_auth_cookie()

        self.assertIn(f"{auth.AUTH_COOKIE_NAME}=", rendered["source"])
        self.assertIn("Max-Age=0", rendered["source"])

    def test_require_authenticated_user_warns_and_stops_when_logged_out(self):
        fake_st = _FakeStreamlit()

        with patch.object(auth, "st", fake_st), patch.object(auth, "get_current_user", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "streamlit stop"):
                auth.require_authenticated_user()

        self.assertEqual(fake_st.warning_messages, ["このページを利用するにはログインしてください。"])
        self.assertEqual(fake_st.caption_messages, [])
        self.assertEqual(fake_st.stop_call_count, 1)


if __name__ == "__main__":
    unittest.main()
