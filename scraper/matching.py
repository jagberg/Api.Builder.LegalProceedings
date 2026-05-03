"""
matching.py — alias-to-parties matching for filtering upstream fuzzy results.

The NSW Registry API does substring/fuzzy matching on nameOfParty, so
"Capitol Constructions" returns hits for "CAPITAL CONSTRUCTION AND
REFURBISHING PTY LTD".  This module provides a word-boundary check
to separate exact matches from near-misses.

Matching checks both sides of the "v" separator — the builder may appear
as either the respondent (being sued) or the applicant (suing another party).
Single-word search terms also require a company indicator (Pty, Ltd, Homes,
etc.) in the matched text to avoid matching personal surnames.
"""

import re

# Company indicators — when a single-word alias matches, the matched side
# must also contain at least one of these (case-insensitive).
_COMPANY_INDICATORS = re.compile(
    r"\b(?:Pty|Ltd|Limited|P/L|Inc|Corp|Homes|Constructions|Construction|"
    r"Builders|Building|Group|Holdings|Properties|Development|Developments|"
    r"Services|Solutions|Projects|Industries|Enterprises|Co|Company|"
    r"Association|Trust)\b",
    re.IGNORECASE,
)


def alias_match_side(alias: str, parties: str | None) -> str | None:
    """
    Return 'respondent', 'applicant', or None.

    Checks both sides of the ' v ' separator for a word-boundary match
    (case-insensitive). Respondent side takes priority when both sides match.
    Single-word aliases require a company indicator on the matched side
    to avoid matching personal surnames.

    Returns None when parties is None, empty, or no match found.
    """
    if not parties:
        return None

    pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
    is_multi_word = len(alias.split()) > 1
    parts = re.split(r"\s+v\s+", parties, maxsplit=1)
    respondent = parts[1] if len(parts) == 2 else parties

    if re.search(pattern, respondent, re.IGNORECASE):
        if is_multi_word or bool(_COMPANY_INDICATORS.search(respondent)):
            return "respondent"

    if len(parts) == 2:
        applicant = parts[0]
        if re.search(pattern, applicant, re.IGNORECASE):
            if is_multi_word or bool(_COMPANY_INDICATORS.search(applicant)):
                return "applicant"

    return None
