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

# [LOCAL-PATCH] G：待发货超时告警。复用与企业微信 Token 异常同一套通知渠道
# （notification_channels.type='wechat' 的 webhook），不改发货主链路、不改看板。
ALERT_AFTER_MINUTES = int(os.environ.get("XY_ALERT_AFTER_MINUTES", "15"))
ALERT_COOLDOWN_MINUTES = int(os.environ.get("XY_ALERT_COOLDOWN_MINUTES", "30"))
ALERT_DRY_RUN = os.environ.get("XY_ALERT_DRY_RUN", "") not in ("", "0", "false", "False")


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


def load_wechat_webhooks(cookie_id):
    """读取该账号启用的企业微信渠道 webhook（与 Token 异常通知同一张表）。"""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "select nc.config from message_notifications mn "
            "join notification_channels nc on mn.channel_id = nc.id "
            "where mn.cookie_id = ? and mn.enabled = 1 and nc.enabled = 1 and nc.type = 'wechat'",
            (cookie_id,),
        ).fetchall()
    except Exception as exc:
        log(f"  [告警] 读取通知渠道失败: {exc}")
        return []
    finally:
        conn.close()
    urls = []
    for (cfg,) in rows:
        try:
            data = json.loads(cfg) if isinstance(cfg, str) else (cfg or {})
        except Exception:
            continue
        url = str((data or {}).get("webhook_url") or "").strip()
        if url:
            urls.append(url)
    return urls


def send_wechat(webhook_url, message):
    payload = json.dumps({"msgtype": "text", "text": {"content": message}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8", "replace")


def find_overdue_orders():
    """pending_ship 且 system_shipped=0 且已超过 ALERT_AFTER_MINUTES 分钟。"""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cutoff = (datetime.now() - timedelta(minutes=ALERT_AFTER_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        return conn.execute(
            "select order_id,item_id,buyer_id,chat_id,amount,created_at,cookie_id,receiver_name from orders "
            "where order_status='pending_ship' and coalesce(system_shipped,0)=0 "
            "and created_at <= ? order by created_at",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()


def item_titles(item_ids):
    if not item_ids:
        return {}
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "select item_id, item_title from item_info where item_id in (%s)"
            % ",".join("?" * len(item_ids)),
            list(item_ids),
        ).fetchall()
        return {str(r[0]): (r[1] or "") for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def account_labels(cookie_ids):
    """账号显示名：优先备注，其次昵称，查不到回落 ID。"""
    cookie_ids = [c for c in cookie_ids if c]
    if not cookie_ids:
        return {}
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "select id, remark, nickname from cookies where id in (%s)"
            % ",".join("?" * len(cookie_ids)),
            cookie_ids,
        ).fetchall()
        return {str(r[0]): ((r[1] or r[2] or "").strip() or str(r[0])) for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def alert_overdue_orders(state):
    """同一订单 30 分钟内只提醒一次；返回本轮提醒的订单数。"""
    overdue = find_overdue_orders()
    if not overdue:
        return 0
    now = datetime.now()
    titles = item_titles({str(r["item_id"] or "") for r in overdue})
    accounts = account_labels({str(r["cookie_id"] or "") for r in overdue})
    groups = {}
    for row in overdue:
        oid = row["order_id"]
        st = dict(state.get(oid) or {})
        last_alert = str(st.get("alert_at") or "")
        if last_alert:
            try:
                gap = (now - datetime.strptime(last_alert, "%Y-%m-%d %H:%M:%S")).total_seconds()
                if gap < ALERT_COOLDOWN_MINUTES * 60:
                    continue
            except ValueError:
                pass
        groups.setdefault(str(row["cookie_id"] or ""), []).append((row, st))

    alerted = 0
    for cookie_id, items in groups.items():
        webhooks = load_wechat_webhooks(cookie_id)
        # [LOCAL-PATCH] 告警文案：账号显示昵称，商品显示标题，时间只留月日时分，去掉单号等噪音。
        account_label = accounts.get(str(cookie_id), str(cookie_id))
        waits = []
        for row, _st in items:
            try:
                waits.append(int((now - datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")).total_seconds() // 60))
            except ValueError:
                waits.append(ALERT_AFTER_MINUTES)
        lines = [
            "⏰ 待发货超时，需要处理",
            "",
            f"账号: {account_label}",
            f"共 {len(items)} 笔，最早已等 {max(waits) if waits else ALERT_AFTER_MINUTES} 分钟",
            "",
        ]
        for idx, (row, st) in enumerate(items, 1):
            waited = waits[idx - 1] if idx - 1 < len(waits) else ALERT_AFTER_MINUTES
            buyer = (row["receiver_name"] or "").strip()
            buyer_text = f"买家 {buyer}" if buyer else "买家未留名"
            created = str(row["created_at"] or "")[5:16]
            title = titles.get(str(row["item_id"] or "")) or str(row["item_id"] or "未知商品")
            extra = f"，自动补发已失败 {st.get('fails', 0)} 次" if int(st.get("fails", 0) or 0) else ""
            lines.append(
                f"{idx}. {title}\n"
                f"   ¥{row['amount'] or '0'} · {buyer_text} · {created} 下单，已等 {waited} 分钟{extra}"
            )
        lines.append("")
        lines.append("请尽快发货，超时会被平台处罚。")
        message = "\n".join(lines)

        if not webhooks:
            log(f"  [告警] 账号 {cookie_id} 未配置企业微信渠道，跳过 {len(items)} 笔")
            continue
        if ALERT_DRY_RUN:
            log(f"  [告警][DRY-RUN] 账号 {cookie_id} 待推送 {len(items)} 笔:\n{message}")
        else:
            for url in webhooks:
                try:
                    resp = send_wechat(url, message)
                    log(f"  [告警] 账号 {cookie_id} 推送 {len(items)} 笔超时订单，渠道响应: {resp[:120]}")
                except Exception as exc:
                    log(f"  [告警] 账号 {cookie_id} 推送失败: {exc}")
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        for row, st in items:
            st["alert_at"] = stamp
            st["last"] = stamp
            state[row["order_id"]] = st
            alerted += 1
    return alerted


def read_order_fields(order_id):
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    try:
        return conn.execute(
            "select item_id, buyer_id, chat_id from orders where order_id=?", (order_id,)
        ).fetchone()
    finally:
        conn.close()


# [LOCAL-PATCH] D3：发货成功后的异步回写会把 item_id/buyer_id 覆盖成 chat_id，
# 延迟 3 秒复读该行并最多补修 3 次（约 9 秒），每次记日志。上游合并时需重放。
def verify_and_repair_fields(order_id, before_item, before_buyer, attempts=3, interval=3):
    for i in range(attempts):
        time.sleep(interval)
        row = read_order_fields(order_id)
        if not row:
            log(f"  [字段校验] {order_id} 第{i + 1}次: 订单行已不存在，停止校验")
            return
        item, buyer, chat_id = row[0], row[1], (row[2] or "")
        problems = []
        if chat_id and str(item or "") == str(chat_id):
            problems.append("item_id=chat_id")
        if chat_id and str(buyer or "") == str(chat_id):
            problems.append("buyer_id=chat_id")
        if before_item and str(item or "") != str(before_item):
            problems.append(f"item_id变化 {before_item}->{item}")
        if before_buyer and str(buyer or "") != str(before_buyer):
            problems.append(f"buyer_id变化 {before_buyer}->{buyer}")
        if problems:
            log(f"  [字段修复] {order_id} 第{i + 1}次发现 {'; '.join(problems)}，重新修复")
            repair_order_fields(order_id, before_item, before_buyer)
        else:
            log(f"  [字段校验] {order_id} 第{i + 1}次通过: item_id={item}, buyer_id={buyer}, chat_id={chat_id}")


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
                    verify_and_repair_fields(oid, before_item, before_buyer)
                    log(f"  [OK] {oid} 补发成功: {item_result.get('message', '')}")
                    # [LOCAL-PATCH] G：发货成功即视为恢复，后续不再提醒
                    log(f"  [已恢复] {oid} 发货成功，停止超时提醒")
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

        # [LOCAL-PATCH] G：本轮补发结束后，对仍未发货且超过 15 分钟的订单推一次企业微信提醒
        try:
            alerted = alert_overdue_orders(state)
            if alerted:
                log(f"本轮超时告警: {alerted} 笔")
        except Exception as alert_exc:
            log(f"[告警] 超时提醒异常（不影响补发）: {alert_exc}")

        save_state(state)
    except Exception as exc:
        log(f"[ERROR] 巡检异常: {exc}")
    finally:
        release_lock()


if __name__ == "__main__":
    main()
