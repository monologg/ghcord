"""GitHub webhook signature verification.

GitHub sends the x-hub-signature-256 header with a "sha256=" prefix.
"""

import hashlib
import hmac


SIGNATURE_HEADER = "x-hub-signature-256"


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
