"""Optional operator sign-in, same-origin write protection and safe browser headers."""

import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse


def install_security(app, settings, templates):
    # Derived from the password, so a sign-in survives a restart (the free host restarts
    # after every idle spell) and changing the password signs everyone out.
    secret = (
        hashlib.sha256(b"outreach-session-v1:" + settings.app_password.encode()).digest()
        if settings.app_password
        else secrets.token_bytes(32)
    )
    failures = {}

    def valid(token):
        try:
            expires, signature = token.split(".", 1)
            return int(expires) > time.time() and hmac.compare_digest(
                signature, hmac.new(secret, expires.encode(), hashlib.sha256).hexdigest()
            )
        except (ValueError, AttributeError):
            return False

    @app.middleware("http")
    async def protection(request, call_next):
        allowed = {name.strip().casefold() for name in settings.allowed_hosts.split(",")}
        if (request.url.hostname or "").casefold() not in allowed:
            return HTMLResponse("This host is not configured for the workspace.", status_code=400)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin") or request.headers.get("referer")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin and urlsplit(origin).netloc != request.headers.get("host")
            ):
                return HTMLResponse(
                    "This action must be submitted from this application.", status_code=403
                )
        if (
            settings.app_password
            and request.url.path
            not in (
                "/login",
                "/health",
                "/accounts/oauth/gmail/callback",
                "/accounts/oauth/zoho/callback",
            )
            and not request.url.path.startswith("/static/")
            and not valid(request.cookies.get("outreach_session"))
        ):
            return RedirectResponse("/login", status_code=303)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = (
            "no-referrer"
            if request.url.path
            in ("/accounts/oauth/gmail/callback", "/accounts/oauth/zoho/callback")
            else "same-origin"
        )
        response.headers["Content-Security-Policy"] = (
            "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        )
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {})

    @app.post("/login")
    def login(request: Request, password: str = Form("")):
        ip = request.client.host if request.client else "unknown"
        recent = [t for t in failures.get(ip, []) if time.time() - t < 60]
        if len(recent) >= 5:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Too many wrong tries. Wait a minute, then try again.", "locked": True},
                status_code=429,
            )
        if not settings.app_password or not secrets.compare_digest(password, settings.app_password):
            failures[ip] = [*recent, time.time()]
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": "That password was not accepted.",
                    "wrong_password": True,
                    "tries_left": max(0, 5 - len(failures[ip])),
                },
                status_code=401,
            )
        expires = str(int(time.time() + 12 * 60 * 60))
        token = expires + "." + hmac.new(secret, expires.encode(), hashlib.sha256).hexdigest()
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            "outreach_session",
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https"
            or bool(settings.oauth_public_url and settings.oauth_public_url.startswith("https://")),
            max_age=43200,
        )
        failures.pop(ip, None)
        return response

    @app.post("/logout")
    def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("outreach_session")
        return response
