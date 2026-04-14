"""
test_matching.py — unit tests for scraper/matching.py.

No database or network required.
"""

from scraper.matching import alias_matches_parties


class TestAliasMatchesParties:
    def test_exact_match_case_insensitive(self):
        assert alias_matches_parties(
            "Capitol Constructions",
            "Oscar Downing v CAPITOL CONSTRUCTIONS PTY. LIMITED trading as VOGUE HOMES NSW",
        ) is True

    def test_alias_at_end_of_parties(self):
        assert alias_matches_parties(
            "Vogue Homes",
            "John Smith v CAPITOL CONSTRUCTIONS PTY LTD trading as VOGUE HOMES",
        ) is True

    def test_alias_at_start_of_parties(self):
        assert alias_matches_parties(
            "Capitol Constructions",
            "CAPITOL CONSTRUCTIONS PTY LTD v John Smith",
        ) is True

    def test_different_spelling_rejected(self):
        """'Capitol' vs 'Capital', 'Constructions' vs 'Construction'."""
        assert alias_matches_parties(
            "Capitol Constructions",
            "Jane Doe v CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD",
        ) is False

    def test_words_in_different_order_rejected(self):
        assert alias_matches_parties(
            "Capitol Constructions",
            "Natalie Cue v PREMIER CONSTRUCTION CAPITAL PTY LTD",
        ) is False

    def test_single_word_alias_matches(self):
        assert alias_matches_parties(
            "Metricon",
            "Smith v METRICON HOMES PTY LTD",
        ) is True

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

    def test_parties_is_none(self):
        assert alias_matches_parties("Capitol Constructions", None) is False

    def test_parties_is_empty(self):
        assert alias_matches_parties("Capitol Constructions", "") is False
