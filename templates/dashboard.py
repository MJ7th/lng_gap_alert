<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LNG 수급 공백 예측</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #f5f4f0; --panel: #ffffff; --ink: #1d1f22; --muted: #6b6f76; --line: #e2e0da;
    --actual: #1d1f22; --pred: #c2410c; --plan: #8a8f98; --a: #b42318; --b: #0f6e56;
    --warn-bg: #fff4e5; --warn-ink: #8a4b00; --accent: #0f6e56;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #141518; --panel: #1d1f23; --ink: #ecebe7; --muted: #9a9ea6; --line: #2e3036;
      --actual: #ecebe7; --pred: #f08a4b; --plan: #7d828b; --a: #f2766b; --b: #4cc3a0;
      --warn-bg: #3a2a12; --warn-ink: #ffc87a; --accent: #4cc3a0;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font-family: "IBM Plex Sans KR", system-ui, sans-serif; line-height: 1.5; }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 28px 16px 64px; }
  header h1 { font-size: 1.5rem; margin: 0 0 4px; font-weight: 600; letter-spacing: -0.01em; }
  header p { margin: 0; color: var(--muted); font-size: .92rem; }
  .banner { background: var(--warn-bg); color: var(--warn-ink); border-radius: 8px;
            padding: 10px 14px; margin: 18px 0 0; font-size: .9rem; font-weight: 500; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 22px 0; }
  .kpi { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
  .kpi .label { color: var(--muted); font-size: .8rem; }
  .kpi .value { font-family: "IBM Plex Mono", monospace; font-size: 1.45rem; margin-top: 2px; }
  .kpi .sub { color: var(--muted); font-size: .76rem; margin-top: 2px; }
  .kpi.good .value { color: var(--accent); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 520px), 1fr)); gap: 14px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px; min-width: 0; }
  .card h2 { font-size: 1rem; margin: 0 0 2px; font-weight: 600; }
  .card .desc { color: var(--muted); font-size: .82rem; margin: 0 0 10px; }
  .chart { position: relative; height: 260px; }
  table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  th, td { text-align: right; padding: 7px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  th { color: var(--muted); font-weight: 500; }
  .num { font-family: "IBM Plex Mono", monospace; }
  .pos { color: var(--b); } .neg { color: var(--a); }
  .scroll { overflow-x: auto; }
  .tag { display: inline-block; padding: 1px 8px; border-radius: 99px; font-size: .75rem; border: 1px solid var(--line); }
  .tag.hit { color: var(--b); border-color: var(--b); }
  details { margin-top: 14px; color: var(--muted); font-size: .85rem; }
  details code { font-family: "IBM Plex Mono", monospace; }
  .err { background: var(--panel); border: 1px solid var(--line); padding: 24px; border-radius: 10px; margin-top: 24px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>LNG 수급 공백 예측</h1>
    <p>동절기 총수요와 직수입 변동을 함께 예측해, 가스공사가 떠안을 물량을 한 달 먼저 계산합니다.</p>
  </header>

  {% if data.error %}
    <div class="err">{{ data.error }}</div>
  {% else %}
  {% if data.sample %}
    <div class="banner">⚠ 가짜 샘플 데이터로 만든 결과입니다. 실제 수치가 아니므로 자소서·면접에 인용하지 마세요.</div>
  {% endif %}

  <section class="kpis" id="kpis"></section>

  <div class="grid">
    <div class="card">
      <h2>① 총수요: 실제 vs 예측</h2>
      <p class="desc" id="demand-desc"></p>
      <div class="chart"><canvas id="c-demand"></canvas></div>
    </div>
    <div class="card">
      <h2>② 직수입: 실제 vs 예측</h2>
      <p class="desc">가격차(JKM − 수입단가)가 벌어지면 직수입사가 빠집니다. 회색은 전년 동월값(계획 가정).</p>
      <div class="chart"><canvas id="c-direct"></canvas></div>
    </div>
    <div class="card">
      <h2>③ 가스공사 부담물량</h2>
      <p class="desc">계획(연초, 평년 기온·평상시 가격) · 예측(전월 시점) · 실제. 실제가 계획을 넘는 만큼이 공백입니다.</p>
      <div class="chart"><canvas id="c-burden"></canvas></div>
    </div>
    <div class="card">
      <h2>④ 재고와 경보</h2>
      <p class="desc">점선은 안전재고. 점은 조기경보가 발령된 달(1개월 전 발령)입니다.</p>
      <div class="chart"><canvas id="c-stock"></canvas></div>
    </div>
    <div class="card">
      <h2>⑤ 월별 추가 구매 비용 (억 원)</h2>
      <p class="desc">급매 = 당월 스팟 × (1 + 긴급 프리미엄), 조기경보 = 전월 스팟으로 선구매.</p>
      <div class="chart"><canvas id="c-cost"></canvas></div>
    </div>
    <div class="card">
      <h2>연도별 요약</h2>
      <p class="desc">공백 중 직수입 요인 = 직수입 이탈분 ÷ (기온 요인 + 직수입 요인), 양(+)의 값만 합산. 연도별 절감액에는 기말재고 보정이 빠져 있습니다.</p>
      <div class="scroll"><table id="t-yearly"></table></div>
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <h2>경보 목록</h2>
    <p class="desc">발령월에 다음 달 부족을 예측해 선구매한 내역. API: <code>/api/alerts</code></p>
    <div class="scroll"><table id="t-alerts"></table></div>
  </div>

  <details>
    <summary>시뮬레이션 가정</summary>
    <p id="assump"></p>
  </details>
  {% endif %}
</div>

{% if not data.error %}
<script>
const D = {{ data | tojson }};
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = (v, d = 1) => v === null || v === undefined ? "–" : Number(v).toLocaleString("ko-KR", {maximumFractionDigits: d, minimumFractionDigits: d});
const M = D.metrics || {}, dem = M.demand || {}, dir = M.direct || {}, sim = M.simulation || {};

// KPI
const kpis = [
  {label: "총수요 MAPE (시험 구간)", value: fmt(dem.mape_test, 2) + "%", sub: "기준선(전년 동월) " + fmt(dem.mape_baseline_lag12, 2) + "%"},
  {label: "한파 구간 MAPE", value: fmt(dem.mape_cold, 2) + "%", sub: "HDD 상위 " + Math.round((1 - D.cold_q) * 100) + "% 달, " + (dem.n_cold ?? "–") + "개월"},
  {label: "직수입 MAPE", value: dir.available ? fmt(dir.mape_test, 2) + "%" : "데이터 없음", sub: dir.available ? "기준선 " + fmt(dir.mape_baseline_lag12, 2) + "%" : ""},
  {label: "경보 적중률", value: sim.alert_hit_rate_pct == null ? "–" : fmt(sim.alert_hit_rate_pct, 0) + "%", sub: "부족 " + (sim.shortage_months ?? "–") + "개월 · 오경보 " + (sim.false_alarms ?? "–") + "회"},
  {label: "절감 추정", value: fmt(sim.saving_eok, 0) + "억", sub: sim.period || "", cls: (sim.saving_eok || 0) > 0 ? "good" : ""},
];
document.getElementById("kpis").innerHTML = kpis.map(k =>
  `<div class="kpi ${k.cls || ""}"><div class="label">${k.label}</div><div class="value">${k.value}</div><div class="sub">${k.sub}</div></div>`).join("");
document.getElementById("demand-desc").textContent =
  `목표: ${dem.target === "national_demand" ? "국가 총수요(가스공사+직수입)" : "가스공사 공급량"} · 모델: ${dem.model === "gbr" ? "Gradient Boosting" : "선형회귀"} · ${D.train_end} 이후가 시험 구간`;

// Chart 공통
Chart.defaults.font.family = "'IBM Plex Sans KR', system-ui, sans-serif";
Chart.defaults.color = css("--muted");
Chart.defaults.borderColor = css("--line");
const base = (extra = {}) => ({
  responsive: true, maintainAspectRatio: false, interaction: {mode: "index", intersect: false},
  plugins: {legend: {position: "bottom", labels: {boxWidth: 12, boxHeight: 2}}},
  scales: {x: {ticks: {maxTicksLimit: 8}, grid: {display: false}}, y: {grid: {color: css("--line")}}},
  elements: {point: {radius: 0}, line: {borderWidth: 2, tension: 0.2}}, ...extra,
});
const line = (label, data, color, dash = []) => ({label, data, borderColor: color, backgroundColor: color, borderDash: dash, spanGaps: true});

new Chart("c-demand", {type: "line", data: {labels: D.demand.labels, datasets: [
  line("실제", D.demand.actual, css("--actual")),
  line("예측", D.demand.pred, css("--pred"), [5, 4]),
]}, options: base()});

new Chart("c-direct", {type: "line", data: {labels: D.direct.labels, datasets: [
  line("실제", D.direct.actual, css("--actual")),
  line("예측", D.direct.pred, css("--pred"), [5, 4]),
  line("전년 동월", D.direct.direct_normal, css("--plan"), [2, 3]),
]}, options: base()});

new Chart("c-burden", {type: "line", data: {labels: D.sim.labels, datasets: [
  line("실제", D.sim.burden_actual, css("--actual")),
  line("예측(전월)", D.sim.burden_fcst, css("--pred"), [5, 4]),
  line("계획(연초)", D.sim.burden_plan, css("--plan"), [2, 3]),
]}, options: base()});

const alertPts = D.sim.b_alert.map((a, i) => a ? D.sim.b_stock[i] : null);
new Chart("c-stock", {type: "line", data: {labels: D.sim.labels, datasets: [
  line("급매 전략 재고", D.sim.a_stock, css("--a")),
  line("조기경보 전략 재고", D.sim.b_stock, css("--b")),
  {...line("안전재고", D.sim.labels.map(() => D.safety_stock), css("--plan"), [4, 4]), borderWidth: 1},
  {label: "경보", data: alertPts, type: "line", showLine: false, pointRadius: 5, pointBackgroundColor: css("--b"), borderColor: css("--b")},
]}, options: base()});

new Chart("c-cost", {type: "bar", data: {labels: D.sim.labels, datasets: [
  {label: "급매", data: D.sim.a_cost, backgroundColor: css("--a")},
  {label: "조기경보", data: D.sim.b_cost, backgroundColor: css("--b")},
]}, options: base({elements: {}})});

// 연도별 표
const Y = sim.yearly || {};
const cls = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
document.getElementById("t-yearly").innerHTML =
  `<tr><th>연도</th><th>급매 비용</th><th>조기경보 비용</th><th>절감</th><th>경보</th><th>평균 스팟</th><th>직수입 요인</th></tr>` +
  Object.entries(Y).map(([y, v]) => `<tr><td>${y}</td><td class="num">${fmt(v.a_cost, 0)}</td><td class="num">${fmt(v.b_cost, 0)}</td>
    <td class="num ${cls(v.saving)}">${fmt(v.saving, 0)}</td><td class="num">${fmt(v.alerts, 0)}</td>
    <td class="num">${fmt(v.avg_spot, 1)}</td><td class="num">${v.direct_share_of_gap_pct == null ? "–" : fmt(v.direct_share_of_gap_pct, 0) + "%"}</td></tr>`).join("");

// 경보 표
document.getElementById("t-alerts").innerHTML = D.alerts.length ?
  `<tr><th>대상월</th><th>발령월</th><th>예상 부족량</th><th>선구매량</th><th>실제 부족 여부</th></tr>` +
  D.alerts.map(a => `<tr><td>${a.target_month}</td><td>${a.issued_month}</td><td class="num">${fmt(a.projected_short)}</td>
    <td class="num">${fmt(a.advance_buy)}</td><td>${a.actual_shortage ? '<span class="tag hit">적중</span>' : '<span class="tag">오경보</span>'}</td></tr>`).join("")
  : `<tr><td>시험 구간에 발령된 경보가 없습니다.</td></tr>`;

const A = sim.assumptions || {};
document.getElementById("assump").innerHTML =
  `시작재고 ${fmt(A.INITIAL_STOCK, 0)} · 안전재고 ${fmt(A.SAFETY_STOCK, 0)} · 긴급 프리미엄 ${fmt((A.URGENT_PREMIUM || 0) * 100, 0)}% · 환율 ${fmt(A.FX_KRW_PER_USD, 0)}원/$ · ` +
  `물량 1단위 = ${fmt(A.VOLUME_UNIT_TON, 0)}톤 · 1톤 = ${fmt(A.MMBTU_PER_TON, 0)} MMBtu · 스팟가격 출처: ${sim.spot_source || "–"} · ` +
  `기말재고 보정 ${fmt(sim.ending_stock_adjust_eok, 0)}억. 모두 <code>config.py</code>에서 바꿀 수 있습니다.`;
</script>
{% endif %}
</body>
</html>
