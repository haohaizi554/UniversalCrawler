import unittest
from types import SimpleNamespace


class RequestsProxyPolicyTests(unittest.TestCase):
    def test_missing_explicit_proxy_disables_requests_environment_discovery(self):
        from shared.network_proxy import configure_requests_session, requests_proxy_mapping

        session = SimpleNamespace(trust_env=True)

        self.assertEqual(
            requests_proxy_mapping(None),
            {"http": None, "https": None},
        )
        self.assertIs(configure_requests_session(session), session)
        self.assertFalse(session.trust_env)

    def test_explicit_proxy_is_forwarded_for_both_http_schemes(self):
        from shared.network_proxy import requests_proxy_mapping

        self.assertEqual(
            requests_proxy_mapping("http://127.0.0.1:8899"),
            {
                "http": "http://127.0.0.1:8899",
                "https": "http://127.0.0.1:8899",
            },
        )


if __name__ == "__main__":
    unittest.main()
