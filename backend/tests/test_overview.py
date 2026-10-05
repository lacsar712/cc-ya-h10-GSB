"""总览链路回归：落盘成功（done）的行必须在 /api/logs 全量返回，
不得再以“整理进行中”为由把最新行藏掉；连续快送多笔同样笔笔可见。"""

import asyncio
import importlib.util
from datetime import datetime, timezone

import api


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return {"n": len(self._rows)}


class FakeConn:
    def __init__(self, store):
        self._store = store

    def execute(self, sql, *args, **kwargs):
        # 列表接口按 id DESC 返回；其余语句（建表/种子）给空结果即可。
        if "FROM yaw_logs" in sql:
            return FakeResult(list(reversed(self._store)))
        return FakeResult([])

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _row(id_, status="done"):
    now = datetime.now(timezone.utc)
    done = status == "done"
    return {
        "id": id_,
        "turbine_code": f"W{id_:02d}",
        "yaw_err_deg": 0.4,
        "status": status,
        "verdict": "合格" if done else None,
        "reason": "在 ±1.5° 以内" if done else None,
        "created_by": "technician",
        "created_at": now,
        "processed_at": now if done else None,
    }


async def _run_overview_scenario():
    store = [_row(1), _row(2)]

    def fake_connect():
        return FakeConn(store)

    api.connect = fake_connect  # api.py 内 `from db import connect` 的绑定

    async with api.app.test_client() as client:
        login = await client.post(
            "/api/auth/login",
            json={"username": "technician", "password": "tech123456"},
        )
        token = (await login.get_json())["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 初始：两条已完成种子行都在，最新行（id=2）不得被藏
        res = await client.get("/api/logs", headers=headers)
        rows = await res.get_json()
        assert res.status_code == 200
        assert [r["id"] for r in rows] == [2, 1]

        # 连续快送三笔：每笔先 pending（可见），worker 落盘 done 后仍必须可见
        for new_id in (3, 4, 5):
            store.append(_row(new_id, status="pending"))
            res = await client.get("/api/logs", headers=headers)
            rows = await res.get_json()
            ids = [r["id"] for r in rows]
            assert new_id in ids, f"待处理的新行 {new_id} 也应在总览可见"

            store[-1] = _row(new_id, status="done")  # worker 认领并落盘
            res = await client.get("/api/logs", headers=headers)
            rows = await res.get_json()
            ids = [r["id"] for r in rows]
            newest = max(ids)
            assert newest == new_id
            assert rows[0]["id"] == newest, "落盘成功后最新行仍被‘整理中’规则藏掉"
            assert rows[0]["status"] == "done"
            assert rows[0]["verdict"] == "合格"
            assert ids == list(range(new_id, 0, -1))

        # 只读账号看到的也是同一份全量数据
        login = await client.post(
            "/api/auth/login",
            json={"username": "observer", "password": "obs123456"},
        )
        obs_token = (await login.get_json())["access_token"]
        res = await client.get(
            "/api/logs", headers={"Authorization": f"Bearer {obs_token}"}
        )
        rows = await res.get_json()
        assert [r["id"] for r in rows] == [5, 4, 3, 2, 1]


def test_done_rows_never_hidden_as_organizing():
    asyncio.run(_run_overview_scenario())


def test_trap_modules_removed():
    for name in (
        "hide_new",
        "h10_extra_trap",
        "h10_ui_trap",
    ):
        assert importlib.util.find_spec(name) is None, f"{name} 藏行模块不应再存在"
