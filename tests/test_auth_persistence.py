import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils import auth


class _FakeCacheData:
    def __init__(self):
        self.clear_call_count = 0

    def clear(self):
        self.clear_call_count += 1


class _FakeCookieManager(dict):
    def __init__(self, *, ready=True, initial=None):
        super().__init__(initial or {})
        self._ready = ready
        self.save_call_count = 0

    def ready(self):
        return self._ready

    def save(self):
        self.save_call_count += 1


class _FakeStreamlit:
    def __init__(self, session_state=None):
        self.session_state = {} if session_state is None else dict(session_state)
        self.context = SimpleNamespace(cookies={})
        self.cache_data = _FakeCacheData()
        self.stop_call_count = 0
        self.secrets = {}

    def stop(self):
        self.stop_call_count += 1
        raise RuntimeError("st.stop")


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

    def test_init_auth_state_restores_session_from_cookie_manager(self):
        cookie_value = auth._dump_auth_cookie_payload("access-1", "refresh-1")
        fake_st = _FakeStreamlit()
        fake_cookies = _FakeCookieManager(initial={auth.AUTH_COOKIE_NAME: cookie_value})

        with patch.object(auth, "st", fake_st), patch.object(auth, "_get_cookie_manager", return_value=fake_cookies):
            auth.init_auth_state()

        self.assertEqual(fake_st.session_state["sb_access_token"], "access-1")
        self.assertEqual(fake_st.session_state["sb_refresh_token"], "refresh-1")
        self.assertTrue(fake_st.session_state["sb_session_loaded"])
        self.assertFalse(fake_st.session_state["sb_skip_cookie_restore"])

    def test_init_auth_state_stops_until_cookie_manager_is_ready(self):
        fake_st = _FakeStreamlit()
        fake_cookies = _FakeCookieManager(ready=False)

        with patch.object(auth, "st", fake_st), patch.object(auth, "_get_cookie_manager", return_value=fake_cookies):
            with self.assertRaisesRegex(RuntimeError, "st.stop"):
                auth.init_auth_state()

        self.assertEqual(fake_st.stop_call_count, 1)

    def test_init_auth_state_does_not_restore_cookie_after_explicit_logout(self):
        cookie_value = auth._dump_auth_cookie_payload("access-1", "refresh-1")
        fake_st = _FakeStreamlit(session_state={"sb_skip_cookie_restore": True})
        fake_cookies = _FakeCookieManager(initial={auth.AUTH_COOKIE_NAME: cookie_value})

        with patch.object(auth, "st", fake_st), patch.object(auth, "_get_cookie_manager", return_value=fake_cookies):
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
        fake_cookies = _FakeCookieManager()

        with patch.object(auth, "st", fake_st), patch.object(auth, "_get_cookie_manager", return_value=fake_cookies):
            auth.sync_auth_cookie()

        self.assertEqual(
            fake_cookies[auth.AUTH_COOKIE_NAME],
            auth._dump_auth_cookie_payload("access-1", "refresh-1"),
        )
        self.assertEqual(fake_cookies.save_call_count, 1)

    def test_sync_auth_cookie_clears_cookie_when_logged_out(self):
        fake_st = _FakeStreamlit(
            session_state={
                "sb_access_token": None,
                "sb_refresh_token": None,
            }
        )
        fake_cookies = _FakeCookieManager(initial={auth.AUTH_COOKIE_NAME: "cookie-value"})

        with patch.object(auth, "st", fake_st), patch.object(auth, "_get_cookie_manager", return_value=fake_cookies):
            auth.sync_auth_cookie()

        self.assertNotIn(auth.AUTH_COOKIE_NAME, fake_cookies)
        self.assertEqual(fake_cookies.save_call_count, 1)

    def test_sync_auth_cookie_returns_until_cookie_manager_is_ready(self):
        fake_st = _FakeStreamlit(
            session_state={
                "sb_access_token": "access-1",
                "sb_refresh_token": "refresh-1",
            }
        )
        fake_cookies = _FakeCookieManager(ready=False)

        with patch.object(auth, "st", fake_st), patch.object(auth, "_get_cookie_manager", return_value=fake_cookies):
            auth.sync_auth_cookie()

        self.assertEqual(fake_cookies.save_call_count, 0)
        self.assertEqual(dict(fake_cookies), {})

    def test_get_cookie_password_prefers_secret_then_env_then_supabase(self):
        fake_st = _FakeStreamlit()
        fake_st.secrets = {
            auth.AUTH_COOKIE_PASSWORD_SECRET_KEY: "secret-password",
            "supabase": {"anon_key": "anon-key"},
        }

        with patch.object(auth, "st", fake_st), patch.dict("os.environ", {auth.AUTH_COOKIE_PASSWORD_SECRET_KEY: "env-password"}, clear=False):
            password = auth._get_cookie_password()

        self.assertEqual(password, "secret-password")

        fake_st.secrets = {"supabase": {"anon_key": "anon-key"}}
        with patch.object(auth, "st", fake_st), patch.dict("os.environ", {auth.AUTH_COOKIE_PASSWORD_SECRET_KEY: "env-password"}, clear=False):
            password = auth._get_cookie_password()

        self.assertEqual(password, "env-password")

        with patch.object(auth, "st", fake_st), patch.dict("os.environ", {}, clear=True):
            password = auth._get_cookie_password()

        self.assertEqual(password, "anon-key")

    def test_get_cookie_password_raises_when_missing(self):
        fake_st = _FakeStreamlit()
        fake_st.secrets = {}

        with patch.object(auth, "st", fake_st), patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, auth.AUTH_COOKIE_PASSWORD_SECRET_KEY):
                auth._get_cookie_password()

    def test_get_current_user_keeps_auth_state_on_transient_failure(self):
        fake_st = _FakeStreamlit(
            session_state={
                "sb_access_token": "access-1",
                "sb_refresh_token": "refresh-1",
            }
        )

        with patch.object(auth, "st", fake_st), patch.object(auth, "get_supabase_client", side_effect=RuntimeError("temporary")):
            user = auth.get_current_user()

        self.assertIsNone(user)
        self.assertEqual(fake_st.session_state["sb_access_token"], "access-1")
        self.assertEqual(fake_st.session_state["sb_refresh_token"], "refresh-1")


if __name__ == "__main__":
    unittest.main()
