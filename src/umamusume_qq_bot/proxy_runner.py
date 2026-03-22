from __future__ import annotations

import argparse
import os
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import BasicAuth


def _parse_proxy_auth(raw_value: str | None) -> BasicAuth | None:
    if not raw_value:
        return None
    if ":" not in raw_value:
        raise ValueError("proxy auth must be in user:password format")
    username, password = raw_value.split(":", 1)
    if not username:
        raise ValueError("proxy auth username cannot be empty")
    return BasicAuth(login=username, password=password)


def _resolve_proxy(cli_proxy: str | None) -> str | None:
    return (
        (cli_proxy or "").strip()
        or os.getenv("QQBOT_FORCE_PROXY", "").strip()
        or os.getenv("HTTPS_PROXY", "").strip()
        or os.getenv("HTTP_PROXY", "").strip()
        or os.getenv("ALL_PROXY", "").strip()
        or None
    )


def _install_aiohttp_proxy_patch(proxy_url: str | None, proxy_auth: BasicAuth | None) -> None:
    if getattr(aiohttp.ClientSession, "_qqbot_proxy_patch_installed", False):
        return

    original_init = aiohttp.ClientSession.__init__
    original_request = aiohttp.ClientSession._request
    original_ws_connect = aiohttp.ClientSession._ws_connect
    debug_enabled = os.getenv("QQBOT_PROXY_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

    def _should_force_proxy(target_url: Any) -> bool:
        try:
            host = getattr(target_url, "host", None)
            if not host:
                host = urlparse(str(target_url)).hostname
        except Exception:
            host = None
        if not host:
            return False
        return host.endswith("sgroup.qq.com")

    def patched_init(self: aiohttp.ClientSession, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("trust_env", True)
        original_init(self, *args, **kwargs)

    async def patched_request(self: aiohttp.ClientSession, method: str, str_or_url: Any, **kwargs: Any) -> Any:
        forced_proxy = False
        if proxy_url and kwargs.get("proxy") is None and _should_force_proxy(str_or_url):
            kwargs["proxy"] = proxy_url
            forced_proxy = True
        if proxy_auth and kwargs.get("proxy_auth") is None and _should_force_proxy(str_or_url):
            kwargs["proxy_auth"] = proxy_auth
            forced_proxy = True
        if debug_enabled and _should_force_proxy(str_or_url):
            print(
                f"[proxy-runner] HTTP {method} {str(str_or_url)} proxy={kwargs.get('proxy')} forced={forced_proxy}"
            )
        return await original_request(self, method, str_or_url, **kwargs)

    async def patched_ws_connect(self: aiohttp.ClientSession, url: Any, **kwargs: Any) -> Any:
        forced_proxy = False
        if proxy_url and kwargs.get("proxy") is None and _should_force_proxy(url):
            kwargs["proxy"] = proxy_url
            forced_proxy = True
        if proxy_auth and kwargs.get("proxy_auth") is None and _should_force_proxy(url):
            kwargs["proxy_auth"] = proxy_auth
            forced_proxy = True
        if debug_enabled and _should_force_proxy(url):
            print(f"[proxy-runner] WS {str(url)} proxy={kwargs.get('proxy')} forced={forced_proxy}")
        return await original_ws_connect(self, url, **kwargs)

    aiohttp.ClientSession.__init__ = patched_init  # type: ignore[method-assign]
    aiohttp.ClientSession._request = patched_request  # type: ignore[method-assign]
    aiohttp.ClientSession._ws_connect = patched_ws_connect  # type: ignore[method-assign]
    setattr(aiohttp.ClientSession, "_qqbot_proxy_patch_installed", True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run umamusume-qq-bot with forced aiohttp proxy for local testing.",
    )
    parser.add_argument(
        "--proxy",
        default="",
        help="Proxy URL, e.g. http://127.0.0.1:10808. If omitted, use env vars.",
    )
    parser.add_argument(
        "--proxy-auth",
        default="",
        help="Proxy auth in user:password format (optional).",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Print resolved proxy settings and exit without starting bot.",
    )
    args = parser.parse_args()

    proxy_url = _resolve_proxy(args.proxy)
    try:
        proxy_auth = _parse_proxy_auth(args.proxy_auth or os.getenv("QQBOT_FORCE_PROXY_AUTH", ""))
    except ValueError as exc:
        raise SystemExit(f"Invalid proxy auth: {exc}") from exc

    if not proxy_url:
        raise SystemExit(
            "No proxy configured. Pass --proxy or set one of QQBOT_FORCE_PROXY/HTTPS_PROXY/HTTP_PROXY/ALL_PROXY."
        )

    _install_aiohttp_proxy_patch(proxy_url=proxy_url, proxy_auth=proxy_auth)
    print(f"[proxy-runner] aiohttp proxy patch enabled, proxy={proxy_url}")

    if args.check_only:
        print("[proxy-runner] check-only mode, exiting.")
        return

    from .__main__ import main as bot_main

    bot_main()


if __name__ == "__main__":
    main()
