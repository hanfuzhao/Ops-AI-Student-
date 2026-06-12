"""
TechCorp agent: answers business questions by letting Gemini decide which
tools to call, running those tools against the local data, and asking the
model to write the final answer from the results.

The three tools read the data that actually ships with the assignment:
  - employees live in the SQLite database (data/techcorp.db)
  - policy documents live in data/documents.json
  - expense and travel rules live in data/policies.json

The starter template assumed a few extra SQL tables (expense_policies,
per_diem, a documents table) that don't exist in the database, so the
expense and policy tools read the JSON files instead.
"""

import json
import sqlite3
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Resolve data relative to the week5 folder so the tools work no matter
# what directory the app or the tests are started from.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

DEFAULT_MODEL = "gemini-2.5-flash"

# Pricing from the README (Gemini 2.5 Pro, per 1M tokens). The flash model
# used by default is cheaper and has a free tier, but we keep these rates so
# the cost numbers stay comparable to the assignment's figures. Override with
# input_rate / output_rate if you switch models.
INPUT_RATE_PER_1M = 0.075
OUTPUT_RATE_PER_1M = 0.30


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class Tool:
    """A thing the agent can call. Subclasses fill in execute()."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def execute(self, **kwargs) -> str:
        raise NotImplementedError

    def declaration(self) -> types.FunctionDeclaration:
        """The schema Gemini sees. Subclasses describe their parameters."""
        raise NotImplementedError


class EmployeeLookupTool(Tool):
    """Find a person in the employees table by name or id."""

    # Columns that not everyone is allowed to see, and which roles can.
    # Mirrors data/access_control.json so the agent doesn't hand back salary
    # or SSN to a role that shouldn't have it.
    SENSITIVE = {
        "salary": {"executive", "hr", "finance"},
        "ssn": {"hr", "finance"},
        "address": {"executive", "hr"},
        "stock_options": {"executive", "finance"},
        "bonus_eligible": {"executive", "finance"},
    }

    def __init__(self, db_path: str):
        super().__init__("employee_lookup", "Find employee information by name or ID")
        self.db_path = db_path

    def execute(self, employee_name: str = None, employee_id: str = None,
                viewer_role: str = "engineer", **_) -> str:
        if not employee_name and not employee_id:
            return "Provide either employee_name or employee_id."
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if employee_id:
                cur.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
            else:
                cur.execute("SELECT * FROM employees WHERE name LIKE ? LIMIT 5",
                            (f"%{employee_name}%",))
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
        except Exception as e:
            logger.error("employee lookup failed: %s", e)
            return f"Error looking up employee: {e}"

        if not rows:
            return "Employee not found"

        for row in rows:
            self._redact(row, viewer_role)
        return json.dumps(rows, indent=2)

    def _redact(self, row: Dict[str, Any], role: str) -> None:
        for field, allowed in self.SENSITIVE.items():
            if field in row and role not in allowed:
                row[field] = "[restricted]"

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description="Look up an employee's record (department, title, manager, "
                        "and so on) by their name or numeric id.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "employee_name": types.Schema(
                        type=types.Type.STRING,
                        description="Full or partial name to search for."),
                    "employee_id": types.Schema(
                        type=types.Type.STRING,
                        description="Exact employee id."),
                },
            ),
        )


class PolicySearchTool(Tool):
    """Keyword search over the policy document corpus."""

    def __init__(self, documents_path: Optional[str] = None):
        super().__init__("policy_search", "Search policy documents by keyword or topic")
        path = Path(documents_path) if documents_path else DATA_DIR / "documents.json"
        try:
            self.documents: List[Dict[str, Any]] = json.loads(Path(path).read_text())
        except Exception as e:
            logger.error("could not load documents: %s", e)
            self.documents = []

    def execute(self, query: str = "", limit: int = 3, **_) -> str:
        if not query:
            return "Provide a search query."
        terms = [t for t in query.lower().split() if t]
        scored = []
        for doc in self.documents:
            haystack = (doc.get("title", "") + " " + doc.get("content", "")).lower()
            score = sum(haystack.count(t) for t in terms)
            if score:
                scored.append((score, doc))
        if not scored:
            return f"No policy documents matched '{query}'."

        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for _, doc in scored[:limit]:
            snippet = " ".join(doc.get("content", "").split())[:500]
            out.append(f"{doc.get('title', 'Untitled')} ({doc.get('category', 'n/a')}):\n{snippet}")
        return "\n\n".join(out)

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description="Search TechCorp's policy documents (HR handbook, travel, "
                        "security, etc.) and return the most relevant passages.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="Keywords or topic to search for."),
                    "limit": types.Schema(
                        type=types.Type.INTEGER,
                        description="How many documents to return (default 3)."),
                },
                required=["query"],
            ),
        )


class ExpenseQueryTool(Tool):
    """Answer questions about expense limits and travel budgets."""

    def __init__(self, policies_path: Optional[str] = None):
        super().__init__("expense_query",
                         "Look up expense approval limits and travel budgets")
        path = Path(policies_path) if policies_path else DATA_DIR / "policies.json"
        try:
            self.policies = json.loads(Path(path).read_text())
        except Exception as e:
            logger.error("could not load policies: %s", e)
            self.policies = {}

    def execute(self, query_type: str = "", role: str = None,
                category: str = None, **_) -> str:
        if query_type == "approval_limit":
            limits = self.policies.get("expense", {}).get("approval_limits", {})
            if role and role in limits:
                return f"Expense approval limit for {role}: ${limits[role]:,}"
            return ("Expense approval limits by role: " +
                    ", ".join(f"{r} ${v:,}" for r, v in limits.items()))

        if query_type == "travel_budget":
            budgets = self.policies.get("travel", {}).get("budget_limits", {})
            if category and category in budgets:
                return f"Travel budget for {category}: ${budgets[category]:,}"
            return ("Travel budget limits: " +
                    ", ".join(f"{k} ${v:,}" for k, v in budgets.items()))

        return ("Unknown query_type. Use 'approval_limit' (with a role) or "
                "'travel_budget' (with a category).")

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description="Look up expense approval limits by role, or travel budget "
                        "limits by category (flights, hotels, meals).",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query_type": types.Schema(
                        type=types.Type.STRING,
                        description="Either 'approval_limit' or 'travel_budget'."),
                    "role": types.Schema(
                        type=types.Type.STRING,
                        description="Role for an approval_limit query, e.g. 'manager'."),
                    "category": types.Schema(
                        type=types.Type.STRING,
                        description="Category for a travel_budget query, e.g. "
                                    "'international' or 'hotel_tier1'."),
                },
                required=["query_type"],
            ),
        )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent:
    """Runs the LLM-plus-tools loop and keeps a running cost tally."""

    MAX_TOOL_ROUNDS = 5

    def __init__(self, db_path: str, api_key: str = None,
                 model: str = DEFAULT_MODEL,
                 input_rate: float = INPUT_RATE_PER_1M,
                 output_rate: float = OUTPUT_RATE_PER_1M):
        self.db_path = db_path
        self.model = model
        self.input_rate = input_rate
        self.output_rate = output_rate

        self.api_key = api_key or __import__("os").getenv("GOOGLE_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "No API key. Pass api_key= or set GOOGLE_API_KEY. "
                "Free keys: https://aistudio.google.com/app/apikey")
        if not self.api_key.isascii():
            raise ValueError(
                "GOOGLE_API_KEY has non-ASCII characters, which looks like a "
                "placeholder rather than a real key. A real key looks like "
                "'AIza...'. Get one at https://aistudio.google.com/app/apikey")

        self.client = genai.Client(api_key=self.api_key)
        self.tools: Dict[str, Tool] = {
            "employee_lookup": EmployeeLookupTool(db_path),
            "policy_search": PolicySearchTool(),
            "expense_query": ExpenseQueryTool(),
        }

        self.queries_run = 0
        self.total_tokens = 0
        self.total_cost = 0.0

    def query(self, user_query: str, user_role: str = "engineer") -> Dict[str, Any]:
        logger.info("query (%s): %s", user_role, user_query)
        self.queries_run += 1
        in_tokens = 0
        out_tokens = 0

        try:
            gemini_tools = types.Tool(
                function_declarations=[t.declaration() for t in self.tools.values()])
            config = types.GenerateContentConfig(
                system_instruction=self._build_system_prompt(user_role),
                tools=[gemini_tools],
                temperature=0,
            )

            contents: List[types.Content] = [
                types.Content(role="user", parts=[types.Part(text=user_query)])
            ]

            answer = ""
            for _ in range(self.MAX_TOOL_ROUNDS):
                response = self.client.models.generate_content(
                    model=self.model, contents=contents, config=config)
                step_in, step_out = self._tokens(response)
                in_tokens += step_in
                out_tokens += step_out

                calls = self._function_calls(response)
                if not calls:
                    answer = response.text or ""
                    break

                # Record the model's tool-call turn, then run each tool and
                # feed the results back for the next round.
                contents.append(response.candidates[0].content)
                tool_parts = []
                for call in calls:
                    result = self._run_tool(call, user_role)
                    tool_parts.append(types.Part.from_function_response(
                        name=call.name, response={"result": result}))
                contents.append(types.Content(role="user", parts=tool_parts))
            else:
                answer = ("Stopped after the tool limit was reached without a "
                          "final answer.")

            tokens_this_query = in_tokens + out_tokens
            cost = self._estimate_query_cost(in_tokens, out_tokens)
            self.total_tokens += tokens_this_query
            self.total_cost += cost
            return {
                "answer": answer or "(no answer returned)",
                "tokens_used": tokens_this_query,
                "cost": cost,
                "role": user_role,
            }

        except Exception as e:
            logger.exception("query failed")
            tokens_this_query = in_tokens + out_tokens
            cost = self._estimate_query_cost(in_tokens, out_tokens)
            self.total_tokens += tokens_this_query
            self.total_cost += cost
            return {
                "answer": f"Sorry, the request failed: {e}",
                "tokens_used": tokens_this_query,
                "cost": cost,
                "role": user_role,
            }

    def _run_tool(self, call, user_role: str) -> str:
        tool = self.tools.get(call.name)
        if tool is None:
            return f"Unknown tool: {call.name}"
        args = dict(call.args) if call.args else {}
        if call.name == "employee_lookup":
            args["viewer_role"] = user_role
        try:
            return tool.execute(**args)
        except Exception as e:
            logger.error("tool %s failed: %s", call.name, e)
            return f"Tool {call.name} failed: {e}"

    @staticmethod
    def _function_calls(response) -> list:
        calls = []
        if not response.candidates:
            return calls
        for part in response.candidates[0].content.parts or []:
            if getattr(part, "function_call", None):
                calls.append(part.function_call)
        return calls

    @staticmethod
    def _tokens(response):
        """Return (input_tokens, output_tokens) for one model response."""
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            return 0, 0
        return (usage.prompt_token_count or 0, usage.candidates_token_count or 0)

    def _build_system_prompt(self, user_role: str) -> str:
        tool_lines = "\n".join(f"- {t.name}: {t.description}"
                               for t in self.tools.values())
        return (
            "You are TechCorp's internal assistant. Answer the employee's "
            "question using the tools below; call a tool when it has the data "
            "you need instead of guessing.\n\n"
            f"Tools:\n{tool_lines}\n\n"
            f"The person asking has the role '{user_role}'. Some employee "
            "fields may come back marked [restricted]; if so, tell them they "
            "are not authorized to see that field. Keep answers short and "
            "concrete."
        )

    def _estimate_query_cost(self, input_tokens: int, output_tokens: int) -> float:
        input_cost = (input_tokens / 1_000_000) * self.input_rate
        output_cost = (output_tokens / 1_000_000) * self.output_rate
        return input_cost + output_cost

    def get_metrics(self) -> Dict[str, Any]:
        avg = self.total_cost / self.queries_run if self.queries_run else 0.0
        return {
            "total_queries": self.queries_run,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "avg_cost_per_query": avg,
        }


if __name__ == "__main__":
    import sys
    try:
        agent = Agent(str(DATA_DIR / "techcorp.db"))
    except ValueError as e:
        print(e)
        sys.exit(1)
    result = agent.query("What is the expense approval limit for a manager?")
    print("Answer:", result["answer"])
    print(f"Tokens: {result['tokens_used']}  Cost: ${result['cost']:.6f}")
    print("Metrics:", agent.get_metrics())
