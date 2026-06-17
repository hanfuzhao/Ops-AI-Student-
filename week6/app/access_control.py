"""Guardrails for the agent: access control, rate limiting, and cost limits.

These run before (and after) the LLM call. The point is to stop a request
that a user shouldn't be allowed to make before it costs anything, and to
strip sensitive values out of anything we hand back.
"""

import json
import re
import logging
from typing import Dict, Any, List
from datetime import datetime, timezone
from time import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# How document sensitivity maps to who is allowed to read it. Anything not
# listed here (or an unknown level) is treated as the most restrictive.
DOCUMENT_ACCESS = {
    "public": ["engineer", "manager", "hr", "finance", "executive"],
    "internal": ["engineer", "manager", "hr", "finance", "executive"],
    "confidential": ["manager", "hr", "finance", "executive"],
    "restricted": ["finance", "executive"],
}


class AccessController:
    """Role-based access to documents and sensitive fields, with an audit log."""

    def __init__(self, access_policy_path: str):
        with open(access_policy_path) as f:
            self.policy = json.load(f)
        self.sensitive_fields = self.policy.get("sensitive_fields", {})
        self.audit_log: List[Dict[str, Any]] = []

    def can_view_document(self, role: str, document: Dict[str, Any]) -> bool:
        level = str(document.get("sensitivity", "restricted")).lower()
        allowed_roles = DOCUMENT_ACCESS.get(level, DOCUMENT_ACCESS["restricted"])
        return role in allowed_roles

    def can_view_field(self, role: str, field_name: str) -> bool:
        # A field that isn't marked sensitive is visible to everyone.
        field = self.sensitive_fields.get(field_name)
        if field is None:
            return True
        return role in field.get("visibility", [])

    def redact_response(self, role: str, response: str) -> str:
        """Replace values of sensitive fields the role cannot see with [REDACTED]."""
        if not response:
            return response

        redacted = response
        for field_name in self.sensitive_fields:
            if self.can_view_field(role, field_name):
                continue

            # "Salary: $123,456" / "ssn = 123-45-6789" -> keep the label, drop the
            # value. A comma only ends the value when it isn't a thousands
            # separator, so "$467,621" stays together but ", next field" does not.
            label = re.escape(field_name).replace("_", "[ _]")
            redacted = re.sub(
                rf"(?i)\b({label})\b(\s*[:=]\s*)((?:[^,\n;]|,(?=\s*\d))+)",
                r"\1\2[REDACTED]",
                redacted,
            )

            # SSNs are recognisable on their own, so catch an unlabelled one too.
            if field_name == "ssn":
                redacted = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED]", redacted)

        if redacted != response:
            self.log_access(role, "response", allowed=False, field="sensitive")
        return redacted

    def log_access(self, role: str, resource: str, allowed: bool, field: str = None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "resource": resource,
            "allowed": allowed,
        }
        if field is not None:
            entry["field"] = field
        self.audit_log.append(entry)

    def filter_documents(self, role: str, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        visible = []
        for doc in documents:
            allowed = self.can_view_document(role, doc)
            self.log_access(role, doc.get("id", doc.get("title", "?")), allowed)
            if allowed:
                visible.append(doc)
        return visible

    def get_audit_log(self) -> List[Dict[str, Any]]:
        return self.audit_log


class RateLimiter:
    """Allow at most N queries per user in any rolling 60-second window."""

    def __init__(self, max_queries_per_minute: int = 30):
        self.max_queries_per_minute = max_queries_per_minute
        self.user_query_times: Dict[str, List[float]] = {}

    def _recent(self, user_id: str) -> List[float]:
        cutoff = time() - 60
        recent = [t for t in self.user_query_times.get(user_id, []) if t > cutoff]
        self.user_query_times[user_id] = recent
        return recent

    def is_allowed(self, user_id: str) -> bool:
        recent = self._recent(user_id)
        if len(recent) >= self.max_queries_per_minute:
            return False
        recent.append(time())
        return True

    def get_remaining_queries(self, user_id: str) -> int:
        return max(0, self.max_queries_per_minute - len(self._recent(user_id)))


class CostEnforcer:
    """Track spend per user and block queries that would blow the role budget."""

    DEFAULT_BUDGETS = {
        "engineer": 100.0,
        "manager": 500.0,
        "hr": 200.0,
        "finance": 500.0,
        "executive": 1000.0,
    }

    def __init__(self, policy_path: str = None):
        self.role_budgets = dict(self.DEFAULT_BUDGETS)
        if policy_path:
            with open(policy_path) as f:
                self.role_budgets.update(json.load(f).get("role_budgets", {}))
        self.user_spending: Dict[str, Dict[str, Any]] = {}

    def add_cost(self, user_id: str, role: str, cost: float):
        entry = self.user_spending.setdefault(user_id, {"role": role, "total": 0.0})
        entry["role"] = role
        entry["total"] += cost

    def _role_of(self, user_id: str, role: str = None):
        return role or self.user_spending.get(user_id, {}).get("role")

    def can_afford_query(self, user_id: str, estimated_cost: float, role: str = None) -> bool:
        role = self._role_of(user_id, role)
        if role is None:
            # We don't know the user's role yet, so there is no budget to
            # enforce against. It gets recorded on the first add_cost.
            return True
        spent = self.user_spending.get(user_id, {}).get("total", 0.0)
        return estimated_cost <= (self.role_budgets.get(role, 0.0) - spent)

    def get_budget_remaining(self, user_id: str, role: str = None) -> float:
        role = self._role_of(user_id, role)
        if role is None:
            return 0.0
        spent = self.user_spending.get(user_id, {}).get("total", 0.0)
        return max(0.0, self.role_budgets.get(role, 0.0) - spent)
