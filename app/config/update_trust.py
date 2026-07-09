"""Read-only trust anchors for the desktop auto-updater.

Production releases must replace the empty defaults with the Ed25519 public key
used to sign ``latest.json`` and the OS package signing identities.  These
values are public trust anchors; keep private signing keys outside the client.
Leaving the values empty makes the updater fail closed.
"""

UPDATE_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAP2blm/H8iLEcpLyGQeojydA5pkIBANH3nIdnPxeo6S8=
-----END PUBLIC KEY-----"""
UPDATE_TRUSTED_PUBLISHERS: tuple[str, ...] = ()
UPDATE_TRUSTED_THUMBPRINTS: tuple[str, ...] = ()
