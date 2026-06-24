# Week 5 Report — Agent Architecture with LLM Tool Use

Hanfu Zhao · AIPI 561

## Code structure

I moved away from the single-file `app_starter.py` template and split the code into a small package so the tools, agent, and API layer are easier to test and maintain:

```
week5/
├── app/
│   ├── __init__.py
│   ├── agent.py          # Tool base class, 3 tools, Agent class
│   └── main.py           # FastAPI endpoints (/query, /metrics)
├── tests/
│   └── test_agent.py     # unit tests for tools + agent
├── demo_queries.py       # runs 10 questions, prints cost summary
├── sample_run.md         # captured output from demo_queries.py
└── data/                 # techcorp.db, documents.json, policies.json
```

The starter template assumed a few SQL tables (`expense_policies`, `per_diem`, a `documents` table) that don't exist in the shipped `techcorp.db`. So `ExpenseQueryTool` and `PolicySearchTool` read the JSON files in `data/` instead — `policies.json` for expense/travel rules and `documents.json` for policy text.

### Tools

**EmployeeLookupTool** — queries the `employees` table in SQLite by name (LIKE) or ID (exact). Returns a JSON dict per match. Sensitive fields (salary, ssn, address, stock_options, bonus_eligible) are redacted based on `viewer_role` before the result leaves the tool, mirroring the rules in `data/access_control.json`.

**PolicySearchTool** — loads `data/documents.json` once at init, then does case-insensitive substring match on the `content` field. Returns title + first 500 chars for each hit, capped at `limit`.

**ExpenseQueryTool** — loads `data/policies.json` once at init. Looks up expense approval limits, travel budgets, and per-diem rates by role or city tier.

### Agent reasoning loop

1. Build a system prompt listing the three tools and the user's role.
2. Send the user's question to Gemini with `FunctionDeclaration` schemas for each tool.
3. If Gemini returns function calls, execute them and collect results.
4. Send the tool results back to Gemini for a final natural-language answer.
5. Count input + output tokens across both calls and compute cost.

Cost uses the README rates (input $0.075/1M, output $0.30/1M). The default model is `gemini-2.5-flash` (free tier) but can be overridden with `GEMINI_MODEL` env var.

## Test queries (10 questions)

Run with `python3 demo_queries.py` from `week5/`. Model: `gemini-2.5-flash-lite`.

```
[1] (engineer) What is the expense approval limit for a manager?
    The expense approval limit for a manager is $5,000.
    tokens=973  cost=$0.000082

[2] (engineer) What's the travel budget for an international flight?
    The travel budget for an international flight is $10,000.
    tokens=1052  cost=$0.000088

[3] (engineer) Look up the employee with id 1.
    The employee with ID 1 is Brian Yang, an E1 VP Engineering (Executive)
    in the Engineering department.
    tokens=1175  cost=$0.000097

[4] (engineer) What is the travel policy at TechCorp?
    The travel policy states that all business travel must be pre-approved by
    a manager and adhere to specific budget limits, which vary based on
    employee level and whether the travel is domestic or international.
    International travel requires VP approval.
    tokens=1395  cost=$0.000118

[5] (engineer) How many PTO days does a regular employee get?
    Individual contributors get 15 days per year, managers get 20 days per
    year, and directors and executives get 25 days per year.
    tokens=1401  cost=$0.000116

[6] (engineer) Can an engineer see another employee's salary?
    Engineers can see salary ranges for the Engineering department, but not
    specific employee salaries.
    tokens=1556  cost=$0.000133

[7] (manager) What is the hotel budget for a tier 1 city?
    The hotel budget for a tier 1 city is $350.
    tokens=983  cost=$0.000083

[8] (manager) Find an employee named Brian.
    There are multiple employees named Brian: Brian Yang (VP Engineering),
    Brian Graham (Jr. Specialist), Brian Anderson (Senior Specialist),
    Brian Johnson (Sr. Manager Specialist), and Brian Hunt (Director
    Specialist).
    tokens=2058  cost=$0.000170

[9] (finance) What's the approval limit for a director?
    [free-tier daily request quota reached on this call; handled gracefully]

[10] (engineer) Summarize the expense reimbursement policy.
    The expense reimbursement policy states that all business travel must be
    pre-approved by a manager. There are different budget limits for domestic
    travel based on employee level (IC1-IC2, IC3-IC4, IC5+) and role
    (Manager, Director+). International travel requires VP approval and has
    budget limits 50% higher than domestic travel.
    tokens=1162  cost=$0.000107
```

## Cost summary

```
queries: 10
tokens:  12221
total cost:        $0.001035
avg cost / query:  $0.000103
```

Query 9 hit the free-tier daily quota (20 requests/model/day, ~2 calls per query). The agent caught the rate-limit error and continued — the other 9 queries answered correctly using the database, policy documents, and expense rules.

## How to run

```bash
cd week5
export GOOGLE_API_KEY="AIza..."
pip install -r requirements.txt

# run the 10-query demo
python3 demo_queries.py

# run unit tests
pytest tests/

# start the FastAPI server
uvicorn app.main:app --reload
```
