"""The secretary reads the company directory (plan/40 §7).

One tool, owner-only: name a company and the secretary gets what the exchange knows and
what members have said — the numbers the page shows, the most helpful reviews, the open
postings — so it can brief its owner, compare, or prepare them for an interview without
the owner leaving the chat. Reviews are anonymous here as everywhere.
"""
from __future__ import annotations

import uuid

from memora.db.session import session_scope
from memora.pipeline.tools.base import SecretaryTool, secretary_tool


@secretary_tool
class CompanyLookup(SecretaryTool):
    tool_name = "company_lookup"
    tool_description = ("Look up a company in Memora's directory (listed Korean companies + member reviews): facts from the "
                        "exchange, the rating and its five axes, recommendation rates, pay figures, interview accounts, "
                        "benefits, the most helpful reviews and open postings. Use it whenever the owner asks about a "
                        "company, wants to compare employers, or is preparing for an interview there. Give the name as the "
                        "owner said it; pick the best match and say which one you took.")
    schema = {"type": "object", "properties": {
        "name": {"type": "string", "description": "company name as the owner said it (part of it is fine)"},
        "company_id": {"type": "string", "description": "a company id from an earlier result, when the owner means that one"},
    }}
    audiences = frozenset({"owner"})
    # 관리자가 기업 기능을 끄면 비서도 기업을 찾지 않는다 (plan/71).
    requires_feature = "companies"
    label_template = "기업 정보를 찾는 중"

    async def run(self, args):
        from memora.models import Company
        from memora.services import community as C
        from memora.services.companies import reviews as RV
        from memora.services.companies.query import suggest

        name = str(args.get("name") or "").strip()
        cid = str(args.get("company_id") or "").strip()
        async with session_scope() as db:
            company = None
            if cid:
                try:
                    company = await db.get(Company, uuid.UUID(cid))
                except ValueError:
                    company = None
            candidates = []
            if company is None and name:
                candidates = await suggest(db, name, limit=5)
                if candidates:
                    company = await db.get(Company, uuid.UUID(candidates[0]["id"]))
            if company is None or company.hidden:
                return {"found": False, "candidates": candidates,
                        "note": "No such company in the directory (listed companies only). Say so; do not invent figures."}
            card = RV.card(company)
            st = company.stats or {}
            top = await RV.list_reviews(db, company_id=company.id, user=None, sort="helpful", size=3)
            jobs = await C.list_jobs(db, company_id=company.id, limit=5)
            out = {
                "found": True,
                "company": {**card, "product": company.product, "address": company.address, "founded_on": company.founded_on.isoformat() if company.founded_on else None,
                            "page": f"/app/community/companies/{company.id}"},
                "stats": {k: st.get(k) for k in ("n", "rating", "axes", "recommend", "ceo", "growth", "salary", "interview", "employment")} if st.get("n") else None,
                "benefits": [b["code"] for b in (st.get("benefits") or [])[:8]],
                "top_reviews": [{"title": r["title"], "rating": r["rating"], "family": r["family_label"], "employment": r["employment"],
                                 "year": r["work_year"], "pros": r["pros"][:300], "cons": r["cons"][:300]} for r in top["items"]],
                "open_jobs": [{"title": j.title, "location": j.location, "salary_min": j.salary_min, "salary_max": j.salary_max,
                               "apply_url": j.apply_url} for j in jobs],
                "other_matches": [c for c in candidates[1:4]] if candidates else [],
                "note": ("Reviews are anonymous member opinions, not facts — say how many there are. When there are none, "
                         "say so and offer what the exchange knows. Link the page when useful."),
            }
        self.ctx.card("company_card", {"company": card, "stats": {"n": st.get("n", 0), "rating": st.get("rating", 0),
                                                                    "recommend": st.get("recommend"), "salary_median": (st.get("salary") or {}).get("median")}})
        return out
