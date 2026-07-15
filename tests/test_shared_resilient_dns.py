import socket
import unittest
from types import SimpleNamespace


class ResilientDNSResolverTests(unittest.TestCase):
    @staticmethod
    def _system_resolver_that_fails_for(target_host: str):
        calls: list[str] = []

        def resolve(host, port, family=0, type=0, proto=0, flags=0):
            normalized = str(host)
            calls.append(normalized)
            if normalized == target_host:
                raise socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure")
            return socket.getaddrinfo(host, port, family, type, proto, flags)

        return resolve, calls

    def test_system_dns_failure_uses_doh_answer_and_reuses_it_for_transport(self):
        from shared.resilient_dns import ResilientDNSResolver

        system_resolver, system_calls = self._system_resolver_that_fails_for("cdn.example.net")
        doh_calls: list[tuple[str, int]] = []

        def doh_lookup(host: str, family: int):
            doh_calls.append((host, family))
            return ("93.184.216.34",), 60.0

        resolver = ResilientDNSResolver(
            system_resolver=system_resolver,
            doh_lookup=doh_lookup,
        )

        first = resolver("cdn.example.net", 443, type=socket.SOCK_STREAM)
        second = resolver("cdn.example.net", 443, type=socket.SOCK_STREAM)

        self.assertEqual(first[0][4][0], "93.184.216.34")
        self.assertEqual(second[0][4][0], "93.184.216.34")
        self.assertEqual(system_calls.count("cdn.example.net"), 1)
        self.assertEqual(doh_calls, [("cdn.example.net", socket.AF_UNSPEC)])

    def test_reserved_or_local_names_never_leave_the_system_resolver(self):
        from shared.resilient_dns import ResilientDNSResolver

        doh_calls: list[tuple[str, int]] = []

        def system_resolver(*_args, **_kwargs):
            raise socket.gaierror(socket.EAI_NONAME, "not found")

        def doh_lookup(host: str, family: int):
            doh_calls.append((host, family))
            return ("93.184.216.34",), 60.0

        resolver = ResilientDNSResolver(
            system_resolver=system_resolver,
            doh_lookup=doh_lookup,
        )

        for host in ("localhost", "printer.local", "missing.example"):
            with self.subTest(host=host), self.assertRaises(socket.gaierror):
                resolver(host, 443, type=socket.SOCK_STREAM)

        self.assertEqual(doh_calls, [])

    def test_private_doh_answer_is_still_rejected_by_public_url_policy(self):
        from shared.resilient_dns import ResilientDNSResolver
        from shared.runtime_options import DomainPolicyEngine, DomainPolicyViolation

        system_resolver, _calls = self._system_resolver_that_fails_for("cdn.example.net")
        resolver = ResilientDNSResolver(
            system_resolver=system_resolver,
            doh_lookup=lambda _host, _family: (("127.0.0.1",), 60.0),
        )
        policy = DomainPolicyEngine(resolver=resolver)

        with self.assertRaisesRegex(DomainPolicyViolation, "本地或内网"):
            policy.require_public_url("https://cdn.example.net/video.m4s")

    def test_recent_system_failure_skips_broken_dns_for_the_next_hostname(self):
        from shared.resilient_dns import ResilientDNSResolver

        queried_hosts: list[str] = []

        def system_resolver(host, port, family=0, type=0, proto=0, flags=0):
            normalized = str(host)
            queried_hosts.append(normalized)
            if normalized in {"first.example.net", "second.example.net"}:
                raise socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure")
            return socket.getaddrinfo(host, port, family, type, proto, flags)

        resolver = ResilientDNSResolver(
            system_resolver=system_resolver,
            doh_lookup=lambda _host, _family: (("93.184.216.34",), 60.0),
        )

        resolver("first.example.net", 443, type=socket.SOCK_STREAM)
        resolver("second.example.net", 443, type=socket.SOCK_STREAM)

        self.assertIn("first.example.net", queried_hosts)
        self.assertNotIn("second.example.net", queried_hosts)

    def test_installer_is_idempotent_for_every_entry_point(self):
        from shared.resilient_dns import install_resilient_dns

        system_resolver, _calls = self._system_resolver_that_fails_for("cdn.example.net")
        socket_module = SimpleNamespace(getaddrinfo=system_resolver)

        def doh_lookup(_host, _family):
            return ("93.184.216.34",), 60.0

        installed = install_resilient_dns(
            socket_module=socket_module,
            doh_lookup=doh_lookup,
        )
        installed_again = install_resilient_dns(
            socket_module=socket_module,
            doh_lookup=doh_lookup,
        )

        self.assertIs(installed_again, installed)
        self.assertIs(socket_module.getaddrinfo, installed)
        self.assertEqual(
            socket_module.getaddrinfo("cdn.example.net", 443, type=socket.SOCK_STREAM)[0][4][0],
            "93.184.216.34",
        )

    def test_chromium_dns_args_include_enhanced_bootstrap_endpoints(self):
        from shared.resilient_dns import chromium_resilient_dns_args

        args = chromium_resilient_dns_args()

        self.assertEqual(args[0], "--dns-over-https-mode=automatic")
        self.assertTrue(args[1].startswith("--dns-over-https-templates="))
        self.assertIn("dns.alidns.com", args[1])
        self.assertIn("223.5.5.5", args[1])
        self.assertIn("cloudflare-dns.com", args[1])
        self.assertIn("1.1.1.1", args[1])


if __name__ == "__main__":
    unittest.main()
