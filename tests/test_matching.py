"""
test_matching.py — unit tests for scraper/matching.py.

No database or network required.
"""

from scraper.matching import alias_match_side


# ---------------------------------------------------------------------------
# Multi-word aliases — matched against respondent side
# ---------------------------------------------------------------------------

class TestMultiWordAlias:
    def test_exact_match_on_respondent(self):
        assert alias_match_side(
            "Capitol Constructions",
            "Oscar Downing v CAPITOL CONSTRUCTIONS PTY. LIMITED trading as VOGUE HOMES NSW",
        ) == "respondent"

    def test_alias_in_trading_as_clause(self):
        assert alias_match_side(
            "Vogue Homes",
            "John Smith v CAPITOL CONSTRUCTIONS PTY LTD trading as VOGUE HOMES",
        ) == "respondent"

    def test_different_spelling_rejected(self):
        assert alias_match_side(
            "Capitol Constructions",
            "Jane Doe v CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD",
        ) is None

    def test_words_in_different_order_rejected(self):
        assert alias_match_side(
            "Capitol Constructions",
            "Natalie Cue v PREMIER CONSTRUCTION CAPITAL PTY LTD",
        ) is None

    def test_alias_not_present_at_all(self):
        assert alias_match_side(
            "Totally Different",
            "John Smith v SOME BUILDER PTY LTD",
        ) is None

    def test_alias_with_punctuation(self):
        assert alias_match_side(
            "Smith & Co.",
            "Jones v SMITH & CO. PTY LTD",
        ) == "respondent"


# ---------------------------------------------------------------------------
# Match side — respondent, applicant, and personal surname rejection
# ---------------------------------------------------------------------------

class TestMatchSide:
    def test_personal_surname_applicant_rejected(self):
        """SUSAN DOVE is the applicant but has no company indicator — reject."""
        assert alias_match_side(
            "Dove",
            "SUSAN DOVE v Renovator Store Pty Ltd trading as Reno Store",
        ) is None

    def test_alias_on_respondent_side_accepted(self):
        assert alias_match_side(
            "Masterton",
            "Sundhir Lal v Masterton Homes Pty Limited",
        ) == "respondent"

    def test_multi_word_alias_on_applicant_side_accepted(self):
        """Builder as applicant — should match as 'applicant'."""
        assert alias_match_side(
            "Capitol Constructions",
            "CAPITOL CONSTRUCTIONS PTY LTD v John Smith",
        ) == "applicant"

    def test_no_v_separator_uses_full_string(self):
        """Fallback: if no ' v ' separator, match the full text as respondent."""
        assert alias_match_side(
            "Metricon Homes",
            "Directions hearing for METRICON HOMES PTY LTD",
        ) == "respondent"

    def test_respondent_wins_when_both_sides_match(self):
        assert alias_match_side(
            "Masterton",
            "MASTERTON v MASTERTON HOMES PTY LTD",
        ) == "respondent"


# ---------------------------------------------------------------------------
# Single-word aliases — require company indicator on matched side
# ---------------------------------------------------------------------------

class TestSingleWordCompanyIndicator:
    def test_surname_without_indicator_rejected(self):
        """'Dove' in 'Lachlan Dove' — no company indicator → reject."""
        assert alias_match_side(
            "Dove",
            "Jessica Camille Clark v Lachlan Dove",
        ) is None

    def test_criminal_case_person_rejected(self):
        """'R v BRETT ANTHONY DOVE' — no company indicator → reject."""
        assert alias_match_side(
            "Dove",
            "R v BRETT ANTHONY DOVE",
        ) is None

    def test_law_firm_in_parties_rejected(self):
        """Long law firm reference with 'Dove' as a surname."""
        assert alias_match_side(
            "Dove",
            "McKenzie Dove Moore and the persons listed as Partners v Kerry Anne Hyland",
        ) is None

    def test_single_word_with_pty_ltd_accepted(self):
        assert alias_match_side(
            "Dove",
            "Smith v Dove Homes Pty Ltd",
        ) == "respondent"

    def test_single_word_metricon_with_homes_accepted(self):
        assert alias_match_side(
            "Metricon",
            "Smith v METRICON HOMES PTY LTD",
        ) == "respondent"

    def test_single_word_with_trading_as_accepted(self):
        assert alias_match_side(
            "Dove",
            "Smith v ABC Pty Ltd trading as Dove Building",
        ) == "respondent"

    def test_single_word_with_constructions_accepted(self):
        assert alias_match_side(
            "Dove",
            "Smith v Dove Constructions",
        ) == "respondent"

    def test_single_word_with_limited_accepted(self):
        assert alias_match_side(
            "Dove",
            "Smith v Dove Group Limited",
        ) == "respondent"

    def test_single_word_applicant_with_company_indicator_accepted(self):
        """Single-word alias as applicant with company indicator → 'applicant'."""
        assert alias_match_side(
            "Masterton",
            "MASTERTON HOMES PTY LIMITED v IDEALCORP PTY LIMITED",
        ) == "applicant"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_parties_is_none(self):
        assert alias_match_side("Capitol Constructions", None) is None

    def test_parties_is_empty(self):
        assert alias_match_side("Capitol Constructions", "") is None
