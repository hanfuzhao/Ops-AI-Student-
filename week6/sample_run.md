# Week 6 guardrails demo

Output of `python3 demo_guardrails.py`. All checks are pure policy logic,
so they run offline (no API key, no cost) and are reproducible.

```
ACCESS CONTROL: who can see which fields
------------------------------------------------------------
field     engineer  manager   hr        finance   
name      allow     allow     allow     allow     
salary    DENY      DENY      allow     allow     
ssn       DENY      DENY      allow     allow     
address   DENY      DENY      allow     DENY      

DOCUMENT ACCESS by sensitivity
------------------------------------------------------------
  engineer  can read: ['doc_public', 'doc_internal']
  manager   can read: ['doc_public', 'doc_internal', 'doc_confidential']

REDACTION: same record, different roles
------------------------------------------------------------
  raw       : Employee: Brian Yang, Salary: $467,621, SSN: 123-45-6789, Address: 12 Main St
  engineer  : Employee: Brian Yang, Salary: [REDACTED], SSN: [REDACTED], Address: [REDACTED]
  finance   : Employee: Brian Yang, Salary: $467,621, SSN: 123-45-6789, Address: [REDACTED]
  hr        : Employee: Brian Yang, Salary: $467,621, SSN: 123-45-6789, Address: 12 Main St

RATE LIMIT: 3 queries/minute per user
------------------------------------------------------------
  alice query 1: allowed (remaining 2)
  alice query 2: allowed (remaining 1)
  alice query 3: allowed (remaining 0)
  alice query 4: BLOCKED (remaining 0)
  alice query 5: BLOCKED (remaining 0)
  bob query 1: allowed (separate budget from alice)

COST ENFORCEMENT: per-role monthly budget
------------------------------------------------------------
  engineer budget: $100
  after spending $95, remaining: $5
  can afford a $4 query?  True
  can afford a $10 query? False

All guardrails enforced before any LLM call.
```
