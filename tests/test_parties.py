"""
test_parties.py — unit tests for trading-as parsing helpers.
"""

from scraper.parties import extract_respondent_name, extract_trading_name, extract_short_name_before_trading_as


class TestExtractTradingName:
    def test_canonical_example(self):
        assert extract_trading_name(
            "Kin Yan Chow v Metricon Homes trading as METRICON HOMES PTY LTD"
        ) == "METRICON HOMES PTY LTD"

    def test_capitol_example(self):
        assert extract_trading_name(
            "Oscar Downing v CAPITOL CONSTRUCTIONS PTY. LIMITED trading as VOGUE HOMES NSW"
        ) == "VOGUE HOMES NSW"

    def test_returns_first_match(self):
        """If two 'trading as' clauses exist, use the first."""
        assert extract_trading_name(
            "Alpha v Beta trading as FIRST PTY LTD v Gamma trading as SECOND PTY LTD"
        ) == "FIRST PTY LTD"

    def test_no_trading_as_returns_none(self):
        assert extract_trading_name("John Smith v VOGUE HOMES NSW PTY LTD") is None

    def test_none_input(self):
        assert extract_trading_name(None) is None

    def test_empty_string(self):
        assert extract_trading_name("") is None

    def test_case_insensitive(self):
        assert extract_trading_name("A v B Trading As Some Pty Ltd") == "Some Pty Ltd"

    def test_trailing_whitespace_stripped(self):
        assert extract_trading_name("A v B trading as XYZ PTY LTD   ") == "XYZ PTY LTD"


class TestExtractRespondentName:
    def test_standard_case(self):
        assert extract_respondent_name(
            "Jane Doe v CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD"
        ) == "CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD"

    def test_trading_as_included(self):
        assert extract_respondent_name(
            "Oscar Downing v CAPITOL CONSTRUCTIONS PTY. LIMITED trading as VOGUE HOMES NSW"
        ) == "CAPITOL CONSTRUCTIONS PTY. LIMITED trading as VOGUE HOMES NSW"

    def test_no_v_separator_returns_none(self):
        assert extract_respondent_name("Some text without separator") is None

    def test_none_input(self):
        assert extract_respondent_name(None) is None

    def test_empty_string(self):
        assert extract_respondent_name("") is None


class TestExtractShortNameBeforeTradingAs:
    def test_canonical_example(self):
        assert extract_short_name_before_trading_as(
            "Kin Yan Chow v Metricon Homes trading as METRICON HOMES PTY LTD"
        ) == "Metricon Homes"

    def test_capitol_example(self):
        assert extract_short_name_before_trading_as(
            "Oscar Downing v CAPITOL CONSTRUCTIONS PTY. LIMITED trading as VOGUE HOMES NSW"
        ) == "CAPITOL CONSTRUCTIONS PTY. LIMITED"

    def test_no_trading_as_returns_none(self):
        assert extract_short_name_before_trading_as(
            "John Smith v VOGUE HOMES NSW PTY LTD"
        ) is None

    def test_none_input(self):
        assert extract_short_name_before_trading_as(None) is None
