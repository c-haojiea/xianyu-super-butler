import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(ROOT)
DB_PATH = os.environ.get("XY_DB_PATH") or os.path.join(PROJECT, "data", "xianyu_data.db")
PORT = int(os.environ.get("XY_DASHBOARD_PORT", "8092"))

VALID_STATUS = {"completed", "shipped", "pending_ship"}
STATUS_LABEL = {
    "completed": "已完成",
    "shipped": "已发货",
    "pending_ship": "待发货",
    "cancelled": "已取消",
    "unknown": "未知",
}
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def parse_dt(text):
    if not text or len(str(text)) != 19:
        return None
    try:
        return datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def money(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def category_of(title):
    t = title or ""
    if any(k in t for k in ("CLO3D", "服装", "打板", "汉服", "JK", "西装", "连衣裙")):
        return "服装设计"
    if any(k in t for k in ("期末", "考研", "突击", "精讲", "原理", "数据结构", "计算机网络",
                            "C语言", "Python", "离散数学", "编译", "C++", "微机")):
        return "考试冲刺"
    if any(k in t for k in ("Git", "Spine", "UE4", "UE5", "逆向", "动画", "编程")):
        return "技能提升"
    if any(k in t for k in ("资料", "VIP", "合集")):
        return "资料合集"
    return "其他"


def load_data():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        items = {}
        for row in con.execute(
            "select item_id,item_title,item_price,item_category,created_at,listing_status from item_info"
        ):
            items[str(row["item_id"])] = {
                "id": str(row["item_id"]),
                "title": row["item_title"] or "",
                "price_text": row["item_price"] or "",
                "category": category_of(row["item_title"] or ""),
                "listing_at_raw": row["created_at"] or "",
                "listing_status": row["listing_status"] or "",
            }

        orders = []
        for row in con.execute(
            "select order_id,item_id,buyer_id,chat_id,amount,refund_fee,order_status,created_at,system_shipped "
            "from orders where length(created_at)=19"
        ):
            dt = parse_dt(row["created_at"])
            if not dt:
                continue
            orders.append({
                "order_id": row["order_id"],
                "item_id": str(row["item_id"] or ""),
                "buyer_id": str(row["buyer_id"] or ""),
                "amount": money(row["amount"]),
                "refund": money(row["refund_fee"]),
                "status": row["order_status"],
                "system_shipped": int(row["system_shipped"] or 0),
                "dt": dt,
            })

        pending = [o for o in orders if o["status"] == "pending_ship" and not o["system_shipped"]]

        valid = [o for o in orders if o["status"] in VALID_STATUS and o["amount"] > 0]
        now = datetime.now()
        today = now.date()
        today_start = datetime(today.year, today.month, today.day)
        yest_start = today_start - timedelta(days=1)
        month_start = datetime(today.year, today.month, 1)
        start_365 = today_start - timedelta(days=364)
        start_30 = today_start - timedelta(days=29)

        def in_range(o, start, end=None):
            return o["dt"] >= start and (end is None or o["dt"] < end)

        today_orders = [o for o in valid if in_range(o, today_start, today_start + timedelta(days=1))]
        yest_orders = [o for o in valid if in_range(o, yest_start, today_start)]
        month_orders = [o for o in valid if in_range(o, month_start)]
        last30_orders = [o for o in valid if in_range(o, start_30)]
        year_orders = [o for o in valid if in_range(o, start_365)]

        # 日历只画「首单所在月 ~ 今天」，避免左侧大片空白
        cal_start = start_365
        if valid:
            first_dt = min(o["dt"] for o in valid)
            if first_dt > start_365:
                cal_start = datetime(first_dt.year, first_dt.month, 1)

        def rev(list_):
            return round(sum(o["amount"] for o in list_), 2)

        today_buyers = len({o["buyer_id"] for o in today_orders if o["buyer_id"]})
        total_buyers = len({o["buyer_id"] for o in valid if o["buyer_id"]})

        # 商品聚合
        stats = {}
        for o in valid:
            item_id = o["item_id"]
            st = stats.setdefault(item_id, {
                "orders": 0, "revenue": 0.0, "buyers": defaultdict(int),
                "days": set(), "first": o["dt"], "last": o["dt"],
                "orders_7d": 0, "orders_30d": 0,
            })
            st["orders"] += 1
            st["revenue"] += o["amount"]
            if o["buyer_id"]:
                st["buyers"][o["buyer_id"]] += 1
            st["days"].add(o["dt"].date())
            st["first"] = min(st["first"], o["dt"])
            st["last"] = max(st["last"], o["dt"])
            if o["dt"] >= today_start - timedelta(days=6):
                st["orders_7d"] += 1
            if o["dt"] >= start_30:
                st["orders_30d"] += 1

        total_revenue = rev(valid) or 1.0
        products = []
        for item_id, item in items.items():
            st = stats.get(item_id)
            listing_dt = parse_dt(item["listing_at_raw"])
            listing_age = (today - listing_dt.date()).days if listing_dt else None
            if st:
                buyers = st["buyers"]
                repeat_buyers = sum(1 for n in buyers.values() if n > 1)
                first_days = max((today - st["first"].date()).days, 1)
                p = {
                    "id": item_id,
                    "title": item["title"],
                    "category": item["category"],
                    "price_text": item["price_text"],
                    "listing_status": item["listing_status"],
                    "listing_age_days": listing_age,
                    "orders": st["orders"],
                    "revenue": round(st["revenue"], 2),
                    "buyers": len(buyers),
                    "repeat_buyers": repeat_buyers,
                    "active_days": len(st["days"]),
                    "first": st["first"].strftime("%Y-%m-%d"),
                    "last": st["last"].strftime("%Y-%m-%d"),
                    "avg_amount": round(st["revenue"] / st["orders"], 2),
                    "orders_7d": st["orders_7d"],
                    "orders_30d": st["orders_30d"],
                    "velocity": round(st["orders"] / first_days, 2),
                    "share": round(st["revenue"] / total_revenue * 100, 1),
                    "title_len": len(item["title"]),
                }
            else:
                p = {
                    "id": item_id,
                    "title": item["title"],
                    "category": item["category"],
                    "price_text": item["price_text"],
                    "listing_status": item["listing_status"],
                    "listing_age_days": listing_age,
                    "orders": 0, "revenue": 0.0, "buyers": 0, "repeat_buyers": 0,
                    "active_days": 0, "first": "", "last": "",
                    "avg_amount": 0.0, "orders_7d": 0, "orders_30d": 0,
                    "velocity": 0.0, "share": 0.0, "title_len": len(item["title"]),
                }
            products.append(p)

        for p in products:
            if p["orders"]:
                p["first_days"] = max((today - datetime.strptime(p["first"], "%Y-%m-%d").date()).days, 1)
            else:
                p["first_days"] = None

        top = sorted(products, key=lambda p: (p["orders"], p["revenue"]), reverse=True)[:10]
        cold_candidates = [p for p in products if p["orders"] <= 1]
        cold = sorted(cold_candidates, key=lambda p: (p["orders"], -(p["listing_age_days"] or 0)))[:6]

        # 日历
        calendar = []
        day_map = defaultdict(lambda: {"revenue": 0.0, "orders": 0})
        for o in year_orders:
            key = o["dt"].strftime("%Y-%m-%d")
            day_map[key]["revenue"] += o["amount"]
            day_map[key]["orders"] += 1
        cursor = cal_start
        while cursor.date() <= today:
            key = cursor.strftime("%Y-%m-%d")
            entry = day_map.get(key)
            calendar.append({
                "date": key,
                "revenue": round(entry["revenue"], 2) if entry else 0.0,
                "orders": entry["orders"] if entry else 0,
            })
            cursor += timedelta(days=1)

        active_calendar = [d for d in calendar if d["orders"]]
        best_day = max(active_calendar, key=lambda d: d["revenue"]) if active_calendar else None
        avg_active = round(sum(d["revenue"] for d in active_calendar) / len(active_calendar), 2) if active_calendar else 0
        max_rev = max([d["revenue"] for d in calendar] or [1]) or 1

        # 时段
        hourly_orders = [0] * 24
        hourly_rev = [0.0] * 24
        wd_orders = [0] * 7
        wd_hour = [[0] * 24 for _ in range(7)]
        for o in valid:
            h = o["dt"].hour
            wd = o["dt"].weekday()
            hourly_orders[h] += 1
            hourly_rev[h] += o["amount"]
            wd_orders[wd] += 1
            wd_hour[wd][h] += 1

        peak_hour = max(range(24), key=lambda h: hourly_orders[h])
        peak_wd = max(range(7), key=lambda w: wd_orders[w])
        evening = sum(hourly_orders[18:24])
        dawn = sum(hourly_orders[0:7])
        total_hour_orders = sum(hourly_orders) or 1
        period = [
            {"name": "凌晨 0–6", "orders": dawn, "share": round(dawn / total_hour_orders * 100, 1)},
            {"name": "上午 7–11", "orders": sum(hourly_orders[7:12]), "share": round(sum(hourly_orders[7:12]) / total_hour_orders * 100, 1)},
            {"name": "下午 12–17", "orders": sum(hourly_orders[12:18]), "share": round(sum(hourly_orders[12:18]) / total_hour_orders * 100, 1)},
            {"name": "晚间 18–23", "orders": evening, "share": round(evening / total_hour_orders * 100, 1)},
        ]

        # 近 14 天迷你走势
        spark = []
        for i in range(13, -1, -1):
            d = today - timedelta(days=i)
            key = d.strftime("%Y-%m-%d")
            e = day_map.get(key)
            spark.append({"date": key, "revenue": round(e["revenue"], 2) if e else 0.0,
                          "orders": e["orders"] if e else 0})

        summary = {
            "today_revenue": rev(today_orders),
            "today_orders": len(today_orders),
            "today_buyers": today_buyers,
            "today_aov": round(rev(today_orders) / len(today_orders), 2) if today_orders else 0,
            "yesterday_revenue": rev(yest_orders),
            "yesterday_orders": len(yest_orders),
            "month_revenue": rev(month_orders),
            "month_orders": len(month_orders),
            "last30_revenue": rev(last30_orders),
            "last30_orders": len(last30_orders),
            "pending_count": len(pending),
            "pending_value": rev(pending),
            "total_revenue": rev(valid),
            "total_orders": len(valid),
            "total_buyers": total_buyers,
            "repeat_rate": round((1 - total_buyers / len(valid)) * 100, 1) if valid else 0,
            "days_active": len({o["dt"].date() for o in valid}),
            "avg_active_day": avg_active,
            "best_day": best_day,
            "spark": spark,
        }

        # 订单流水（用于日历点击与最近成交）
        order_rows = []
        for o in sorted(valid, key=lambda x: x["dt"], reverse=True):
            item = items.get(o["item_id"])
            order_rows.append({
                "date": o["dt"].strftime("%Y-%m-%d"),
                "time": o["dt"].strftime("%H:%M"),
                "item_id": o["item_id"],
                "title": item["title"] if item else "未识别商品",
                "amount": round(o["amount"], 2),
                "status": STATUS_LABEL.get(o["status"], o["status"]),
            })

        # 归因
        hot_cards = []
        for idx, p in enumerate([x for x in top if x["orders"] >= 3][:3]):
            reasons = []
            reasons.append(f"累计 {p['orders']} 单、¥{p['revenue']:.2f}，占全店成交额 {p['share']}%")
            if p["repeat_buyers"]:
                reasons.append(f"{p['repeat_buyers']} 位买家复购，占买家数 {round(p['repeat_buyers'] / p['buyers'] * 100)}%")
            else:
                reasons.append("买家全部为一次性，靠持续拉新而非复购")
            if p["avg_amount"] <= 1.1:
                reasons.append(f"均价 ¥{p['avg_amount']:.2f}，在 ¥1 心理门槛内，决策成本低")
            if p["active_days"] >= 7 and p["velocity"] >= 0.5:
                reasons.append(f"在 {p['active_days']} 个不同日期出单，日均 {p['velocity']} 单，属于稳定常青款")
            elif p["active_days"] >= 7:
                reasons.append(f"在 {p['active_days']} 个不同日期出单，需求持续存在")
            if p["orders_7d"] >= 2:
                reasons.append(f"最近 7 天仍有 {p['orders_7d']} 单，热度未衰减")
            elif p["last"]:
                reasons.append(f"最近一单 {p['last']}，仍保持活跃")
            title = p["title"]
            if any(k in title for k in ("全流程", "完整", "合集", "全套", "课时")):
                reasons.append("标题直接给出完整交付范围（课时 / 合集 / 全流程），降低买家的判断成本")
            elif p["category"] == "技能提升":
                reasons.append("技能类需求不受考试周期影响，属于全年常青方向")
            elif p["category"] == "考试冲刺":
                reasons.append("期末 / 考研刚需，考试季流量集中")
            reasons = reasons[:5]
            hot_cards.append({
                "rank": idx + 1, "id": p["id"], "title": p["title"],
                "orders": p["orders"], "revenue": p["revenue"], "buyers": p["buyers"],
                "repeat": p["repeat_buyers"], "velocity": p["velocity"], "share": p["share"],
                "category": p["category"], "reasons": reasons,
            })

        cold_cards = []
        for idx, p in enumerate(cold):
            reasons = []
            age = p["listing_age_days"]
            if p["orders"] == 0:
                if age is not None and age <= 3:
                    reasons.append(f"上架仅 {age} 天，还处在冷启动期，尚未积累曝光和搜索权重")
                elif age is not None:
                    reasons.append(f"上架 {age} 天仍为 0 单，需要检查曝光、价格与标题匹配")
                else:
                    reasons.append("本地暂无上架时间记录，且没有成交")
            else:
                reasons.append(f"自首单以来 {p['first_days']} 天仅 {p['orders']} 单，需求明显弱于头部商品")
            if p["avg_amount"] >= 2:
                reasons.append(f"均价 ¥{p['avg_amount']:.2f}，明显高于店内 ¥1 主流价格带，决策门槛更高")
            if p["title_len"] > 30:
                reasons.append(f"标题 {p['title_len']} 字偏长，移动端信息流容易被截断")
            same_cat = sum(1 for x in products if x["category"] == p["category"]) 
            if same_cat >= 3:
                reasons.append(f"同方向在售 {same_cat} 个商品，流量在店铺内部被分流")
            if p["category"] == "服装设计":
                reasons.append("服装三维设计属于专业窄众需求，目标人群规模本身较小")
            if p["listing_status"] and p["listing_status"] != "on_sale":
                reasons.append(f"当前商品状态为 {p['listing_status']}，可能未正常在售")
            reasons = reasons[:4]
            cold_cards.append({
                "rank": idx + 1, "id": p["id"], "title": p["title"], "orders": p["orders"],
                "revenue": p["revenue"], "listing_age_days": age, "category": p["category"],
                "badge": "新上架" if (p["orders"] == 0 and age is not None and age <= 3) else "冷门",
                "reasons": reasons,
            })

        time_insights = [
            f"{peak_hour:02d}:00–{peak_hour:02d}:59 是下单峰值，共 {hourly_orders[peak_hour]} 单",
            f"{WEEKDAY_CN[peak_wd]}是一周中成交最多的一天，共 {wd_orders[peak_wd]} 单",
            f"晚间 18–23 点贡献 {period[3]['share']}% 的订单，是全天主战场",
            f"凌晨 0–6 点仅 {period[0]['orders']} 单（{period[0]['share']}%），不建议在这个时段集中上新或回复",
        ]

        overall = [
            f"{cal_start.strftime('%Y-%m-%d')} 起有 {len(active_calendar)} 天出单，活跃日平均 ¥{avg_active:.2f}",
        ]
        if best_day:
            overall.append(f"最高单日 ¥{best_day['revenue']:.2f}（{best_day['date']}，{best_day['orders']} 单）")
        overall.append(f"全店复购率 {summary['repeat_rate']}%，{summary['total_buyers']} 位买家贡献 {len(valid)} 单")

        categories = []
        cat_map = defaultdict(lambda: {"orders": 0, "revenue": 0.0})
        for p in products:
            cat_map[p["category"]]["orders"] += p["orders"]
            cat_map[p["category"]]["revenue"] += p["revenue"]
        for name, v in sorted(cat_map.items(), key=lambda x: -x[1]["orders"]):
            if v["orders"]:
                categories.append({"name": name, "orders": v["orders"], "revenue": round(v["revenue"], 2)})
        if categories:
            lead = categories[0]
            share = round(lead["orders"] / (sum(c["orders"] for c in categories) or 1) * 100, 1)
            overall.append(f"{lead['name']}是当前主力品类，贡献 {lead['orders']} 单（{share}%）、¥{lead['revenue']:.2f}")

        return {
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "summary": summary,
            "calendar": {
                "start": cal_start.strftime("%Y-%m-%d"),
                "end": today.strftime("%Y-%m-%d"),
                "range": [cal_start.strftime("%Y-%m"), today.strftime("%Y-%m")],
                "max": round(max_rev, 2),
                "days": calendar,
                "best": best_day,
                "active_days": len(active_calendar),
            },
            "hourly": {
                "orders": hourly_orders,
                "revenue": [round(x, 2) for x in hourly_rev],
                "weekday_orders": wd_orders,
                "weekday_hour": wd_hour,
                "peak_hour": peak_hour,
                "peak_weekday": peak_wd,
                "period": period,
            },
            "products": {"top": top, "all": products, "cold": cold},
            "insights": {"hot": hot_cards, "cold": cold_cards, "time": time_insights, "overall": overall},
            "categories": categories,
            "orders": order_rows,
            "recent": order_rows[:12],
        }
    finally:
        con.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", cache="no-store"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def _file(self, name, ctype, cache="public, max-age=300"):
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, ctype, cache)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send(200, json.dumps({"ok": True, "ts": datetime.now().isoformat()}, ensure_ascii=False))
            return
        if path == "/api/dashboard":
            try:
                payload = load_data()
                self._send(200, json.dumps(payload, ensure_ascii=False))
            except Exception as exc:
                self._send(500, json.dumps({"error": str(exc)}, ensure_ascii=False))
            return
        if path in ("/", "/index.html"):
            self._file("index.html", "text/html; charset=utf-8", "no-cache")
        elif path == "/styles.css":
            self._file("styles.css", "text/css; charset=utf-8", "no-cache")
        elif path == "/app.js":
            self._file("app.js", "application/javascript; charset=utf-8", "no-cache")
        elif path == "/assets/echarts.min.js":
            self._file("assets/echarts.min.js", "application/javascript; charset=utf-8", "public, max-age=86400")
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        PORT = int(sys.argv[1])
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"dashboard running: http://localhost:{PORT}  db={DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
