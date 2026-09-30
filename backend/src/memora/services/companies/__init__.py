"""Company information, collected in batches from national and exchange sources (plan/33).

Each source is a module with the same shape — ``fetch()`` returns rows, ``SOURCE`` names
it, and the merge rules live in ``merge.py`` — so adding the tax office next to the
exchange is a module, not a rewrite.
"""
from __future__ import annotations

from memora.services.companies.merge import apply_rows, normalise_name
from memora.services.companies.taxonomy import industry_codes_for, region_code_for

__all__ = ["apply_rows", "normalise_name", "industry_codes_for", "region_code_for"]
