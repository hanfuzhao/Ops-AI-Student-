"""
Week 7: Cost Optimization & Feedback Loop
"""

import json
import logging
import math
from typing import Dict, List, Any
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CostAnalyzer:
    """Track and analyze query costs."""

    def __init__(self):
        self.query_history = []

    def record_query(self, query: Dict[str, Any]):
        rec = {
            "query_text": query.get("query_text", ""),
            "retrieval_cost": query.get("retrieval_cost", 0.0),
            "llm_cost": query.get("llm_cost", 0.0),
            "tool_cost": query.get("tool_cost", 0.0),
            "error_cost": query.get("error_cost", 0.0),
            "total_cost": query.get("total_cost", 0.0),
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.query_history.append(rec)

    def get_cost_breakdown(self) -> Dict[str, Any]:
        if not self.query_history:
            return {
                "retrieval_total": 0.0,
                "llm_total": 0.0,
                "tool_total": 0.0,
                "error_total": 0.0,
                "total_daily": 0.0,
                "query_count": 0,
            }

        retrieval = sum(q["retrieval_cost"] for q in self.query_history)
        llm = sum(q["llm_cost"] for q in self.query_history)
        tool = sum(q["tool_cost"] for q in self.query_history)
        error = sum(q["error_cost"] for q in self.query_history)
        total = sum(q["total_cost"] for q in self.query_history)

        return {
            "retrieval_total": round(retrieval, 6),
            "llm_total": round(llm, 6),
            "tool_total": round(tool, 6),
            "error_total": round(error, 6),
            "total_daily": round(total, 6),
            "query_count": len(self.query_history),
        }

    def identify_cost_spikes(self) -> List[Dict]:
        """Flag queries that cost more than mean + 2*stdev."""
        if len(self.query_history) < 2:
            return []

        costs = [q["total_cost"] for q in self.query_history]
        n = len(costs)
        mean = sum(costs) / n
        variance = sum((c - mean) ** 2 for c in costs) / n
        std = math.sqrt(variance)

        if std == 0:
            return []

        threshold = mean + 2 * std
        spikes = []
        for i, q in enumerate(self.query_history):
            if q["total_cost"] > threshold:
                spikes.append({
                    "index": i,
                    "query_text": q.get("query_text", ""),
                    "total_cost": q["total_cost"],
                    "threshold": round(threshold, 6),
                    "excess": round(q["total_cost"] - threshold, 6),
                    "breakdown": {
                        "retrieval_cost": q["retrieval_cost"],
                        "llm_cost": q["llm_cost"],
                        "tool_cost": q["tool_cost"],
                        "error_cost": q["error_cost"],
                    },
                })
        return spikes


class OptimizationStrategy:
    """Cost reduction via caching, model routing, and response compression."""

    COMPLEXITY_KEYWORDS = [
        "analyze", "compare", "design", "evaluate", "explain",
        "synthesize", "recommend", "investigate", "assess", "optimize",
    ]

    def __init__(self):
        self.cache = {}
        self.strategies_applied = []
        self._cache_hits = 0
        self._cache_misses = 0
        self._docs_saved = 0
        self._model_downgrades = 0
        self._chars_saved = 0

    def apply_caching(self, query: str, response: str) -> tuple:
        """Return (hit, response). Stores on miss."""
        if query in self.cache:
            self._cache_hits += 1
            self.strategies_applied.append("caching")
            return (True, self.cache[query])

        self.cache[query] = response
        self._cache_misses += 1
        return (False, response)

    def optimize_retrieval_count(self, num_docs: int) -> int:
        """Cut retrieval to top-k (divide by 5, min 1)."""
        optimized = max(1, num_docs // 5)
        saved = num_docs - optimized
        if saved > 0:
            self._docs_saved += saved
            self.strategies_applied.append("retrieval_optimization")
        return optimized

    def select_model_by_complexity(self, query: str) -> str:
        """Route simple queries to flash, complex ones to pro."""
        q_lower = query.lower()
        words = len(query.split())

        needs_pro = any(kw in q_lower for kw in self.COMPLEXITY_KEYWORDS) or words > 15

        if needs_pro:
            return "gemini-2.5-pro"

        self._model_downgrades += 1
        self.strategies_applied.append("model_selection")
        return "gemini-1.5-flash"

    def enable_response_compression(self, response: str) -> str:
        """Keep first 5 sentences, drop the rest."""
        sentences = []
        cur = ""
        for ch in response:
            cur += ch
            if ch in ".!?":
                s = cur.strip()
                if s:
                    sentences.append(s)
                cur = ""
        if cur.strip():
            sentences.append(cur.strip())

        if len(sentences) <= 5:
            return response

        compressed = " ".join(sentences[:5])
        saved = len(response) - len(compressed)
        if saved > 0:
            self._chars_saved += saved
            self.strategies_applied.append("response_compression")
        return compressed

    def get_optimization_impact(self) -> Dict[str, Any]:
        counts = {}
        for s in self.strategies_applied:
            counts[s] = counts.get(s, 0) + 1

        breakdown = {
            "caching": counts.get("caching", 0) * 5.0,
            "retrieval_optimization": min(counts.get("retrieval_optimization", 0) * 3.0, 30.0),
            "model_selection": min(counts.get("model_selection", 0) * 4.0, 20.0),
            "response_compression": min(counts.get("response_compression", 0) * 2.0, 15.0),
        }
        total = min(sum(breakdown.values()), 80.0)

        return {
            "total_savings_pct": round(total, 1),
            "strategies_applied": list(set(self.strategies_applied)),
            "breakdown": {k: round(v, 1) for k, v in breakdown.items()},
            "details": {
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "docs_saved": self._docs_saved,
                "model_downgrades": self._model_downgrades,
                "chars_saved": self._chars_saved,
            },
        }


class FeedbackLoop:
    """Collect corrections with role-based authority checks."""

    def __init__(self):
        self.corrections = []
        self.authority = {
            "intern": 0,
            "engineer": 1,
            "manager": 2,
            "director": 3,
            "executive": 4,
        }

    def submit_correction(self, original_query: str, original_answer: str,
                          corrected_answer: str, user_role: str) -> Dict[str, Any]:
        """Store a correction if the submitter has authority and the fix adds detail."""
        if user_role not in self.authority:
            return {"accepted": False, "reason": f"Unknown role: {user_role}"}

        if self.authority[user_role] < 2:
            return {
                "accepted": False,
                "reason": f"Role '{user_role}' needs manager-level or above.",
            }

        if len(corrected_answer.strip()) <= len(original_answer.strip()):
            return {
                "accepted": False,
                "reason": "Corrected answer must be longer than the original.",
            }

        entry = {
            "original_query": original_query,
            "original_answer": original_answer,
            "corrected_answer": corrected_answer,
            "user_role": user_role,
            "timestamp": datetime.utcnow().isoformat(),
            "validated": False,
        }
        self.corrections.append(entry)
        logger.info(f"Correction from {user_role}: {original_query[:60]}...")
        return {"accepted": True, "reason": "Stored."}

    def validate_correction(self, index: int) -> bool:
        """Re-check authority + detail, then mark validated."""
        if index < 0 or index >= len(self.corrections):
            return False

        c = self.corrections[index]
        if self.authority.get(c["user_role"], -1) < 2:
            return False
        if len(c["corrected_answer"].strip()) <= len(c["original_answer"].strip()):
            return False

        c["validated"] = True
        return True

    def get_feedback_metrics(self) -> Dict[str, Any]:
        total = len(self.corrections)
        if total == 0:
            return {
                "total_corrections": 0,
                "validation_rate": 0.0,
                "avg_correction_length": 0.0,
                "top_error_patterns": [],
            }

        validated = sum(1 for c in self.corrections if c.get("validated", False))
        avg_len = sum(len(c["corrected_answer"]) for c in self.corrections) / total

        # pull keywords from original queries to spot recurring topics
        stop = {"what", "is", "the", "how", "who", "can", "for", "and", "are", "does", "do", "to", "of", "in", "a"}
        counts: Dict[str, int] = {}
        for c in self.corrections:
            for w in c["original_query"].lower().split():
                w = w.strip("?,.!")
                if len(w) > 3 and w not in stop:
                    counts[w] = counts.get(w, 0) + 1
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "total_corrections": total,
            "validation_rate": round(validated / total, 2),
            "avg_correction_length": round(avg_len, 1),
            "top_error_patterns": [{"pattern": p, "count": n} for p, n in top],
        }


if __name__ == "__main__":
    passed = 0
    failed = 0

    def check(name, cond):
        global passed, failed
        if cond:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}")

    # -- CostAnalyzer --
    print("=" * 60)
    print("CostAnalyzer Tests")
    print("=" * 60)

    analyzer = CostAnalyzer()

    bd = analyzer.get_cost_breakdown()
    check("empty breakdown count=0", bd["query_count"] == 0)
    check("empty breakdown total=0", bd["total_daily"] == 0.0)
    check("empty spikes", analyzer.identify_cost_spikes() == [])

    analyzer.record_query({
        "query_text": "What is the travel policy?",
        "retrieval_cost": 0.01,
        "llm_cost": 0.02,
        "tool_cost": 0.005,
        "error_cost": 0.0,
        "total_cost": 0.035,
    })
    check("1 record -> count=1", analyzer.get_cost_breakdown()["query_count"] == 1)
    check("1 record -> no spikes yet", analyzer.identify_cost_spikes() == [])

    for i in range(14):
        analyzer.record_query({
            "query_text": f"Normal query {i}",
            "retrieval_cost": 0.01,
            "llm_cost": 0.02,
            "tool_cost": 0.005,
            "error_cost": 0.0,
            "total_cost": 0.035,
        })

    bd = analyzer.get_cost_breakdown()
    check("15 queries recorded", bd["query_count"] == 15)
    check("retrieval total ok", abs(bd["retrieval_total"] - 0.15) < 1e-4)
    check("llm total ok", abs(bd["llm_total"] - 0.30) < 1e-4)
    check("tool total ok", abs(bd["tool_total"] - 0.075) < 1e-4)
    check("total ok", abs(bd["total_daily"] - 0.525) < 1e-4)

    # spike
    analyzer.record_query({
        "query_text": "Complex analysis with many tools",
        "retrieval_cost": 0.50,
        "llm_cost": 1.00,
        "tool_cost": 0.30,
        "error_cost": 0.20,
        "total_cost": 2.00,
    })

    spikes = analyzer.identify_cost_spikes()
    check("spike detected", len(spikes) >= 1)
    if spikes:
        check("spike is the expensive one",
              spikes[0]["query_text"] == "Complex analysis with many tools")
        check("spike has breakdown", "breakdown" in spikes[0])
        print(f"\n  spike: cost={spikes[0]['total_cost']}, "
              f"threshold={spikes[0]['threshold']}, excess={spikes[0]['excess']}")

    # identical costs -> no spikes
    a2 = CostAnalyzer()
    for _ in range(10):
        a2.record_query({"query_text": "same", "total_cost": 0.05})
    check("identical costs -> no spikes", a2.identify_cost_spikes() == [])

    print(f"\n  breakdown: {analyzer.get_cost_breakdown()}")

    # -- OptimizationStrategy --
    print("\n" + "=" * 60)
    print("OptimizationStrategy Tests")
    print("=" * 60)

    strat = OptimizationStrategy()

    hit, resp = strat.apply_caching("What is the travel policy?", "Travel policy says...")
    check("first call miss", hit is False)
    check("returns provided response", resp == "Travel policy says...")

    hit, resp = strat.apply_caching("What is the travel policy?", "Different answer")
    check("second call hit", hit is True)
    check("returns cached", resp == "Travel policy says...")

    hit, _ = strat.apply_caching("What is the PTO policy?", "PTO policy says...")
    check("different query miss", hit is False)

    check("15->3", strat.optimize_retrieval_count(15) == 3)
    check("10->2", strat.optimize_retrieval_count(10) == 2)
    check("1->1", strat.optimize_retrieval_count(1) == 1)
    check("0->1", strat.optimize_retrieval_count(0) == 1)

    check("simple -> flash", strat.select_model_by_complexity("What is the travel policy?") == "gemini-1.5-flash")
    check("short -> flash", strat.select_model_by_complexity("Who is the CEO?") == "gemini-1.5-flash")
    check("analyze -> pro", strat.select_model_by_complexity("Analyze the travel policy and compare it with last year") == "gemini-2.5-pro")
    check("compare -> pro", strat.select_model_by_complexity("Compare the compensation packages across departments") == "gemini-2.5-pro")
    check("long -> pro", strat.select_model_by_complexity("Design a new onboarding process for remote employees with detailed steps") == "gemini-2.5-pro")

    short = "This is short."
    check("short unchanged", strat.enable_response_compression(short) == short)

    long_resp = (
        "First sentence about the policy. "
        "Second sentence with details. "
        "Third sentence more info. "
        "Fourth sentence even more. "
        "Fifth sentence still going. "
        "Sixth sentence extra. "
        "Seventh sentence way too much. "
        "Eighth sentence unnecessary."
    )
    comp = strat.enable_response_compression(long_resp)
    check("long compressed", len(comp) < len(long_resp))
    check("keeps first 5", "First sentence" in comp and "Fifth sentence" in comp)
    check("drops later", "Eighth sentence" not in comp)

    impact = strat.get_optimization_impact()
    check("savings > 0", impact["total_savings_pct"] > 0)
    check("strategies listed", len(impact["strategies_applied"]) > 0)
    check("breakdown dict", isinstance(impact["breakdown"], dict))
    check("details dict", isinstance(impact["details"], dict))
    print(f"\n  impact: {impact['total_savings_pct']}% savings")
    print(f"  strategies: {impact['strategies_applied']}")
    print(f"  details: {impact['details']}")

    # -- FeedbackLoop --
    print("\n" + "=" * 60)
    print("FeedbackLoop Tests")
    print("=" * 60)

    loop = FeedbackLoop()
    m = loop.get_feedback_metrics()
    check("empty total=0", m["total_corrections"] == 0)
    check("empty rate=0", m["validation_rate"] == 0.0)

    r = loop.submit_correction(
        "What is the travel policy for flights over 8 hours?",
        "There is no specific policy for 8+ hour flights.",
        "Employees can book business class for flights over 8 hours with manager approval. "
        "This requires VP sign-off and must be booked through the company travel portal.",
        "manager",
    )
    check("manager accepted", r["accepted"] is True)
    check("1 stored", len(loop.corrections) == 1)

    r = loop.submit_correction("What is X?", "Short.", "A longer answer about X.", "intern")
    check("intern rejected", r["accepted"] is False)
    check("still 1", len(loop.corrections) == 1)

    r = loop.submit_correction("What is Y?", "Short.", "A longer answer about Y.", "engineer")
    check("engineer rejected", r["accepted"] is False)

    r = loop.submit_correction("What is Z?", "This is a fairly long original answer.", "Short.", "director")
    check("shorter rejected", r["accepted"] is False)

    r = loop.submit_correction("What is Z?", "Short.", "A longer corrected answer.", "unknown_role")
    check("unknown role rejected", r["accepted"] is False)

    loop.submit_correction(
        "What is the NYC per diem rate?",
        "The per diem rate is not specified.",
        "The NYC per diem rate is $250/day for hotel and $50/day for meals. "
        "Receipts are required for all expenses over $25.",
        "director",
    )
    check("director accepted", len(loop.corrections) == 2)

    loop.submit_correction(
        "Who can approve expenses over $5000?",
        "Anyone can approve.",
        "Only managers and above can approve expenses over $5000. "
        "Directors have a $25,000 limit. VP has $100,000 limit.",
        "executive",
    )
    check("executive accepted", len(loop.corrections) == 3)

    check("validate idx 0", loop.validate_correction(0) is True)
    check("validate idx 1", loop.validate_correction(1) is True)
    check("validate -1", loop.validate_correction(-1) is False)
    check("validate 99", loop.validate_correction(99) is False)
    check("correction 0 validated", loop.corrections[0]["validated"] is True)
    check("correction 1 validated", loop.corrections[1]["validated"] is True)

    m = loop.get_feedback_metrics()
    check("total=3", m["total_corrections"] == 3)
    check("rate > 0", m["validation_rate"] > 0)
    check("avg len > 0", m["avg_correction_length"] > 0)
    check("patterns list", isinstance(m["top_error_patterns"], list))
    print(f"\n  metrics: {m}")

    # -- Integration --
    print("\n" + "=" * 60)
    print("Integration Test")
    print("=" * 60)

    ai = CostAnalyzer()
    si = OptimizationStrategy()
    li = FeedbackLoop()

    queries = [
        ("What is the travel policy?", "engineer"),
        ("What is the travel policy?", "manager"),  # dup -> cache
        ("Analyze and compare all department budgets in detail", "finance"),
        ("Who is the CEO?", "engineer"),
        ("What is the NYC per diem rate?", "hr"),
    ]

    for text, role in queries:
        hit, _ = si.apply_caching(text, f"Answer for: {text}")
        model = si.select_model_by_complexity(text)
        docs = si.optimize_retrieval_count(15)

        if hit:
            cost = 0.0
        elif model == "gemini-1.5-flash":
            cost = 0.01
        else:
            cost = 0.05

        ai.record_query({
            "query_text": text,
            "retrieval_cost": 0.005 * docs,
            "llm_cost": cost,
            "tool_cost": 0.002,
            "error_cost": 0.0,
            "total_cost": 0.005 * docs + cost + 0.002,
        })

    check("5 queries in integration", ai.get_cost_breakdown()["query_count"] == 5)

    r = li.submit_correction(
        "What is the NYC per diem rate?",
        "Answer for: What is the NYC per diem rate?",
        "The NYC per diem rate is $250/day for hotel. "
        "Meal allowance is $50/day. Receipts required over $25.",
        "manager",
    )
    check("integration correction accepted", r["accepted"] is True)

    ib = ai.get_cost_breakdown()
    ii = si.get_optimization_impact()
    im = li.get_feedback_metrics()
    print(f"\n  queries: {ib['query_count']}, cost: ${ib['total_daily']:.4f}")
    print(f"  cache hits: {si._cache_hits}, savings: {ii['total_savings_pct']}%")
    print(f"  corrections: {im['total_corrections']}")

    # -- Summary --
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("All tests passed!")
    else:
        print(f"{failed} test(s) failed!")
    print("=" * 60)
