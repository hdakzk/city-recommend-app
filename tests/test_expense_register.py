import unittest
from unittest.mock import patch

from pages import expense_register


class _FakeStreamlit:
    def __init__(self, session_state=None):
        self.session_state = {} if session_state is None else dict(session_state)


class ExpenseRegisterTest(unittest.TestCase):
    def test_build_auth_diagnostics_returns_expected_flags(self):
        fake_st = _FakeStreamlit(
            session_state={
                "sb_access_token": "access-1",
                "sb_refresh_token": "refresh-1",
                "sb_session_loaded": True,
            }
        )

        with patch.object(expense_register, "st", fake_st):
            diagnostics = expense_register.build_auth_diagnostics("user-1")

        self.assertEqual(
            diagnostics,
            {
                "app_user_id": "user-1",
                "access_token_exists": True,
                "refresh_token_exists": True,
                "session_loaded": True,
                "page_auth_check_passed": True,
            },
        )

    def test_build_auth_diagnostics_handles_missing_session_boundary(self):
        fake_st = _FakeStreamlit()

        with patch.object(expense_register, "st", fake_st):
            diagnostics = expense_register.build_auth_diagnostics("")

        self.assertEqual(diagnostics["app_user_id"], "")
        self.assertFalse(diagnostics["access_token_exists"])
        self.assertFalse(diagnostics["refresh_token_exists"])
        self.assertFalse(diagnostics["session_loaded"])
        self.assertFalse(diagnostics["page_auth_check_passed"])


if __name__ == "__main__":
    unittest.main()
