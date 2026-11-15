"""Bind launch consent to the exact emails, sender and pace shown on screen."""

import hashlib
import hmac
import json
import secrets
import time


class LaunchReview:
    def __init__(self):
        self.secret = secrets.token_bytes(32)

    def _signature(self, expires, snapshot):
        payload = json.dumps([expires, snapshot], sort_keys=True, separators=(",", ":"))
        return hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()

    def issue(self, snapshot):
        expires = str(int(time.time()) + 900)
        return expires + "." + self._signature(expires, snapshot)

    def matches(self, token, snapshot):
        try:
            expires, signature = token.split(".", 1)
            return int(expires) > time.time() and hmac.compare_digest(
                signature, self._signature(expires, snapshot)
            )
        except (ValueError, AttributeError):
            return False
