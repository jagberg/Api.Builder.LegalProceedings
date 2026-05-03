"""
test_golden.py — canonical regression suite.

These tests define the core behavioural contracts that must never break
without explicit approval. All tests use real DB + mock NSW API (no live
network calls).

Requires: docker compose up -d db
"""


class TestGoldenAliasResolution:
    """Single-word alias and full legal name must resolve to the same builder and results."""

    def test_single_word_finds_builder(self, client, seed_respondent_case, mock_nsw_empty):
        r = client.get("/builders/masterton/hearings")
        assert r.json["ephemeral"] is False
        assert r.json["builderName"] == "Masterton"

    def test_full_name_lowercase_finds_same_builder(self, client, seed_respondent_case, mock_nsw_empty):
        r = client.get("/builders/masterton%20homes%20pty%20limited/hearings")
        assert r.json["ephemeral"] is False
        assert r.json["builderName"] == "Masterton"

    def test_full_name_uppercase_finds_same_builder(self, client, seed_respondent_case, mock_nsw_empty):
        r = client.get("/builders/MASTERTON%20HOMES%20PTY%20LIMITED/hearings")
        assert r.json["ephemeral"] is False
        assert r.json["builderName"] == "Masterton"

    def test_single_word_and_full_name_return_identical_hearings(
        self, client, seed_respondent_case, mock_nsw_empty
    ):
        by_short = client.get("/builders/masterton/hearings").json
        by_full  = client.get("/builders/masterton%20homes%20pty%20limited/hearings").json
        assert by_short["total"] == by_full["total"]
        short_ids = {h["externalId"] for h in by_short["hearings"]}
        full_ids  = {h["externalId"] for h in by_full["hearings"]}
        assert short_ids == full_ids


class TestGoldenRespondentCase:
    """Builder as respondent appears in hearings, not applicantCases."""

    def test_respondent_case_in_hearings(self, client, seed_respondent_case, mock_nsw_empty):
        r = client.get("/builders/masterton/hearings")
        ids = [h["externalId"] for h in r.json["hearings"]]
        assert "golden_respondent_001" in ids

    def test_respondent_case_not_in_applicant_cases(self, client, seed_respondent_case, mock_nsw_empty):
        r = client.get("/builders/masterton/hearings")
        ids = [h["externalId"] for h in r.json["applicantCases"]]
        assert "golden_respondent_001" not in ids

    def test_respondent_case_not_in_similar(self, client, seed_respondent_case, mock_nsw_empty):
        r = client.get("/builders/masterton/hearings")
        ids = [h["externalId"] for h in r.json["similarMatches"]]
        assert "golden_respondent_001" not in ids


class TestGoldenApplicantCase:
    """Builder as applicant appears in applicantCases, not hearings or similar."""

    def test_applicant_case_in_applicant_cases(self, client, seed_applicant_case, mock_nsw_empty):
        r = client.get("/builders/masterton/hearings")
        ids = [h["externalId"] for h in r.json["applicantCases"]]
        assert "golden_applicant_001" in ids

    def test_applicant_case_not_in_hearings(self, client, seed_applicant_case, mock_nsw_empty):
        r = client.get("/builders/masterton/hearings")
        ids = [h["externalId"] for h in r.json["hearings"]]
        assert "golden_applicant_001" not in ids

    def test_applicant_case_not_in_similar(self, client, seed_applicant_case, mock_nsw_empty):
        r = client.get("/builders/masterton/hearings")
        ids = [h["externalId"] for h in r.json["similarMatches"]]
        assert "golden_applicant_001" not in ids


class TestGoldenBothCasesTogether:
    """Both case types seeded — verify correct partition and counts."""

    def test_counts_partitioned_correctly(
        self, client, seed_respondent_case, seed_applicant_case, mock_nsw_empty
    ):
        r = client.get("/builders/masterton/hearings")
        assert r.status_code == 200
        assert r.json["total"] == 1                  # hearings count = respondent only
        assert len(r.json["hearings"]) == 1
        assert len(r.json["applicantCases"]) == 1

    def test_each_case_in_correct_bucket(
        self, client, seed_respondent_case, seed_applicant_case, mock_nsw_empty
    ):
        r = client.get("/builders/masterton/hearings")
        hearing_ids  = {h["externalId"] for h in r.json["hearings"]}
        applicant_ids = {h["externalId"] for h in r.json["applicantCases"]}
        assert "golden_respondent_001" in hearing_ids
        assert "golden_applicant_001" in applicant_ids
        assert hearing_ids.isdisjoint(applicant_ids)
