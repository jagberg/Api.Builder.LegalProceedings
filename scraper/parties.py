"""
parties.py — helpers for parsing the `parties` / `case_title` field.
"""

import re

# Match "trading as <name>" — captures up to the next " v " (case titles
# often contain "v" separators) or end of string. First match wins.
_TRADING_AS_RE = re.compile(
    r"trading as\s+(.+?)(?:\s+v\s+|$)",
    re.IGNORECASE,
)


def extract_trading_name(parties: str | None) -> str | None:
    """
    Return the first 'trading as <X>' name found in parties, or None.

    Example:
      "Kin Yan Chow v Metricon Homes trading as METRICON HOMES PTY LTD"
        -> "METRICON HOMES PTY LTD"
    """
    if not parties:
        return None
    m = _TRADING_AS_RE.search(parties)
    return m.group(1).strip() if m else None


def extract_short_name_before_trading_as(parties: str | None) -> str | None:
    """
    Return the token that appears just before 'trading as'. Useful for
    adding the 'short' name as an alias alongside the trading-as name.

    Example:
      "Kin Yan Chow v Metricon Homes trading as METRICON HOMES PTY LTD"
        -> "Metricon Homes"
    """
    if not parties:
        return None
    m = re.search(r"\bv\s+(.+?)\s+trading as\b", parties, re.IGNORECASE)
    return m.group(1).strip() if m else None
