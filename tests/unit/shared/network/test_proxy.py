import unittest
from types import SimpleNamespace
from unittest.mock import patch


class RequestsProxyPolicyTests(unittest.TestCase):
    def test_missing_explicit_proxy_disables_requests_environment_discovery(self):
        from shared.network_proxy import configure_requests_session, requests_proxy_mapping

        session = SimpleNamespace(trust_env=True)

        self.assertEqual(
            requests_proxy_mapping(None),
            {"http": None, "https": None, "all": None},
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
                "all": "http://127.0.0.1:8899",
            },
        )

    def test_direct_mapping_blocks_all_proxy_from_requests_environment(self):
        import requests

        from shared.network_proxy import requests_proxy_mapping

        with patch.dict("os.environ", {"ALL_PROXY": "http://127.0.0.1:65535"}, clear=True):
            settings = requests.Session().merge_environment_settings(
                "https://example.com/",
                requests_proxy_mapping(None),
                stream=False,
                verify=True,
                cert=None,
            )

        self.assertNotIn("all", {key.lower(): value for key, value in settings["proxies"].items() if value})


if __name__ == "__main__":
    unittest.main()
