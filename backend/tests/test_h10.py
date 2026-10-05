"""回归：落盘成功后总览不得再按「重算中」规则藏行；观察员保持只读。"""

import asyncio

from jose import jwt

import api


def _token(username: str, role: str) -> str:
    return jwt.encode({"sub": username, "role": role}, api.SECRET, algorithm="HS256")


def _row(i: int) -> dict:
    return {
        "id": i,
        "turbine_code": f"W{i:02d}",
        "yaw_err_deg": 0.4,
        "status": "done",
        "verdict": "合格",
        "reason": "偏航误差 0.4° 在 ±1.5° 以内",
        "created_by": "technician",
        "created_at": None,
        "processed_at": None,
    }


def _fetch_list(rows, monkeypatch, username="observer", role="reader"):
    async def fake_run_db(fn, *args, **kwargs):
        return rows

    monkeypatch.setattr(api, "run_db", fake_run_db)

    async def main():
        client = api.app.test_client()
        resp = await client.get(
            "/api/logs",
            headers={"Authorization": f"Bearer {_token(username, role)}"},
        )
        assert resp.status_code == 200
        return await resp.get_json()

    return asyncio.run(main())


def test_newest_persisted_row_is_listed(monkeypatch):
    # 落盘成功的新行（id 最大、排在最前）必须出现在总览里。
    data = _fetch_list([_row(3), _row(2), _row(1)], monkeypatch)
    assert [r["id"] for r in data] == [3, 2, 1]


def test_burst_submissions_all_stay_listed(monkeypatch):
    # 连续快送：每一笔成功后都不得再被「重算中」规则藏掉。
    rows = [_row(i) for i in range(9, 0, -1)]
    data = _fetch_list(rows, monkeypatch)
    assert [r["id"] for r in data] == [r["id"] for r in rows]


def test_observer_stays_read_only():
    async def main():
        client = api.app.test_client()
        resp = await client.post(
            "/api/logs",
            json={"turbine_code": "W09", "yaw_err_deg": 0.1},
            headers={"Authorization": f"Bearer {_token('observer', 'reader')}"},
        )
        return resp.status_code

    assert asyncio.run(main()) == 403
