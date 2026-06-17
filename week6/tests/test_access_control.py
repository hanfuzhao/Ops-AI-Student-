"""Tests for the week 6 guardrails."""

from pathlib import Path

import pytest

from app.access_control import AccessController, RateLimiter, CostEnforcer

POLICY = str(Path(__file__).resolve().parents[1] / "data" / "access_control.json")


# --- AccessController ---------------------------------------------------------

def test_policy_loads():
    c = AccessController(POLICY)
    assert "engineer" in c.policy["roles"]
    assert "salary" in c.sensitive_fields


def test_field_visibility():
    c = AccessController(POLICY)
    assert c.can_view_field("hr", "salary")
    assert c.can_view_field("finance", "salary")
    assert not c.can_view_field("engineer", "salary")
    # ssn is the tightest field
    assert c.can_view_field("hr", "ssn")
    assert not c.can_view_field("manager", "ssn")


def test_non_sensitive_field_is_open():
    c = AccessController(POLICY)
    assert c.can_view_field("engineer", "name")
    assert c.can_view_field("engineer", "email")


def test_document_visibility_by_sensitivity():
    c = AccessController(POLICY)
    assert c.can_view_document("engineer", {"sensitivity": "Public"})
    assert c.can_view_document("engineer", {"sensitivity": "Internal"})
    assert not c.can_view_document("engineer", {"sensitivity": "Confidential"})
    assert c.can_view_document("manager", {"sensitivity": "Confidential"})
    # unknown / missing sensitivity is treated as restricted
    assert not c.can_view_document("engineer", {})
    assert c.can_view_document("executive", {"sensitivity": "Restricted"})


def test_filter_documents_and_audit():
    c = AccessController(POLICY)
    docs = [
        {"id": "a", "sensitivity": "Public"},
        {"id": "b", "sensitivity": "Confidential"},
        {"id": "c", "sensitivity": "Internal"},
    ]
    visible = c.filter_documents("engineer", docs)
    assert [d["id"] for d in visible] == ["a", "c"]
    # one audit entry per document checked
    assert len(c.get_audit_log()) == 3
    assert any(e["allowed"] is False for e in c.get_audit_log())


def test_redaction_blocks_only_what_role_cannot_see():
    c = AccessController(POLICY)
    text = "Salary: $467,621, SSN: 123-45-6789, Address: 12 Main St"

    eng = c.redact_response("engineer", text)
    assert "467,621" not in eng
    assert "123-45-6789" not in eng
    assert eng.count("[REDACTED]") == 3

    # hr can see all three, so nothing changes
    assert c.redact_response("hr", text) == text


def test_unlabelled_ssn_is_caught():
    c = AccessController(POLICY)
    assert "123-45-6789" not in c.redact_response("engineer", "his number is 123-45-6789")


# --- RateLimiter --------------------------------------------------------------

def test_rate_limiter_blocks_after_limit():
    r = RateLimiter(max_queries_per_minute=3)
    assert [r.is_allowed("u1") for _ in range(4)] == [True, True, True, False]


def test_rate_limiter_is_per_user():
    r = RateLimiter(max_queries_per_minute=1)
    assert r.is_allowed("u1")
    assert not r.is_allowed("u1")
    assert r.is_allowed("u2")  # different user has its own budget


def test_remaining_queries():
    r = RateLimiter(max_queries_per_minute=3)
    r.is_allowed("u1")
    assert r.get_remaining_queries("u1") == 2


# --- CostEnforcer -------------------------------------------------------------

def test_new_user_can_afford():
    e = CostEnforcer()
    assert e.can_afford_query("u1", 50.0)


def test_budget_blocks_when_exceeded():
    e = CostEnforcer()
    e.add_cost("u1", "engineer", 50.0)        # engineer budget is 100
    assert e.can_afford_query("u1", 49.0)
    assert not e.can_afford_query("u1", 51.0)
    assert e.get_budget_remaining("u1") == 50.0


def test_budget_differs_by_role():
    e = CostEnforcer()
    e.add_cost("boss", "executive", 600.0)    # executive budget is 1000
    assert e.can_afford_query("boss", 300.0)
    e.add_cost("ic", "engineer", 90.0)
    assert not e.can_afford_query("ic", 20.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
