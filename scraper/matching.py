"""
matching.py — alias-to-parties matching for filtering upstream fuzzy results.

The NSW Registry API does substring/fuzzy matching on nameOfParty, so
"Capitol Constructions" returns hits for "CAPITAL CONSTRUCTION AND
REFURBISHING PTY LTD".  This module provides a word-boundary check
to separate exact matches from near-misses.
"""

import re


def alias_matches_parties(alias: str, parties: str | None) -> bool:
    """
    Return True if `alias` appears as contiguous whole words in `parties`
    (case-insensitive).  Returns False when parties is None or empty.

    Uses lookaround assertions instead of \\b so aliases containing
    punctuation (e.g. "Smith & Co.") are handled correctly.
    """
    if not parties:
        return False
    pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
    return bool(re.search(pattern, parties, re.IGNORECASE))
