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
    gross = sum(money(r[4]) for r in valid)
    refund = sum(money(r[5]) for r in valid)
    buyers = len({r[2] for r in valid if r[2]})
    pending = [r for r in valid if r[3] == "pending_ship"]
    status_count = {}
    for r in valid:
        status_count[r[3]] = status_count.get(r[3], 0) + 1
    return {
        "count": len(valid),
        "buyers": buyers,
        "gross": gross,
        "refund": refund,
        "net": gross - refund,
        "pending_count": len(pending),
        "pending_value": sum(money(r[4]) for r in pending),
        "status": status_count,
        "cancelled": len(rows) - len(valid),
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
    "order by o.created_at desc limit 5",
    (today_start.strftime("%Y-%m-%d %H:%M:%S"), tomorrow.strftime("%Y-%m-%d %H:%M:%S")),
).fetchall()

print(f"──────────── 今日经营概览 {now:%Y-%m-%d} ────────────")
status_text = " / ".join(
    f"{STATUS_LABEL.get(k, k)} {v}" for k, v in sorted(t["status"].items())
) or "无"
print(f"今日订单   {t['count']} 笔（{status_text}）")
print(f"今日买家   {t['buyers']} 人")
print(f"今日销售额 ¥{t['gross']:.2f}（未扣平台费）")
print(f"今日退款   ¥{t['refund']:.2f}")
print(f"今日净收入 ¥{t['net']:.2f}")
avg = t["net"] / t["count"] if t["count"] else 0
print(f"客单价     ¥{avg:.2f}")
print(f"本月累计   {m['count']} 笔 / ¥{m['net']:.2f}")
diff_count = t["count"] - y["count"]
diff_money = t["net"] - y["net"]
print(f"昨日对比   {y['count']} 笔 / ¥{y['net']:.2f}（订单{diff_count:+d}，金额{diff_money:+.2f}）")

if recent:
    print("")
    print("最近成交：")
    for r in recent:
        title = (r[4] or r[1] or "未知商品").strip()
        if len(title) > 24:
            title = title[:24] + "…"
        print(f"  {r[0][11:16]}  {title}  ¥{money(r[3]):.2f}  {STATUS_LABEL.get(r[2], r[2])}")
else:
    print("")
    print("最近成交：今日暂无成交")

print("")
print("说明：金额取自本地订单实付，未扣平台服务费；以订单库为准。")

con.close()
