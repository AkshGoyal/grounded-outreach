"""Each campaign's own files, in `campaigns/`.

- `<campaign-id>.md` — what you are offering. The only thing a draft may say
  about your own business.
- `<campaign-id>.closing.md` — optional. Your fixed ending: offer, request,
  sign-off and signature, added word for word to every email. When it exists,
  the model writes only the opening and is checked for repeating it.

Both live on your own machine and are git-ignored apart from the examples:
a real closing holds phone numbers and registration details.

`<!-- comments -->` are stripped when a file is loaded, so notes to yourself
never reach a model — or, worse, a recipient.
"""

from __future__ import annotations

import re
from pathlib import Path

CAMPAIGN_DIR = Path("campaigns")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def copy_path(campaign_id: str) -> Path:
    return CAMPAIGN_DIR / f"{campaign_id}.md"


def closing_path(campaign_id: str) -> Path:
    return CAMPAIGN_DIR / f"{campaign_id}.closing.md"


def _load(path: Path) -> str | None:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    # Fixed editor content, including HTML-like text, is literal user content.
    text = raw.strip() if "[KEEP]" in raw else _COMMENT.sub("", raw).strip()
    return text or None


def load_copy(campaign_id: str) -> str | None:
    if not is_valid_id(campaign_id):
        raise ValueError("Choose a valid campaign identifier.")
    return _load(copy_path(campaign_id))


def load_closing(campaign_id: str) -> str | None:
    if not is_valid_id(campaign_id):
        raise ValueError("Choose a valid campaign identifier.")
    return _load(closing_path(campaign_id))


# Lower-case letters, digits, dashes and underscores: safe as a file name, and
# nothing typed into a web form can point outside `campaigns/`.
_VALID_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def is_valid_id(campaign_id: str) -> bool:
    return bool(_VALID_ID.fullmatch(campaign_id or ""))


def read_raw(path: Path) -> str:
    """A campaign file exactly as written, comments included, for editing."""
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_texts(campaign_id: str, *, copy: str, closing: str) -> None:
    """Write both files from the web editor. An empty closing removes the file,
    which switches the campaign back to full-email drafting."""
    if not is_valid_id(campaign_id):
        raise ValueError(f"Not a usable campaign id: {campaign_id!r}")
    # Browsers submit textarea lines as CRLF. Normalise before Windows translates
    # newlines on write, otherwise CRLF becomes CRCRLF and creates blank lines.
    copy = copy.replace("\r\n", "\n").replace("\r", "\n")
    closing = closing.replace("\r\n", "\n").replace("\r", "\n")
    CAMPAIGN_DIR.mkdir(exist_ok=True)
    copy_path(campaign_id).write_text(copy.strip() + "\n", encoding="utf-8")
    if closing.strip():
        closing_path(campaign_id).write_text(closing.strip() + "\n", encoding="utf-8")
    elif closing_path(campaign_id).exists():
        closing_path(campaign_id).unlink()
