"""
matching.py — alias-to-parties matching for filtering upstream fuzzy results.

The NSW Registry API does substring/fuzzy matching on nameOfParty, so
"Capitol Constructions" returns hits for "CAPITAL CONSTRUCTION AND
REFURBISHING PTY LTD".  This module provides a word-boundary check
to separate exact matches from near-misses.

Matching is restricted to the respondent side of the "v" separator
(the builder in building disputes).  Single-word search terms also
require a company indicator (Pty, Ltd, Homes, etc.) in the respondent
text to avoid matching personal surnames.
"""

import re

# Company indicators — when a single-word alias matches, the respondent
# text must also contain at least one of these (case-insensitive).
_COMPANY_INDICATORS = re.compile(
    r"\b(?:Pty|Ltd|Limited|P/L|Inc|Corp|Homes|Constructions|Construction|"
    r"Builders|Building|Group|Holdings|Properties|Development|Developments|"
    r"Services|Solutions|Projects|Industries|Enterprises|Co|Company|"
    r"Association|Trust)\b",
    re.IGNORECASE,
)


def _extract_respondent(parties: str) -> str:
    """
    Return the respondent portion of a parties string (after ' v ').
    Falls back to the full string when no ' v ' separator is found.
    """
    parts = re.split(r"\s+v\s+", parties, maxsplit=1)
    return parts[1] if len(parts) == 2 else parties


def alias_matches_parties(alias: str, parties: str | None) -> bool:
    """
    Return True if `alias` appears as contiguous whole words in the
    **respondent** side of `parties` (case-insensitive).

    For single-word aliases, the respondent must also contain a company
    indicator (Pty, Ltd, Homes, etc.) to avoid matching personal surnames.

    Returns False when parties is None or empty.
    """
    if not parties:
        return False

    respondent = _extract_respondent(parties)
    pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
    if not re.search(pattern, respondent, re.IGNORECASE):
        return False

    # Single-word aliases need a company indicator to confirm it's a business
    if len(alias.split()) == 1:
        return bool(_COMPANY_INDICATORS.search(respondent))

    return True
