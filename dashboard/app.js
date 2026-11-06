const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const COLORS = {
  ink: "#17130f",
  ink2: "#3b342b",
  muted: "#7d7365",
  line: "rgba(23,19,15,0.14)",
  lineStrong: "rgba(23,19,15,0.3)",
  accent: "#c4462b",
  jade: "#2f6a5a",
  gold: "#b2862f",
  paper: "#f2ecdf",
  paper2: "#faf6ec",
};

const MONO = '"IBM Plex Mono", "JetBrains Mono", Consolas, monospace';
const BODY = '"Noto Sans SC", "Microsoft YaHei", sans-serif';
const DISPLAY = '"Source Han Serif SC", "Noto Serif SC", "Songti SC", serif';

const state = {
  data: null,
  loaded: false,
  sortKey: "orders",
  sortDir: "desc",
  selectedDate: null,
  drawerProduct: null,
  charts: {},
};

const fmtMoney = (v) =>
  "¥" + Number(v || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtInt = (v) => Number(v || 0).toLocaleString("zh-CN");
const fmtPct = (v) => Number(v || 0).toFixed(1) + "%";

function escapeHtml(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function animateNumber(el, target, decimals = 0, prefix = "", suffix = "") {
  const start = 0;
  const duration = 620;
  const t0 = performance.now();
  const step = (t) => {
    const p = Math.min(1, (t - t0) / duration);
    const eased = 1 - Math.pow(1 - p, 3);
    const val = start + (target - start) * eased;
    el.textContent = prefix + val.toLocaleString("zh-CN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }) + suffix;
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function sparkSvg(values, color) {
  if (!values || !values.length) return "";
  const w = 74, h = 26, pad = 2;
  const max = Math.max(...values, 1);
  const step = (w - pad * 2) / Math.max(values.length - 1, 1);
  const pts = values.map((v, i) => [pad + i * step, h - pad - (v / max) * (h - pad * 2)]);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  return `<svg class="kpi-spark" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <path d="${path}" fill="none" stroke="${color}" stroke-width="1.4" opacity="0.9"/>
    <circle cx="${pts[pts.length - 1][0]}" cy="${pts[pts.length - 1][1]}" r="1.8" fill="${color}"/>
  </svg>`;
}

function deltaText(current, previous, isMoney) {
  if (!previous && !current) return "昨日无成交";
  if (!previous) return "昨日为 0";
  const pct = ((current - previous) / previous) * 100;
  const cls = pct >= 0 ? "up" : "down";
  const arrow = pct >= 0 ? "▲" : "▼";
  const text = isMoney
    ? `${arrow} ${Math.abs(pct).toFixed(0)}% · 昨日 ${fmtMoney(previous)}`
    : `${arrow} ${Math.abs(pct).toFixed(0)}% · 昨日 ${fmtInt(previous)} 单`;
  return `<span class="kpi-delta ${cls}">${text}</span>`;
}

function renderHeader(data) {
  const dt = new Date(data.generated_at.replace(" ", "T"));
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  $("#dateNum").textContent = `${mm}.${dd}`;
  const wd = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][dt.getDay()];
  $("#dateMeta").textContent = `${wd} · ${dt.getFullYear()}`;
  $("#updatedAt").textContent = "更新于 " + data.generated_at.slice(11, 19);
  $("#liveDot").classList.toggle("offline", false);

  const best = data.calendar.best;
  $("#tickerNote").textContent = best
    ? `峰值 ${String(data.hourly.peak_hour).padStart(2, "0")}:00 · 最高单日 ${fmtMoney(best.revenue)}（${best.date}）`
    : "暂无成交数据";
  $("#footerNote").textContent = `生成于 ${data.generated_at} · ${data.calendar.start} 起活跃 ${data.calendar.active_days} 天`;
}

function renderKpis(data) {
  const s = data.summary;
  const cards = [
    {
      label: "TODAY / 今日成交额",
      value: s.today_revenue,
      money: true,
      foot: deltaText(s.today_revenue, s.yesterday_revenue, true),
      spark: data.summary.spark.map((x) => x.revenue),
      primary: true,
    },
    {
      label: "TODAY ORDERS / 今日订单",
      value: s.today_orders,
      foot: deltaText(s.today_orders, s.yesterday_orders, false),
      spark: data.summary.spark.map((x) => x.orders),
    },
    {
      label: "BUYERS / 今日买家",
      value: s.today_buyers,
      foot: `全店累计 ${fmtInt(s.total_buyers)} 位买家`,
      spark: data.summary.spark.map((x) => x.orders),
    },
    {
      label: "AOV / 今日客单价",
      value: s.today_aov,
      money: true,
      foot: `本月 ${fmtInt(s.month_orders)} 单 · ${fmtMoney(s.month_revenue)}`,
    },
    {
      label: "MONTH / 本月成交额",
      value: s.month_revenue,
      money: true,
      foot: `近 30 天 ${fmtMoney(s.last30_revenue)}`,
      spark: data.summary.spark.map((x) => x.revenue),
    },
    {
      label: "PENDING / 待发货",
      value: s.pending_count,
      foot: s.pending_count ? `待发货金额 ${fmtMoney(s.pending_value)}` : "全部订单已处理",
      warn: s.pending_count > 0,
    },
  ];

  $("#kpis").innerHTML = cards.map((c, i) => `
    <article class="kpi ${c.primary ? "kpi-primary" : ""}" style="--i:${i}">
      <div class="kpi-label">${escapeHtml(c.label)}</div>
      <div class="kpi-value" data-money="${c.money ? 1 : 0}" data-value="${c.value}">
        ${c.money ? fmtMoney(c.value) : fmtInt(c.value)}
      </div>
      <div class="kpi-foot">${c.foot || ""}</div>
      ${c.spark ? sparkSvg(c.spark, c.primary ? "#e5a48e" : COLORS.accent) : ""}
    </article>
  `).join("");

  if (!state.loaded) {
    $$("#kpis .kpi-value").forEach((el) => {
      const target = Number(el.dataset.value || 0);
      const isMoney = el.dataset.money === "1";
      animateNumber(el, target, isMoney ? 2 : 0, isMoney ? "¥" : "");
    });
  } else {
    $$("#kpis .kpi-value").forEach((el) => {
      const target = Number(el.dataset.value || 0);
      const isMoney = el.dataset.money === "1";
      el.textContent = (isMoney ? "¥" : "") + target.toLocaleString("zh-CN", {
        minimumFractionDigits: isMoney ? 2 : 0,
        maximumFractionDigits: isMoney ? 2 : 0,
      });
    });
  }
}

function tooltipBase() {
  return {
    backgroundColor: COLORS.paper2,
    borderColor: COLORS.lineStrong,
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color: COLORS.ink, fontFamily: BODY, fontSize: 12 },
    extraCssText: "box-shadow:none;border-radius:2px;",
  };
}

function renderCalendar(data) {
  const chart = state.charts.calendar || echarts.init($("#calendarChart"));
  state.charts.calendar = chart;

  // 以周为列、星期为行，避免 12 个月日历被压成细条
  const days = data.calendar.days;
  const firstDate = new Date(days[0].date + "T00:00:00");
  const mondayOffset = (firstDate.getDay() + 6) % 7;
  const weekStart = new Date(firstDate);
  weekStart.setDate(firstDate.getDate() - mondayOffset);
  const dayMs = 86400000;
  const weekIndexOf = (dt) => Math.floor((dt - weekStart) / (7 * dayMs));
  const weekdayOf = (dt) => (dt.getDay() + 6) % 7;
  const values = days.map((d) => {
    const dt = new Date(d.date + "T00:00:00");
    return {
      value: [weekIndexOf(dt), weekdayOf(dt), d.revenue],
      date: d.date,
      revenue: d.revenue,
      orders: d.orders,
    };
  });
  const weekCount = weekIndexOf(new Date(days[days.length - 1].date + "T00:00:00")) + 1;
  const weekLabels = new Array(weekCount).fill("");
  for (let i = 0; i < weekCount; i++) {
    const ws = new Date(weekStart.getTime() + i * 7 * dayMs);
    if (i === 0) weekLabels[i] = `${firstDate.getMonth() + 1}月`;
    else {
      const prev = new Date(weekStart.getTime() + (i - 1) * 7 * dayMs);
      if (ws.getMonth() !== prev.getMonth()) weekLabels[i] = `${ws.getMonth() + 1}月`;
    }
  }
  // 相邻重复的月份只保留第一个，避免首周与次周都标「8月」
  let lastMonthLabel = "";
  weekLabels.forEach((v, i) => {
    if (!v) return;
    if (v === lastMonthLabel) weekLabels[i] = "";
    else lastMonthLabel = v;
  });

  const max = data.calendar.max || 1;
  chart.setOption({
    backgroundColor: "transparent",
    grid: { left: 42, right: 18, top: 34, bottom: 38, containLabel: false },
    tooltip: Object.assign({}, tooltipBase(), {
      trigger: "item",
      formatter: (p) => {
        if (!p.data) return "";
        return `<div style="font-family:${MONO};font-size:11px;color:${COLORS.muted}">${p.data.date}</div>
          <div style="margin-top:2px"><b>${p.data.orders ? fmtMoney(p.data.revenue) : "无成交"}</b>
          ${p.data.orders ? ` · ${p.data.orders} 单` : ""}</div>`;
      },
    }),
    xAxis: {
      type: "category",
      data: Array.from({ length: weekCount }, (_, i) => i),
      position: "top",
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: {
        interval: 0,
        color: COLORS.ink2,
        fontFamily: DISPLAY,
        fontSize: 10,
        formatter: (v) => weekLabels[v] || "",
      },
    },
    yAxis: {
      type: "category",
      data: ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
      inverse: true,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { color: COLORS.muted, fontFamily: MONO, fontSize: 9, margin: 8 },
    },
    visualMap: {
      min: 0,
      max,
      show: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 120,
      itemHeight: 9,
      text: ["高", "低"],
      textStyle: { color: COLORS.muted, fontFamily: MONO, fontSize: 9 },
      inRange: { color: ["#eee6d6", "#e7c7b1", "#d99773", "#c4462b", "#7e2416"] },
      calculable: false,
    },
    series: [{
      type: "heatmap",
      data: values,
      itemStyle: {
        borderWidth: 1,
        borderColor: COLORS.paper2,
        borderRadius: 1,
      },
      emphasis: { itemStyle: { borderColor: COLORS.ink, borderWidth: 1 } },
    }],
  }, true);

  if (!chart.__bound) {
    chart.on("click", (params) => {
      if (params.data && params.data.date) showDay(params.data.date);
    });
    chart.__bound = true;
  }

  $("#calendarMeta").textContent = data.calendar.best
    ? `最高单日 ${fmtMoney(data.calendar.best.revenue)} · 活跃 ${data.calendar.active_days} 天`
    : "暂无成交";
  const calMax = $("#calMax");
  if (calMax) calMax.textContent = `最高 ${fmtMoney(max)}`;
}

function showDay(date) {
  state.selectedDate = date;
  const rows = state.data.orders.filter((o) => o.date === date);
  const revenue = rows.reduce((s, o) => s + o.amount, 0);
  const box = $("#dayDetail");
  box.hidden = false;

  if (!rows.length) {
    box.innerHTML = `<div class="day-detail-head">
      <h3>${date} · 无成交</h3>
      <span class="day-sum">这一天没有订单</span>
    </div>`;
    return;
  }
  const shown = rows.slice(0, 12);
  box.innerHTML = `
    <div class="day-detail-head">
      <h3>${date} · ${rows.length} 单</h3>
      <span class="day-sum">当日成交 ${fmtMoney(revenue)}</span>
    </div>
    <div class="day-orders">
      ${shown.map((o) => `<div class="day-order">
        <span class="t">${o.time}</span>
        <span class="n" title="${escapeHtml(o.title)}">${escapeHtml(o.title)}</span>
        <span class="a">${fmtMoney(o.amount)}</span>
      </div>`).join("")}
    </div>
    ${rows.length > shown.length ? `<div class="day-sum" style="margin-top:8px">另有 ${rows.length - shown.length} 单未展开</div>` : ""}
  `;
}

function renderProducts(data) {
  const top = data.products.top;
  const chart = state.charts.products || echarts.init($("#productChart"));
  state.charts.products = chart;

  const ordered = [...top].reverse();
  chart.setOption({
    backgroundColor: "transparent",
    grid: { left: 4, right: 56, top: 6, bottom: 4, containLabel: true },
    tooltip: Object.assign({}, tooltipBase(), {
      formatter: (p) => {
        const item = ordered[p.dataIndex];
        return `<div style="font-family:${DISPLAY};font-size:13px;max-width:300px;white-space:normal">${escapeHtml(item.title)}</div>
          <div style="margin-top:4px;font-family:${MONO};font-size:11px;color:${COLORS.muted}">
          ${item.orders} 单 · ${fmtMoney(item.revenue)} · ${item.buyers} 位买家 · ${item.repeat_buyers} 位复购</div>`;
      },
    }),
    xAxis: {
      type: "value",
      splitLine: { lineStyle: { color: COLORS.line } },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: COLORS.muted, fontFamily: MONO, fontSize: 9 },
    },
    yAxis: {
      type: "category",
      data: ordered.map((p) => p.title),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: COLORS.ink2,
        fontFamily: BODY,
        fontSize: 10,
        formatter: (v) => (v.length > 14 ? v.slice(0, 14) + "…" : v),
      },
    },
    series: [{
      type: "bar",
      data: ordered.map((p) => p.orders),
      barWidth: 14,
      itemStyle: {
        color: (p) => (p.dataIndex === ordered.length - 1 ? COLORS.accent : "rgba(59,52,43,0.72)"),
        borderRadius: [0, 2, 2, 0],
      },
      label: {
        show: true,
        position: "right",
        color: COLORS.muted,
        fontFamily: MONO,
        fontSize: 10,
        formatter: (p) => `${p.value} 单`,
      },
    }],
  }, true);

  if (!chart.__bound) {
    chart.on("click", (params) => {
      const item = ordered[params.dataIndex];
      if (item) openProduct(item.id);
    });
    chart.__bound = true;
  }

  $("#itemCount").textContent = data.products.all.filter((p) => p.orders > 0).length;
  renderProductTable();
}

function renderProductTable() {
  const data = state.data;
  if (!data) return;
  const rows = [...data.products.all];
  const key = state.sortKey;
  const dir = state.sortDir === "desc" ? -1 : 1;
  rows.sort((a, b) => {
    const av = a[key], bv = b[key];
    if (typeof av === "string") return av.localeCompare(bv) * dir;
    return (av - bv) * dir;
  });

  $("#productBody").innerHTML = rows.map((p, i) => {
    const rank = i + 1;
    return `<tr data-id="${p.id}" class="${rank === 1 ? "top1" : ""}">
      <td class="col-rank">${String(rank).padStart(2, "0")}</td>
      <td class="item-cell">
        <span class="item-title" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</span>
        <span class="item-cat">${escapeHtml(p.category)} · ${p.listing_status === "on_sale" ? "在售" : escapeHtml(p.listing_status || "未知状态")}</span>
      </td>
      <td class="col-num num">${p.orders}</td>
      <td class="col-num num money">${fmtMoney(p.revenue)}</td>
      <td class="col-num num">${p.buyers}</td>
      <td class="col-num num">${p.repeat_buyers}</td>
      <td class="col-num num">${p.active_days}</td>
    </tr>`;
  }).join("");

  $$("#productBody tr").forEach((tr) => {
    tr.addEventListener("click", () => openProduct(tr.dataset.id));
  });

  $$("#productTable th[data-sort]").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.sort === key);
    th.textContent = th.textContent.replace(/ [↑↓]$/, "");
    if (th.dataset.sort === key) th.textContent += state.sortDir === "desc" ? " ↓" : " ↑";
  });
}

function renderInsights(data) {
  const hot = data.insights.hot || [];
  const cold = data.insights.cold || [];
  $("#hotCount").textContent = `${hot.length} 个`;
  $("#coldCount").textContent = `${cold.length} 个`;

  $("#hotList").innerHTML = hot.map((h) => `
    <article class="insight-card" data-id="${h.id}">
      <div class="ic-head">
        <span class="ic-rank">爆款 0${h.rank}</span>
        <span class="ic-metric">${h.orders} 单 · ${fmtMoney(h.revenue)}</span>
      </div>
      <h3 class="ic-title">${escapeHtml(h.title)}</h3>
      <ul class="ic-reasons">${h.reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
    </article>
  `).join("") || `<div class="kpi-foot">暂无足够成交样本</div>`;

  $("#coldList").innerHTML = cold.map((c) => `
    <article class="insight-card" data-id="${c.id}">
      <div class="ic-head">
        <span class="ic-rank">${escapeHtml(c.badge)} 0${c.rank}</span>
        <span class="ic-metric">${c.orders} 单 · 上架 ${c.listing_age_days == null ? "?" : c.listing_age_days} 天</span>
      </div>
      <h3 class="ic-title">${escapeHtml(c.title)}</h3>
      <ul class="ic-reasons">${c.reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
    </article>
  `).join("") || `<div class="kpi-foot">没有明显冷门商品</div>`;

  $$(".insight-card").forEach((el) => {
    el.addEventListener("click", () => openProduct(el.dataset.id));
  });

  $("#storeNotes").innerHTML = (data.insights.overall || [])
    .map((t) => `<li>${escapeHtml(t)}</li>`).join("");
}

function renderTime(data) {
  const chart = state.charts.hour || echarts.init($("#hourChart"));
  state.charts.hour = chart;
  const h = data.hourly;
  const hours = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0") + ":00");
  const weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  const series = [];
  let max = 1;
  for (let w = 0; w < 7; w++) {
    for (let hour = 0; hour < 24; hour++) {
      const v = h.weekday_hour[w][hour];
      if (v > max) max = v;
      series.push([hour, w, v]);
    }
  }

  chart.setOption({
    backgroundColor: "transparent",
    grid: { left: 8, right: 12, top: 8, bottom: 48, containLabel: true },
    tooltip: Object.assign({}, tooltipBase(), {
      formatter: (p) => `${weekdays[p.value[1]]} ${hours[p.value[0]]}<br/><b>${p.value[2]} 单</b>`,
    }),
    xAxis: {
      type: "category",
      data: hours,
      splitArea: { show: true },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: COLORS.muted, fontFamily: MONO, fontSize: 9, interval: 1 },
    },
    yAxis: {
      type: "category",
      data: weekdays,
      inverse: true,
      splitArea: { show: true },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: COLORS.ink2, fontFamily: BODY, fontSize: 10 },
    },
    visualMap: {
      min: 0,
      max,
      show: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 110,
      itemHeight: 9,
      text: ["高", "低"],
      textStyle: { color: COLORS.muted, fontFamily: MONO, fontSize: 9 },
      inRange: { color: ["#eee7d9", "#b7d2c7", "#4f8e7b", COLORS.jade, "#173d33"] },
      calculable: false,
    },
    series: [{
      type: "heatmap",
      data: series,
      label: { show: false },
      itemStyle: { borderRadius: 1 },
      emphasis: { itemStyle: { borderColor: COLORS.ink, borderWidth: 1 } },
    }],
  }, true);

  $("#timeMeta").textContent = `峰值 ${String(h.peak_hour).padStart(2, "0")}:00 · ${weekdays[h.peak_weekday]}`;
  $("#timeStrip").innerHTML = h.period.map((p) => `
    <div class="time-chip">
      <div class="name">${escapeHtml(p.name)}</div>
      <div class="val">${p.orders} <small>单 · ${fmtPct(p.share)}</small></div>
    </div>
  `).join("");
  $("#timeNotes").innerHTML = data.insights.time.map((t) => `<div>${escapeHtml(t)}</div>`).join("");
}

function renderRecent(data) {
  $("#recentMeta").textContent = `累计 ${fmtInt(data.summary.total_orders)} 单`;
  $("#recentList").innerHTML = data.recent.map((o) => `
    <div class="recent-row">
      <span class="recent-time">${o.time}</span>
      <span class="recent-title" title="${escapeHtml(o.title)}">${escapeHtml(o.title)}</span>
      <span class="recent-amount">${fmtMoney(o.amount)}<span class="recent-status">${escapeHtml(o.status)}</span></span>
    </div>
  `).join("") || `<div class="kpi-foot">暂无成交</div>`;
}

function openProduct(id) {
  const p = state.data.products.all.find((x) => x.id === id);
  if (!p) return;
  state.drawerProduct = id;
  $("#drawerBadge").textContent = p.orders >= 3 ? "爆款诊断" : p.orders === 0 && (p.listing_age_days || 0) <= 3 ? "新上架诊断" : "商品诊断";
  $("#drawerBody").innerHTML = renderDrawerContent(p);

  $("#drawer").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#scrim").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeDrawer() {
  state.drawerProduct = null;
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#scrim").hidden = true;
  document.body.style.overflow = "";
}

function drawerReasons(p) {
  const reasons = [];
  if (p.orders === 0) {
    if (p.listing_age_days != null && p.listing_age_days <= 3) {
      reasons.push(`上架仅 ${p.listing_age_days} 天，仍处于冷启动期，尚未积累曝光和搜索权重。`);
    } else {
      reasons.push(`上架 ${p.listing_age_days == null ? "未知" : p.listing_age_days} 天仍为 0 单，需要检查曝光量、价格与标题匹配度。`);
    }
  } else {
    reasons.push(`累计 ${p.orders} 单、${fmtMoney(p.revenue)}，占全店成交额 ${p.share}%。`);
    if (p.repeat_buyers) reasons.push(`有 ${p.repeat_buyers} 位买家复购，买家复购率 ${fmtPct((p.repeat_buyers / p.buyers) * 100)}。`);
    else reasons.push("买家均为一次性购买，增长主要依赖持续拉新。");
    if (p.avg_amount <= 1.1) reasons.push(`均价 ${fmtMoney(p.avg_amount)}，处在低决策门槛价格带。`);
    if (p.active_days >= 7) reasons.push(`在 ${p.active_days} 个不同日期出单，日均 ${p.velocity} 单。`);
    if (p.orders_7d) reasons.push(`最近 7 天 ${p.orders_7d} 单，近期热度仍在。`);
    if (p.last) reasons.push(`最近一单发生在 ${p.last}。`);
  }
  if (p.avg_amount >= 2) reasons.push(`价格 ${fmtMoney(p.avg_amount)} 高于店内 ¥1 主流带，转化门槛更高。`);
  if (p.title_len > 30) reasons.push(`标题 ${p.title_len} 字偏长，移动端信息流可能被截断。`);
  if (p.listing_status && p.listing_status !== "on_sale") reasons.push(`当前状态：${p.listing_status}，可能未正常在售。`);
  return reasons;
}

function renderDrawerContent(p) {
  const orders = state.data.orders.filter((o) => o.item_id === p.id).slice(0, 8);
  const metrics = [
    ["订单数", p.orders],
    ["成交额", fmtMoney(p.revenue)],
    ["买家数", p.buyers],
    ["复购买家", p.repeat_buyers],
    ["活跃天数", p.active_days],
    ["占全店", fmtPct(p.share)],
  ];
  return `<h2 class="drawer-title">${escapeHtml(p.title)}</h2>
    <div class="drawer-sub">${escapeHtml(p.category)} · ${p.listing_status === "on_sale" ? "在售" : escapeHtml(p.listing_status || "未知")} · 上架 ${p.listing_age_days == null ? "?" : p.listing_age_days} 天</div>
    <div class="drawer-metrics">
      ${metrics.map(([l, v]) => `<div class="drawer-metric"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("")}
    </div>
    <div class="drawer-section-title">诊断结论</div>
    <ul class="drawer-reasons">${drawerReasons(p).map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
    <div class="drawer-section-title">最近订单</div>
    <div class="drawer-orders">
      ${orders.length ? orders.map((o) => `<div class="drawer-order">
        <span class="t">${o.date.slice(5)} ${o.time}</span>
        <span>${escapeHtml(o.status)}</span>
        <span class="a">${fmtMoney(o.amount)}</span>
      </div>`).join("") : `<div class="kpi-foot">暂无成交记录</div>`}
    </div>`;
}

function renderAll(data) {
  renderHeader(data);
  renderKpis(data);
  renderCalendar(data);
  renderProducts(data);
  renderInsights(data);
  renderTime(data);
  renderRecent(data);
  if (state.selectedDate) showDay(state.selectedDate);
  if (state.drawerProduct) {
    const p = data.products.all.find((x) => x.id === state.drawerProduct);
    if (p) $("#drawerBody").innerHTML = renderDrawerContent(p);
  }
}

async function loadData() {
  const btn = $("#refreshBtn");
  btn.classList.add("spinning");
  try {
    const res = await fetch("/api/dashboard", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    state.data = data;
    renderAll(data);
    if (!state.loaded) state.loaded = true;
    $("#errorBanner").hidden = true;
    $("#liveDot").classList.remove("offline");
  } catch (err) {
    $("#errorBanner").hidden = false;
    $("#errorText").textContent = err.message || String(err);
    $("#liveDot").classList.add("offline");
    $("#updatedAt").textContent = "连接失败";
  } finally {
    setTimeout(() => btn.classList.remove("spinning"), 400);
  }
}

function bind() {
  $("#refreshBtn").addEventListener("click", loadData);
  $("#drawerClose").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
  });

  $$("#productTable th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
      else {
        state.sortKey = key;
        state.sortDir = "desc";
      }
      renderProductTable();
    });
  });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      Object.values(state.charts).forEach((c) => c && c.resize());
    }, 120);
  });

  setInterval(loadData, 20000);
}

bind();
loadData();

// 供自动化测试与调试使用
window.__dashboard = { state, showDay, openProduct, closeDrawer, loadData };
