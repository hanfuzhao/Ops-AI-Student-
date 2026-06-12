"""Unit tests for the tools and agent.

These don't hit the Gemini API, so they run without a key. The reasoning
loop itself needs a real key and is exercised by demo_queries.py.
"""

from pathlib import Path

import pytest

from app.agent import (
    Agent,
    EmployeeLookupTool,
    PolicySearchTool,
    ExpenseQueryTool,
)

DB = str(Path(__file__).resolve().parents[1] / "data" / "techcorp.db")


# --- tools initialise with the right name/description ------------------------

def test_tool_names():
    assert EmployeeLookupTool(DB).name == "employee_lookup"
    assert PolicySearchTool().name == "policy_search"
    assert ExpenseQueryTool().name == "expense_query"
    assert "employee" in EmployeeLookupTool(DB).description.lower()


# --- employee lookup ---------------------------------------------------------

def test_employee_lookup_finds_someone():
    # id 1 exists in the shipped database
    out = EmployeeLookupTool(DB).execute(employee_id="1")
    assert "name" in out and "Employee not found" not in out


def test_employee_lookup_missing_args():
    out = EmployeeLookupTool(DB).execute()
    assert "Provide" in out


def test_employee_lookup_unknown_name():
    out = EmployeeLookupTool(DB).execute(employee_name="Nobody McNobody 9999")
    assert out == "Employee not found"


def test_employee_lookup_redacts_for_engineer():
    out = EmployeeLookupTool(DB).execute(employee_id="1", viewer_role="engineer")
    assert "[restricted]" in out  # salary/ssn hidden from an engineer


def test_employee_lookup_shows_salary_to_finance():
    out = EmployeeLookupTool(DB).execute(employee_id="1", viewer_role="finance")
    assert '"salary"' in out and "[restricted]" not in out.split('"ssn"')[0]


# --- policy search -----------------------------------------------------------

def test_policy_search_matches_travel():
    out = PolicySearchTool().execute(query="travel")
    assert "No policy documents" not in out and len(out) > 0


def test_policy_search_empty_query():
    assert "Provide" in PolicySearchTool().execute(query="")


def test_policy_search_respects_limit():
    out = PolicySearchTool().execute(query="policy employee expense", limit=1)
    # one result means no blank-line separator between documents
    assert out.count("\n\n") == 0


# --- expense query -----------------------------------------------------------

def test_expense_approval_limit_for_role():
    out = ExpenseQueryTool().execute(query_type="approval_limit", role="manager")
    assert "manager" in out and "$" in out


def test_expense_travel_budget():
    out = ExpenseQueryTool().execute(query_type="travel_budget", category="international")
    assert "$" in out


def test_expense_unknown_type():
    assert "Unknown query_type" in ExpenseQueryTool().execute(query_type="bogus")


# --- agent -------------------------------------------------------------------

def test_agent_requires_key():
    with pytest.raises(ValueError):
        Agent(DB, api_key="")


def test_agent_loads_three_tools():
    agent = Agent(DB, api_key="dummy-key-not-used")
    assert set(agent.tools) == {"employee_lookup", "policy_search", "expense_query"}


def test_agent_metrics_start_empty():
    m = Agent(DB, api_key="dummy-key-not-used").get_metrics()
    assert m == {
        "total_queries": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
        "avg_cost_per_query": 0.0,
    }


def test_cost_calculation():
    agent = Agent(DB, api_key="dummy-key-not-used")
    # 1M input + 1M output at the README rates = 0.075 + 0.30
    assert agent._estimate_query_cost(1_000_000, 1_000_000) == pytest.approx(0.375)
    assert agent._estimate_query_cost(0, 0) == 0.0
