"""Real Chromium regression cases for the shared public-network guard."""

from __future__ import annotations

import socket

from shared.playwright_network_guard import install_public_network_guard
from shared.runtime_options import DomainPolicyEngine


class NetworkGuardCases:
    def test_public_network_guard_blocks_popup_first_private_request(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(1.0)
        port = listener.getsockname()[1]
        context = self._browser.new_context(service_workers="block")
        install_public_network_guard(context, DomainPolicyEngine())
        page = context.new_page()
        accepted = False
        connection = None
        try:
            page.goto("data:text/html,<title>network-guard</title>")
            page.evaluate(
                "(url) => { window.open(url, '_blank'); }",
                f"http://127.0.0.1:{port}/private-popup",
            )
            page.wait_for_timeout(250)
            try:
                connection, _address = listener.accept()
                accepted = True
            except socket.timeout:
                pass
            self.assertFalse(accepted, "popup first navigation reached a loopback TCP listener")
        finally:
            if connection is not None:
                connection.close()
            listener.close()
            context.close()

    def test_public_network_guard_blocks_websocket_and_worker_constructors(self):
        context = self._browser.new_context(service_workers="block")
        install_public_network_guard(context, DomainPolicyEngine())
        page = context.new_page()
        try:
            page.goto("data:text/html,<title>script-network-guard</title>")
            results = page.evaluate(
                """
                () => {
                  const names = ["WebSocket", "Worker", "SharedWorker"];
                  return Object.fromEntries(names.map((name) => {
                    try {
                      if (name === "WebSocket") new WebSocket("ws://127.0.0.1:9/socket");
                      else if (name === "Worker") new Worker("data:text/javascript,void 0");
                      else new SharedWorker("data:text/javascript,void 0");
                      return [name, "allowed"];
                    } catch (error) {
                      return [name, error.name];
                    }
                  }));
                }
                """
            )
            self.assertEqual(
                results,
                {"WebSocket": "SecurityError", "Worker": "SecurityError", "SharedWorker": "SecurityError"},
            )
        finally:
            context.close()
