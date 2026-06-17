"""Show the week 6 guardrails without spending any API budget.

Everything here is pure policy logic (access control, rate limiting, cost
limits), so it runs offline and is the same every time. Take the screenshot
of this output for the assignment.

    python3 demo_guardrails.py
"""

from pathlib import Path

from app.access_control import AccessController, RateLimiter, CostEnforcer

POLICY = str(Path(__file__).resolve().parent / "data" / "access_control.json")


def line():
    print("-" * 60)


def access_control_demo():
    print("ACCESS CONTROL: who can see which fields")
    line()
    ac = AccessController(POLICY)
    fields = ["name", "salary", "ssn", "address"]
    roles = ["engineer", "manager", "hr", "finance"]
    header = "field".ljust(10) + "".join(r.ljust(10) for r in roles)
    print(header)
    for field in fields:
        row = field.ljust(10)
        for role in roles:
            row += ("allow" if ac.can_view_field(role, field) else "DENY").ljust(10)
        print(row)

    print("\nDOCUMENT ACCESS by sensitivity")
    line()
    docs = [
        {"id": "doc_public", "sensitivity": "Public"},
        {"id": "doc_internal", "sensitivity": "Internal"},
        {"id": "doc_confidential", "sensitivity": "Confidential"},
    ]
    for role in ["engineer", "manager"]:
        visible = [d["id"] for d in ac.filter_documents(role, docs)]
        print(f"  {role:9} can read: {visible}")


def redaction_demo():
    print("\nREDACTION: same record, different roles")
    line()
    ac = AccessController(POLICY)
    record = ("Employee: Brian Yang, Salary: $467,621, "
              "SSN: 123-45-6789, Address: 12 Main St")
    print(f"  raw       : {record}")
    for role in ["engineer", "finance", "hr"]:
        print(f"  {role:9} : {ac.redact_response(role, record)}")


def rate_limit_demo():
    print("\nRATE LIMIT: 3 queries/minute per user")
    line()
    rl = RateLimiter(max_queries_per_minute=3)
    for i in range(1, 6):
        ok = rl.is_allowed("alice")
        print(f"  alice query {i}: {'allowed' if ok else 'BLOCKED'} "
              f"(remaining {rl.get_remaining_queries('alice')})")
    print(f"  bob query 1: {'allowed' if rl.is_allowed('bob') else 'BLOCKED'} "
          f"(separate budget from alice)")


def cost_demo():
    print("\nCOST ENFORCEMENT: per-role monthly budget")
    line()
    ce = CostEnforcer()
    print(f"  engineer budget: ${ce.role_budgets['engineer']:.0f}")
    ce.add_cost("dev", "engineer", 95.0)
    print(f"  after spending $95, remaining: ${ce.get_budget_remaining('dev', 'engineer'):.0f}")
    print(f"  can afford a $4 query?  {ce.can_afford_query('dev', 4.0, 'engineer')}")
    print(f"  can afford a $10 query? {ce.can_afford_query('dev', 10.0, 'engineer')}")


def main():
    access_control_demo()
    redaction_demo()
    rate_limit_demo()
    cost_demo()
    print("\nAll guardrails enforced before any LLM call.")


if __name__ == "__main__":
    main()
