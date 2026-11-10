import os
import sqlite3
import sys
from datetime import datetime, timedelta

DB = sys.argv[1]

STATUS_LABEL = {
    "pending_ship": "待发货",
    "shipped": "已发货",
    "completed": "已完成",
    "cancelled": "已取消",
    "processing": "处理中",
    "refunded": "已退款",
    "unknown": "未知",
}


def money(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def day_range(offset=0):
    day = datetime.now().date() + timedelta(days=offset)
    start = datetime(day.year, day.month, day.day)
    return start, start + timedelta(days=1)


def month_start():
    now = datetime.now()
    return datetime(now.year, now.month, 1)


def fetch(con, start, end):
    return con.execute(
        "select order_id,item_id,buyer_id,order_status,amount,refund_fee,created_at "
        "from orders where created_at >= ? and created_at < ?",
        (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchall()


def summarize(rows):
    valid = [r for r in rows if r[3] != "cancelled"]
    # [LOCAL-PATCH] 只把「有金额」的单算作成交：他人店铺的卡片被误抓进来时金额为空，
    # 计入会把订单数虚增、客单价拉低。这类单单独计数，不影响金额与人均。
    paid = [r for r in valid if money(r[4]) > 0]
    gross = sum(money(r[4]) for r in paid)
    refund = sum(money(r[5]) for r in paid)
    buyers = len({r[2] for r in paid if r[2]})
    pending = [r for r in valid if r[3] == "pending_ship"]
    status_count = {}
    for r in paid:
        status_count[r[3]] = status_count.get(r[3], 0) + 1
    return {
        "count": len(paid),
        "buyers": buyers,
        "gross": gross,
        "refund": refund,
        "net": gross - refund,
        "pending_count": len(pending),
        "pending_value": sum(money(r[4]) for r in pending),
        "status": status_count,
        "cancelled": len(rows) - len(valid),
        "anomaly": len(valid) - len(paid),
    }


con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
now = datetime.now()
today_start, tomorrow = day_range(0)
yest_start, today_end = day_range(-1)
mstart = month_start()

today_rows = fetch(con, today_start, tomorrow)
yest_rows = fetch(con, yest_start, today_end)
month_rows = fetch(con, mstart, tomorrow)
t = summarize(today_rows)
y = summarize(yest_rows)
m = summarize(month_rows)

pending_all = con.execute(
    "select count(*), coalesce(sum(amount),0) from orders where order_status='pending_ship' and system_shipped=0"
).fetchone()

recent = con.execute(
    "select o.created_at, o.item_id, o.order_status, o.amount, "
    "(select i.item_title from item_info i where i.item_id=o.item_id and i.cookie_id=o.cookie_id limit 1) as title "
    "from orders o where o.created_at >= ? and o.created_at < ? and o.order_status != 'cancelled' "
    "order by o.created_at desc",
    (today_start.strftime("%Y-%m-%d %H:%M:%S"), tomorrow.strftime("%Y-%m-%d %H:%M:%S")),
).fetchall()

# 今日商品小计（同款合并；只统计有金额的成交单）
goods = {}
for r in recent:
    if money(r[3]) <= 0:
        continue
    key = (r[4] or r[1] or "未识别商品").strip()
    g = goods.setdefault(key, {"count": 0, "amount": 0.0})
    g["count"] += 1
    g["amount"] += money(r[3])

# 待发货明细（有就列出来，方便直接处理）
pending_rows = con.execute(
    "select o.created_at, o.item_id, o.amount, "
    "(select i.item_title from item_info i where i.item_id=o.item_id and i.cookie_id=o.cookie_id limit 1) as title "
    "from orders o where o.order_status='pending_ship' and o.system_shipped=0 "
    "order by o.created_at",
).fetchall()


def short(text, width=24):
    text = (text or "").strip() or "未知商品"
    return text if len(text) <= width else text[:width] + "…"

print(f"──────────── 今日经营概览 {now:%Y-%m-%d} ────────────")
status_text = " / ".join(
    f"{STATUS_LABEL.get(k, k)} {v}" for k, v in sorted(t["status"].items())
) or "无"
cancel_note = f" · 取消 {t['cancelled']}" if t["cancelled"] else ""
print(f"今日订单   {t['count']} 笔（{status_text}{cancel_note}）")
print(f"今日买家   {t['buyers']} 人")
print(f"今日销售额 ¥{t['gross']:.2f}（未扣平台费）")
print(f"今日退款   ¥{t['refund']:.2f}")
print(f"今日净收入 ¥{t['net']:.2f}")
avg = t["net"] / t["count"] if t["count"] else 0
print(f"客单价     ¥{avg:.2f}")
month_avg = m["net"] / now.day if now.day else 0
print(f"本月累计   {m['count']} 笔 / ¥{m['net']:.2f}（日均 ¥{month_avg:.2f}）")
diff_count = t["count"] - y["count"]
diff_money = t["net"] - y["net"]
print(f"昨日对比   {y['count']} 笔 / ¥{y['net']:.2f}（订单{diff_count:+d}，金额{diff_money:+.2f}）")
if t["anomaly"]:
    print(f"异常单据   {t['anomaly']} 笔无金额（多为他人店铺消息误判，不计入以上统计）")

if recent:
    print("")
    print(f"今日成交明细（{len(recent)} 笔，按时间倒序）：")
    for r in recent:
        amount = money(r[3])
        tag = "" if amount > 0 else "  ← 无金额，未计入"
        print(f"  {r[0][11:16]}  {short(r[4] or r[1])}  ¥{amount:.2f}  {STATUS_LABEL.get(r[2], r[2])}{tag}")

    print("")
    print("今日商品小计：")
    for title, g in sorted(goods.items(), key=lambda kv: (-kv[1]["count"], -kv[1]["amount"])):
        print(f"  {short(title, 26)}  ×{g['count']}  ¥{g['amount']:.2f}")
else:
    print("")
    print("今日成交明细：今日暂无成交")

if pending_rows:
    print("")
    print(f"待发货明细（{len(pending_rows)} 笔，需要人工处理）：")
    for r in pending_rows:
        print(f"  {r[0][5:16]}  {short(r[3] or r[1])}  ¥{money(r[2]):.2f}")

last_created = con.execute("select max(created_at) from orders").fetchone()[0]
try:
    db_mtime = datetime.fromtimestamp(os.path.getmtime(DB))
except OSError:
    db_mtime = None
fresh = []
if last_created:
    stamp = last_created[11:16] if last_created[:10] == now.strftime("%Y-%m-%d") else last_created[5:16]
    fresh.append(f"最新订单 {stamp}")
if db_mtime:
    mins = max(int((now - db_mtime).total_seconds() // 60), 0)
    fresh.append(f"库文件更新 {db_mtime:%H:%M}（{mins} 分钟前）")
if fresh:
    print("")
    print("数据新鲜度 " + " · ".join(fresh))

print("")
print("说明：金额取自本地订单实付，未扣平台服务费；以订单库为准。")

con.close()
