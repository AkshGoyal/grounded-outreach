"""Single-process hosted startup with all private state on one persistent volume."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from outreach.config import ConfigError, Settings


def prepare_hosted():
    # Do not load a repository .env or include submitted secret values in errors.
    try:
        settings = Settings(_env_file=None)
    except ValueError:
        raise ConfigError(
            "Hosted settings are invalid. Check environment variable names/types."
        ) from None
    settings.require("app_password")
    if len(settings.app_password) < 16:
        raise ConfigError("Use a workspace password of at least 16 characters.")
    root = Path(os.environ.get("OUTREACH_HOSTED_DATA_DIR", "/var/data/outreach"))
    if not root.is_absolute():
        raise ConfigError("OUTREACH_HOSTED_DATA_DIR must be an absolute persistent-directory path.")
    root = root.resolve()
    db = Path(os.environ.get("OUTREACH_DB_PATH", str(root / "outreach.db")))
    if not db.is_absolute() or not db.resolve().is_relative_to(root):
        raise ConfigError("The hosted database must be inside OUTREACH_HOSTED_DATA_DIR.")
    url = settings.oauth_public_url or os.environ.get("RENDER_EXTERNAL_URL", "")
    origin = urlsplit(url)
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        raise ConfigError(
            "Set an HTTPS origin in OUTREACH_OAUTH_PUBLIC_URL or RENDER_EXTERNAL_URL."
        )
    allowed = list(
        dict.fromkeys(
            [
                *[h.strip() for h in settings.allowed_hosts.split(",") if h.strip()],
                origin.hostname,
            ]
        )
    )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    # Campaign paths are relative in the existing application; the source/prompts stay in repo.
    os.chdir(root)
    return settings.model_copy(
        update={
            "db_path": str(db.resolve()),
            "oauth_public_url": url.rstrip("/"),
            "allowed_hosts": ",".join(allowed),
        }
    )


def main():
    import uvicorn

    from outreach.web.app import create_app

    try:
        settings = prepare_hosted()
        try:
            port = int(os.environ.get("PORT", "8000"))
        except ValueError:
            raise ConfigError("PORT must be a number between 1 and 65535.") from None
        if not 1 <= port <= 65535:
            raise ConfigError("PORT must be between 1 and 65535.")
    except (ConfigError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    uvicorn.run(
        create_app(settings, poll_minutes=None),
        host="0.0.0.0",
        port=port,
        workers=1,
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
