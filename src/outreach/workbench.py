"""Start the isolated workbench; fixtures by default, live research only explicitly."""

import argparse
import os
import shutil
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn

from outreach.config import ConfigError, Settings
from outreach.wiring import build_workbench_app

LOCAL_HOSTS = "localhost,127.0.0.1,::1,testserver"


def hosted_options():
    """Read hosted-only settings from the environment, refusing anything unsafe.

    Hosted runs never read a repository .env file. They need an evaluator password, an
    HTTPS public origin (only that host is accepted), an absolute persistent data
    directory and a port. Secret values never appear in errors.
    """
    password = os.environ.get("WORKBENCH_APP_PASSWORD", "")
    # A shared demo password that reviewers type, so 8 characters is the floor; the
    # daily spending cap limits what anyone holding it can cost.
    if len(password) < 8:
        raise ConfigError("Set WORKBENCH_APP_PASSWORD to at least 8 characters for hosted use.")
    url = os.environ.get("WORKBENCH_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")
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
        raise ConfigError("Set an HTTPS origin in WORKBENCH_PUBLIC_URL or RENDER_EXTERNAL_URL.")
    root = Path(os.environ.get("WORKBENCH_DATA_DIR", "/var/data/workbench"))
    if not root.is_absolute():
        raise ConfigError("WORKBENCH_DATA_DIR must be an absolute persistent-directory path.")
    try:
        port = int(os.environ.get("PORT", "10000"))
    except ValueError:
        raise ConfigError("PORT must be a number between 1 and 65535.") from None
    if not 1 <= port <= 65535:
        raise ConfigError("PORT must be between 1 and 65535.")
    return {"password": password, "host": origin.hostname, "data_dir": root, "port": port}


SHOWCASE = Path(__file__).resolve().parent / "web" / "evaluation" / "showcase.db"


def seed_showcase(data_dir):
    """Start an empty hosted data folder from the evaluation's 15 real runs.

    The free host keeps no disk between restarts, so without this every visitor would
    meet an empty History. The copy holds only finished runs (no pending paid work),
    with contact details stripped from the saved pages. An existing database is never
    touched.
    """
    target = data_dir / "workbench.db"
    if target.exists() or not SHOWCASE.exists():
        return False
    shutil.copyfile(SHOWCASE, target)
    marker = data_dir / "workbench.db.workbench"
    if not marker.exists():
        marker.write_text("Outreach Workbench dedicated database\n")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(".local-cache/workbench-workbench"))
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--credential-file", type=Path, default=Path(".env"))
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal("0.05"))
    parser.add_argument(
        "--daily-usd",
        type=Decimal,
        default=Decimal("0.50"),
        help="Total paid spend allowed per UTC day across all runs in this data directory.",
    )
    parser.add_argument(
        "--hosted",
        action="store_true",
        help="Serve behind an HTTPS proxy with a password; settings come from the environment.",
    )
    args = parser.parse_args()
    if not args.budget_usd.is_finite() or not Decimal("0.01") <= args.budget_usd <= Decimal("0.15"):
        parser.error("Choose a live budget from 0.01 to 0.15 USD.")
    if not args.daily_usd.is_finite() or not args.budget_usd <= args.daily_usd <= Decimal("2"):
        parser.error("Choose a daily budget from the run budget up to 2.00 USD.")
    hosted = None
    if args.hosted:
        try:
            hosted = hosted_options()
        except ConfigError as exc:
            parser.error(str(exc))
        hosted["data_dir"].mkdir(parents=True, exist_ok=True, mode=0o700)
    data_dir = hosted["data_dir"] if hosted else args.data_dir
    if hosted and args.mode == "live":
        seed_showcase(data_dir)
    # Fixtures never read .env or the original application's environment namespace;
    # hosted live runs read keys from the process environment only.
    try:
        settings = Settings(
            _env_file=args.credential_file if args.mode == "live" and not hosted else None,
            _env_prefix="OUTREACH_" if args.mode == "live" else "WORKBENCH_",
            db_path=str(data_dir / "workbench.db"),
            app_password=(hosted or {}).get("password")
            or os.environ.get("WORKBENCH_APP_PASSWORD")
            or None,
            allowed_hosts=hosted["host"] if hosted else LOCAL_HOSTS,
        )
        if args.mode == "live":
            settings.require("parallel_api_key", "openrouter_api_key")
    except (ConfigError, ValueError):
        parser.error(
            "Live research needs valid OUTREACH_PARALLEL_API_KEY and "
            "OUTREACH_OPENROUTER_API_KEY settings. Secret values are hidden."
        )
    network = (
        # The hosting proxy terminates HTTPS; trust its forwarded scheme so the login
        # cookie is marked Secure. Only the configured public host is accepted.
        {
            "host": "0.0.0.0",
            "port": hosted["port"],
            "proxy_headers": True,
            "forwarded_allow_ips": "*",
        }
        if hosted
        else {"host": "127.0.0.1", "port": args.port}
    )
    uvicorn.run(
        build_workbench_app(
            settings,
            mode=args.mode,
            limits={"budget_micro": int(args.budget_usd * 1_000_000)},
            daily_budget_usd=float(args.daily_usd),
        ),
        **network,
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    main()
