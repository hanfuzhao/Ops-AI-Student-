"""
pytest setup for week3.

Puts the week3/ folder on the import path so the tests can do
`from validation.check_data_quality import ...` no matter which directory
pytest is started from (repo root or week3/).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
