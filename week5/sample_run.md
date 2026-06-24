Sample run of demo_queries.py (10 questions through the agent).

Model: gemini-2.5-flash-lite (free tier, swapped in for Gemini 2.5 Pro to
avoid cost, as allowed by the assignment note). Run from week5/ with
GOOGLE_API_KEY set:  python3 demo_queries.py

Note on query 9: the free Gemini tier caps this key at 20 requests/day per
model and each query makes about two model calls, so one query hit the daily
quota and returned its rate-limit message. The agent handled it gracefully
and the run continued. Every other query answered correctly using the
database, policy documents, and expense rules, with per-query cost tracked.

============================================================

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

============================================================
queries: 10
tokens:  12221
total cost:        $0.001035
avg cost / query:  $0.000103
