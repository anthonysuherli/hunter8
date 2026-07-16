# handlers/__init__.py
from .base import BaseHandler, FallbackHandler
from .greenhouse import GreenhouseHandler
from .ashby import AshbyHandler
from .lever import LeverHandler


def route(url: str, dry_run: bool = False) -> BaseHandler:
    u = url.lower()
    # Embedded Greenhouse boards (e.g. Optiver) use gh_jid= without greenhouse.io in the URL.
    if "greenhouse.io" in u or "gh_jid=" in u:
        return GreenhouseHandler(dry_run=dry_run)
    if "ashbyhq.com" in u:
        return AshbyHandler(dry_run=dry_run)
    if "lever.co" in u:
        return LeverHandler(dry_run=dry_run)
    return FallbackHandler(dry_run=dry_run)
