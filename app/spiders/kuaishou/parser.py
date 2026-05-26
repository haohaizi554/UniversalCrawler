from __future__ import annotations

import base64
import re
import urllib.parse


class KuaishouParser:
    def extract_all_possible_ids(self, url: str) -> set[str]:
        if not url:
            return set()
        ids: set[str] = set()
        try:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(urllib.parse.unquote(parsed.query))
            path = parsed.path
            filename = path.split("/")[-1]

            if "clientCacheKey" in qs:
                key = qs["clientCacheKey"][0]
                key_no_ext = key.rsplit(".", 1)[0]
                match = re.match(r"^([a-zA-Z0-9]+)", key_no_ext)
                if match:
                    ids.add(match.group(1))

            if "x-ks-ptid" in qs:
                ids.add(qs["x-ks-ptid"][0])

            b64_match = re.search(r"(BMj[a-zA-Z0-9+/]+)", path) or re.search(
                r"(BMj[a-zA-Z0-9+/]+)", urllib.parse.unquote(parsed.query)
            )
            if b64_match:
                b64_str = b64_match.group(1)
                try:
                    missing_padding = len(b64_str) % 4
                    if missing_padding:
                        b64_str += "=" * (4 - missing_padding)
                    decoded_str = base64.b64decode(b64_str).decode("utf-8", errors="ignore")
                    parts = decoded_str.split("_")
                    if len(parts) >= 3 and parts[2].isdigit() and len(parts[2]) >= 10:
                        ids.add(parts[2])
                    ids.update(re.findall(r"\d{10,}", decoded_str))
                except (ValueError, UnicodeDecodeError, base64.binascii.Error):
                    pass

            name_no_ext = filename.rsplit(".", 1)[0]
            ids.add(name_no_ext)
            if "_b_B" in name_no_ext:
                ids.add(name_no_ext.split("_b_B")[0])
        except (AttributeError, TypeError, ValueError):
            pass
        return ids
