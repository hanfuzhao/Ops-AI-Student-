"""Run ten sample questions through the agent and print a cost summary.

Set your key first, then run from the week5 folder:
    export GOOGLE_API_KEY="AIza..."
    python3 demo_queries.py

Take the screenshot of this output for the assignment.
"""

from pathlib import Path
from app.agent import Agent

DB = str(Path(__file__).resolve().parent / "data" / "techcorp.db")

QUERIES = [
    ("What is the expense approval limit for a manager?", "engineer"),
    ("What's the travel budget for an international flight?", "engineer"),
    ("Look up the employee with id 1.", "engineer"),
    ("What is the travel policy at TechCorp?", "engineer"),
    ("How many PTO days does a regular employee get?", "engineer"),
    ("Can an engineer see another employee's salary?", "engineer"),
    ("What is the hotel budget for a tier 1 city?", "manager"),
    ("Find an employee named Brian.", "manager"),
    ("What's the approval limit for a director?", "finance"),
    ("Summarize the expense reimbursement policy.", "engineer"),
]


def main():
    agent = Agent(DB)
    for i, (question, role) in enumerate(QUERIES, 1):
        result = agent.query(question, role)
        print(f"\n[{i}] ({role}) {question}")
        print(f"    {result['answer']}")
        print(f"    tokens={result['tokens_used']}  cost=${result['cost']:.6f}")

    m = agent.get_metrics()
    print("\n" + "=" * 60)
    print(f"queries: {m['total_queries']}")
    print(f"tokens:  {m['total_tokens']}")
    print(f"total cost:        ${m['total_cost']:.6f}")
    print(f"avg cost / query:  ${m['avg_cost_per_query']:.6f}")


if __name__ == "__main__":
    main()
