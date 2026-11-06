import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(ROOT, "rescue_config.json")
LOG_PATH = os.path.join(ROOT, "logs", "pending_rescue.log")
LOCK_PATH = os.path.join(ROOT, "data", "pending_rescue.lock")
STATE_PATH = os.path.join(ROOT, "data", "pending_rescue_state.json")
DB_PATH = os.environ.get("XY_DB_PATH") or os.path.join(ROOT, "data", "xianyu_data.db")


def log(msg):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 5 * 1024 * 1024:
            os.replace(LOG_PATH, LOG_PATH + ".1")
    except OSError:
        pass
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def load_config():
    with open(CFG_PATH, encoding="utf-8") as f:
        return json.load(f)


def http(cfg, method, path, body=None, token=None, timeout=30):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(cfg["base_url"].rstrip("/") + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:300]}")
    except Exception as exc:
        raise RuntimeError(str(exc))


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
    state = {
        k: v for k, v in state.items()
        if (v.get("at") or v.get("last") or "") >= cutoff
    }
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def acquire_lock():
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    if os.path.exists(LOCK_PATH):
        try:
            age = time.time() - os.path.getmtime(LOCK_PATH)
        except OSError:
            age = 999
        if age < 600:
            return False
        os.remove(LOCK_PATH)
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


def service_alive(cfg):
    try:
        with urllib.request.urlopen(cfg["base_url"].rstrip("/") + "/", timeout=5) as resp:
            return 200 <= getattr(resp, "status", 200) < 500
    except Exception:
        return False


def find_chat_id(cfg, token, cookie_id, buyer_id):
    try:
        res = http(cfg, "GET", f"/chat/conversations/{cookie_id}?limit=100", token=token, timeout=45)
    except RuntimeError as exc:
        log(f"  [FAIL] 拉取会话列表失败: {exc}")
        return ""
    for conv in (res.get("data", {}).get("conversations") or []):
        if str(conv.get("otherUserId")) == str(buyer_id):
            return str(conv.get("cid") or "")
    return ""


def update_order_field(order_id, field, value):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute(f"update orders set {field}=? where order_id=?", (value, order_id))
        conn.commit()
    finally:
        conn.close()


def repair_order_fields(order_id, before_item, before_buyer):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        row = conn.execute(
            "select item_id, buyer_id from orders where order_id=?", (order_id,)
        ).fetchone()
        if not row:
            return
        if before_item and row[0] != before_item:
            conn.execute("update orders set item_id=? where order_id=?", (before_item, order_id))
        if before_buyer and row[1] != before_buyer and row[1] != "unknown_user":
            conn.execute("update orders set buyer_id=? where order_id=?", (before_buyer, order_id))
        conn.commit()
    finally:
        conn.close()


def main():
    if not acquire_lock():
        log("上一轮仍在执行，跳过本轮")
        return
    try:
        cfg = load_config()
        if not service_alive(cfg):
            log("服务未就绪，跳过本轮")
            return

        try:
            login = http(cfg, "POST", "/login", {
                "username": cfg.get("username", "admin"),
                "password": cfg.get("password", ""),
            }, timeout=15)
        except RuntimeError as exc:
            log(f"[ERROR] 登录后台失败: {exc}")
            return
        token = login.get("token")
        if not token:
            log(f"[ERROR] 登录未返回 token: {login}")
            return

        state = load_state()
        min_age = datetime.now() - timedelta(minutes=int(cfg.get("min_age_minutes", 2)))
        max_age = datetime.now() - timedelta(hours=int(cfg.get("lookback_hours", 72)))
        max_fails = int(cfg.get("max_fails", 5))

        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "select order_id, item_id, buyer_id, chat_id, amount, created_at, cookie_id "
                "from orders where order_status='pending_ship' and system_shipped=0 "
                "and created_at >= ? and created_at <= ? order by created_at",
                (max_age.strftime("%Y-%m-%d %H:%M:%S"), min_age.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchall()
        finally:
            conn.close()

        log(f"本轮候选待发货订单: {len(rows)} 笔")
        for row in rows:
            oid = row["order_id"]
            st = state.get(oid) or {}
            if st.get("status") == "done" or int(st.get("fails", 0)) >= max_fails:
                continue

            before_item, before_buyer = row["item_id"], row["buyer_id"]
            chat_id = row["chat_id"] or ""
            if not chat_id:
                chat_id = find_chat_id(cfg, token, row["cookie_id"], row["buyer_id"])
                if chat_id:
                    update_order_field(oid, "chat_id", chat_id)
                    log(f"  [{oid}] 已补齐 chat_id={chat_id}")

            if not chat_id:
                st["fails"] = int(st.get("fails", 0)) + 1
                st["last"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                state[oid] = st
                log(f"  [SKIP] {oid} 未找到买家会话，待下次重试 (fails={st['fails']})")
                continue

            try:
                res = http(cfg, "POST", "/api/orders/manual-ship", {
                    "order_ids": [oid],
                    "ship_mode": "full_delivery",
                }, token=token, timeout=120)
                item_result = (res.get("results") or [{}])[0]
                ok = bool(res.get("success")) and bool(item_result.get("success"))
                if ok:
                    state[oid] = {"status": "done", "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "fails": 0}
                    repair_order_fields(oid, before_item, before_buyer)
                    log(f"  [OK] {oid} 补发成功: {item_result.get('message', '')}")
                else:
                    st["fails"] = int(st.get("fails", 0)) + 1
                    st["last"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    state[oid] = st
                    log(f"  [FAIL] {oid} 补发失败: {item_result.get('message', res)} (fails={st['fails']})")
            except RuntimeError as exc:
                st["fails"] = int(st.get("fails", 0)) + 1
                st["last"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                state[oid] = st
                log(f"  [FAIL] {oid} 调用发货接口异常: {exc} (fails={st['fails']})")

        save_state(state)
    except Exception as exc:
        log(f"[ERROR] 巡检异常: {exc}")
    finally:
        release_lock()


if __name__ == "__main__":
    main()
