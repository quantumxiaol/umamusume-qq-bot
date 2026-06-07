from __future__ import annotations

import socket
from typing import Any

import aiohttp


_ORIGINAL_TCP_CONNECTOR = aiohttp.TCPConnector


class IPv4TCPConnector(_ORIGINAL_TCP_CONNECTOR):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["family"] = socket.AF_INET
        super().__init__(*args, **kwargs)


def install_force_ipv4() -> None:
    """Force aiohttp/botpy outbound connections to use IPv4."""
    if getattr(aiohttp.ClientSession, "_umamusume_force_ipv4_installed", False):
        return

    aiohttp.TCPConnector = IPv4TCPConnector  # type: ignore[assignment]

    for module_name in ("botpy.http", "botpy.gateway"):
        try:
            module = __import__(module_name, fromlist=["TCPConnector"])
        except Exception:
            continue
        if hasattr(module, "TCPConnector"):
            setattr(module, "TCPConnector", IPv4TCPConnector)

    original_init = aiohttp.ClientSession.__init__

    def patched_init(self: aiohttp.ClientSession, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("connector") is None:
            kwargs["connector"] = IPv4TCPConnector()
        original_init(self, *args, **kwargs)

    aiohttp.ClientSession.__init__ = patched_init  # type: ignore[method-assign]
    setattr(aiohttp.ClientSession, "_umamusume_force_ipv4_installed", True)
