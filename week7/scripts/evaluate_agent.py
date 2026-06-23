"""
Evaluate the agent with cost optimization.

Runs the queries from test_queries.json through CostAnalyzer + OptimizationStrategy,
prints cost breakdown, spike detection, and optimization impact.
"""
import json
import sys
from pathlib import Path

# add parent dir to path so we can import the starter
sys.path.insert(0, str(Path(__file__).parent.parent))
from cost_optimization_starter import CostAnalyzer, OptimizationStrategy, FeedbackLoop


def load_queries():
    p = Path(__file__).parent / "test_queries.json"
    with open(p) as f:
        return json.load(f)["test_queries"]


def fake_answer(query):
    """Generate a plausible-looking answer for cost estimation."""
    return f"Based on company policy, {query.lower().strip('?')} is governed by the standard guidelines."


def run_evaluation():
    queries = load_queries()
    print(f"Loaded {len(queries)} test queries\n")

    analyzer = CostAnalyzer()
    strategy = OptimizationStrategy()
    feedback = FeedbackLoop()

    print("=" * 70)
    print("Running queries through optimized agent")
    print("=" * 70)

    for i, q in enumerate(queries):
        text = q["question"]
        role = q["role"]

        # optimization 1: caching
        hit, resp = strategy.apply_caching(text, fake_answer(text))

        # optimization 2: model routing
        model = strategy.select_model_by_complexity(text)

        # optimization 3: retrieval trimming
        docs = strategy.optimize_retrieval_count(15)

        # optimization 4: compress response
        resp = strategy.enable_response_compression(resp)

        # estimate cost
        if hit:
            llm_cost = 0.0
        elif model == "gemini-1.5-flash":
            llm_cost = 0.01
        else:
            llm_cost = 0.05

        retrieval_cost = 0.005 * docs
        tool_cost = 0.002
        total = retrieval_cost + llm_cost + tool_cost

        analyzer.record_query({
            "query_text": text,
            "retrieval_cost": retrieval_cost,
            "llm_cost": llm_cost,
            "tool_cost": tool_cost,
            "error_cost": 0.0,
            "total_cost": total,
        })

        cache_tag = "HIT " if hit else "MISS"
        print(f"  [{i+1:2d}] {cache_tag} {model:20s} docs={docs} cost=${total:.4f} | {text[:50]}")

    # cost breakdown
    print("\n" + "=" * 70)
    print("Cost Breakdown")
    print("=" * 70)
    bd = analyzer.get_cost_breakdown()
    for k, v in bd.items():
        print(f"  {k:20s}: {v}")

    # spikes
    print("\n" + "=" * 70)
    print("Cost Spikes")
    print("=" * 70)
    spikes = analyzer.identify_cost_spikes()
    if not spikes:
        print("  No spikes detected.")
    for s in spikes:
        print(f"  Query #{s['index']}: ${s['total_cost']:.4f} "
              f"(threshold ${s['threshold']:.4f}, excess ${s['excess']:.4f})")
        print(f"    \"{s['query_text'][:60]}...\"")
        print(f"    breakdown: {s['breakdown']}")

    # optimization impact
    print("\n" + "=" * 70)
    print("Optimization Impact")
    print("=" * 70)
    impact = strategy.get_optimization_impact()
    print(f"  Total savings: {impact['total_savings_pct']}%")
    print(f"  Strategies applied: {impact['strategies_applied']}")
    print(f"  Breakdown: {impact['breakdown']}")
    print(f"  Details: {impact['details']}")

    # feedback loop demo
    print("\n" + "=" * 70)
    print("Feedback Loop")
    print("=" * 70)
    r = feedback.submit_correction(
        "What is the travel policy for flights over 8 hours?",
        "There is no specific policy for 8+ hour flights.",
        "Employees can book business class for flights over 8 hours with manager approval. "
        "This requires VP sign-off and must be booked through the company travel portal.",
        "manager",
    )
    print(f"  Correction 1: {r}")
    r = feedback.submit_correction(
        "What is the NYC per diem rate?",
        "The per diem rate is not specified.",
        "The NYC per diem rate is $250/day for hotel and $50/day for meals. "
        "Receipts are required for all expenses over $25.",
        "director",
    )
    print(f"  Correction 2: {r}")

    feedback.validate_correction(0)
    feedback.validate_correction(1)
    m = feedback.get_feedback_metrics()
    print(f"  Metrics: {m}")

    # summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Queries processed: {bd['query_count']}")
    print(f"  Total cost: ${bd['total_daily']:.4f}")
    print(f"  Avg cost/query: ${bd['total_daily']/bd['query_count']:.4f}")
    print(f"  Spikes detected: {len(spikes)}")
    print(f"  Optimization savings: {impact['total_savings_pct']}%")
    print(f"  Corrections collected: {m['total_corrections']}")
    print(f"  Validation rate: {m['validation_rate']*100:.0f}%")


if __name__ == "__main__":
    run_evaluation()
