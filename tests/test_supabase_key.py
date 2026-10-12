import base64
import json
import unittest
from unittest.mock import patch

from core import supabase_client as sc


def fake_jwt(role):
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'HS256'})}.{b64({'role': role, 'iss': 'supabase'})}.sig"


class KeySelectionTest(unittest.TestCase):
    def test_service_role_override(self):
        env = {"SUPABASE_SERVICE_ROLE_KEY": fake_jwt("service_role"), "SUPABASE_KEY": fake_jwt("anon")}
        key, name = sc.select_key(env)
        self.assertEqual(name, "SUPABASE_SERVICE_ROLE_KEY")
        self.assertEqual(sc.key_role(key), "service_role")

    def test_anon_is_default(self):
        env = {"SUPABASE_SERVICE_ROLE_KEY": "  ", "SUPABASE_KEY": fake_jwt("anon")}
        key, name = sc.select_key(env)
        self.assertEqual(name, "SUPABASE_KEY")
        self.assertEqual(sc.key_role(key), "anon")

    def test_none(self):
        self.assertEqual(sc.select_key({}), (None, None))
        self.assertEqual(sc.describe_key({}), "Supabase key: not set")

    def test_role_unknown_for_garbage(self):
        self.assertEqual(sc.key_role("dummy-key"), "unknown")
        self.assertEqual(sc.key_role("a.!!!.c"), "unknown")

    def test_describe_never_contains_key(self):
        key = fake_jwt("service_role")
        text = sc.describe_key({"SUPABASE_SERVICE_ROLE_KEY": key})
        self.assertIn("role=service_role", text)
        self.assertNotIn(key, text)
        self.assertNotIn(key.split(".")[1], text)
        anon = sc.describe_key({"SUPABASE_KEY": fake_jwt("anon")})
        self.assertEqual(anon, "Supabase key: SUPABASE_KEY (role=anon)")

    def test_create_client_uses_selected_key(self):
        import supabase as supabase_module
        calls = []
        with patch.object(supabase_module, "create_client", lambda u, k: calls.append((u, k)) or "client"):
            env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "srv", "SUPABASE_KEY": "anon"}
            self.assertEqual(sc.create_client_from_env(env), "client")
            self.assertIsNone(sc.create_client_from_env({"SUPABASE_KEY": "anon"}))
        self.assertEqual(calls, [("https://x.supabase.co", "srv")])

    def test_get_client_shared_and_logged_once(self):
        import supabase as supabase_module
        sc._reset_for_tests()
        made = []
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": fake_jwt("anon")}
        try:
            with patch.dict("os.environ", env, clear=True), \
                 patch.object(supabase_module, "create_client", lambda u, k: made.append(1) or object()), \
                 patch("builtins.print") as p:
                a, b = sc.get_client(), sc.get_client()
            self.assertIs(a, b)
            self.assertEqual(len(made), 1)
            self.assertEqual(p.call_count, 1)
        finally:
            sc._reset_for_tests()


if __name__ == "__main__":
    unittest.main()
