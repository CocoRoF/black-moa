"""호감도를 실제 기록으로 다시 센다 (plan/61).

    python -m blackmoa.scripts.recompute_affinity            # 바뀔 값만 보인다
    python -m blackmoa.scripts.recompute_affinity --apply    # 적용한다

규칙이 바뀌었거나(예: 대화 상승분이 붙지 않던 결함을 고친 뒤) 값이 의심스러울 때. 실시간과 같은 엔진
(``services/relationship``)으로 돌리므로, 여기서 나온 값이 그 규칙이 처음부터 있었다면의 값이다.
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select


async def main(apply: bool) -> None:
    from blackmoa.db.session import session_scope
    from blackmoa.models import AgentRelationship
    from blackmoa.services import relationship as R

    async with session_scope() as db:
        rels = (await db.execute(select(AgentRelationship).where(AgentRelationship.started_at.isnot(None)))).scalars().all()
        print(f"{'owner':32} {'agent':10} {'seed':>10} {'before':>7} {'after':>7}  why")
        for rel in rels:
            r = await R.recompute(db, rel)
            whys: dict[str, float] = {}
            for e in r["log"]:
                k = e["why"].split("_")[0] if e["why"].startswith("quiet") else e["why"]
                whys[k] = round(whys.get(k, 0.0) + e["d"], 2)
            print(f"{r['owner'][:32]:32} {r['agent'][:10]:10} {r['seed_stage'] + ' ' + str(int(r['seed'])):>10} "
                  f"{r['before']:7.2f} {r['after']:7.2f}  {whys}")
            if apply:
                await R.apply_recompute(db, rel, r)
        if apply:
            await db.commit()
            print(f"applied to {len(rels)} pairs")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    asyncio.run(main(ap.parse_args().apply))
