"""
test_matching.py — unit tests for scraper/matching.py.

No database or network required.
"""

from scraper.matching import alias_matches_parties


# ---------------------------------------------------------------------------
# Multi-word aliases — matched against respondent side
# ---------------------------------------------------------------------------

class TestMultiWordAlias:
    def test_exact_match_on_respondent(self):
        assert alias_matches_parties(
            "Capitol Constructions",
            "Oscar Downing v CAPITOL CONSTRUCTIONS PTY. LIMITED trading as VOGUE HOMES NSW",
        ) is True

    def test_alias_in_trading_as_clause(self):
        assert alias_matches_parties(
            "Vogue Homes",
            "John Smith v CAPITOL CONSTRUCTIONS PTY LTD trading as VOGUE HOMES",
        ) is True

    def test_different_spelling_rejected(self):
        assert alias_matches_parties(
            "Capitol Constructions",
            "Jane Doe v CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD",
        ) is False

    def test_words_in_different_order_rejected(self):
        assert alias_matches_parties(
            "Capitol Constructions",
            "Natalie Cue v PREMIER CONSTRUCTION CAPITAL PTY LTD",
        ) is False

    def test_alias_not_present_at_all(self):
        assert alias_matches_parties(
            "Totally Different",
            "John Smith v SOME BUILDER PTY LTD",
        ) is False

    def test_alias_with_punctuation(self):
        assert alias_matches_parties(
            "Smith & Co.",
            "Jones v SMITH & CO. PTY LTD",
        ) is True


# ---------------------------------------------------------------------------
# Respondent-only matching — alias on applicant side rejected
# ---------------------------------------------------------------------------

class TestRespondentOnlyMatching:
    def test_alias_on_applicant_side_rejected(self):
        """SUSAN DOVE is the applicant, not the respondent."""
        assert alias_matches_parties(
            "Dove",
            "SUSAN DOVE v Renovator Store Pty Ltd trading as Reno Store",
        ) is False

    def test_alias_on_respondent_side_accepted(self):
        assert alias_matches_parties(
            "Masterton",
            "Sundhir Lal v Masterton Homes Pty Limited",
        ) is True

    def test_multi_word_alias_on_applicant_side_rejected(self):
        assert alias_matches_parties(
            "Capitol Constructions",
            "CAPITOL CONSTRUCTIONS PTY LTD v John Smith",
        ) is False

    def test_no_v_separator_uses_full_string(self):
        """Fallback: if no ' v ' separator, match the full text."""
        assert alias_matches_parties(
            "Metricon Homes",
            "Directions hearing for METRICON HOMES PTY LTD",
        ) is True


# ---------------------------------------------------------------------------
# Single-word aliases — require company indicator
# ---------------------------------------------------------------------------

class TestSingleWordCompanyIndicator:
    def test_surname_without_indicator_rejected(self):
        """'Dove' in 'Lachlan Dove' — no company indicator → reject."""
        assert alias_matches_parties(
            "Dove",
            "Jessica Camille Clark v Lachlan Dove",
        ) is False

    def test_criminal_case_person_rejected(self):
        """'R v BRETT ANTHONY DOVE' — no company indicator → reject."""
        assert alias_matches_parties(
            "Dove",
            "R v BRETT ANTHONY DOVE",
        ) is False

    def test_law_firm_in_parties_rejected(self):
        """Long law firm reference with 'Dove' as a surname."""
        assert alias_matches_parties(
            "Dove",
            "McKenzie Dove Moore and the persons listed as Partners v Kerry Anne Hyland",
        ) is False

    def test_single_word_with_pty_ltd_accepted(self):
        assert alias_matches_parties(
            "Dove",
            "Smith v Dove Homes Pty Ltd",
        ) is True

    def test_single_word_metricon_with_homes_accepted(self):
        assert alias_matches_parties(
            "Metricon",
            "Smith v METRICON HOMES PTY LTD",
        ) is True

    def test_single_word_with_trading_as_accepted(self):
        assert alias_matches_parties(
            "Dove",
            "Smith v ABC Pty Ltd trading as Dove Building",
        ) is True

    def test_single_word_with_constructions_accepted(self):
        assert alias_matches_parties(
            "Dove",
            "Smith v Dove Constructions",
        ) is True

    def test_single_word_with_limited_accepted(self):
        assert alias_matches_parties(
            "Dove",
            "Smith v Dove Group Limited",
        ) is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_parties_is_none(self):
        assert alias_matches_parties("Capitol Constructions", None) is False

    def test_parties_is_empty(self):
        assert alias_matches_parties("Capitol Constructions", "") is False
