"""Identity resolution is asymmetric on purpose: duplicates are cheap, wrong
merges are not. These tests exist to keep it that way."""
from __future__ import annotations

from app.connectors.base import Author
from app.services.identity import MERGE_THRESHOLD, _score


class FakeContact:
    def __init__(self, name, email=None):
        self.display_name = name
        self.primary_email = email


def test_identical_name_alone_is_not_enough_to_merge():
    score, _ = _score(FakeContact("Priya Sharma"), Author(name="Priya Sharma"))
    assert score < MERGE_THRESHOLD


def test_identical_name_plus_shared_domain_merges():
    score, basis = _score(
        FakeContact("Priya Sharma", "priya@vertex.io"),
        Author(name="Priya Sharma", email="priya.s@vertex.io"),
    )
    assert score >= MERGE_THRESHOLD
    assert "domain" in basis


def test_different_people_at_different_companies_never_merge():
    score, _ = _score(
        FakeContact("Priya Sharma", "priya@vertex.io"),
        Author(name="Priya Sharma", email="priya@othercorp.com"),
    )
    assert score < MERGE_THRESHOLD


def test_unknown_names_score_zero_rather_than_guessing():
    assert _score(FakeContact(""), Author(name="Someone"))[0] == 0.0
