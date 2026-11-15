"""One way to write an email address down.

Both suppression guards compare addresses as text. If two parts of the system
normalise differently — one keeps the capital letters, the other doesn't — then
"STOP@example.com" is suppressed and "stop@example.com" is not, and someone who
opted out gets another email.

So there is exactly one function, and everything uses it.
"""

from __future__ import annotations


def normalize_email(address: str) -> str:
    """Lowercase and strip an address, for storing and for comparing.

    Deliberately conservative: it does not strip +tags or dots. Those rules
    differ per provider, and guessing wrong would merge two real people into
    one record.
    """
    return address.strip().lower()
