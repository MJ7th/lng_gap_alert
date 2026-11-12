"""③ 부담물량 계산 · ④ 스팟 구매 조기경보 · ⑤ 비용 시뮬레이션.

③ 가스공사 부담물량
   - 계획(plan)    = 평년 기온 총수요 예측 − 전년 동월 직수입   ← 연초 장기계약으로 확보한 물량으로 간주
   - 예측(fcst)    = 총수요 예측 − 직수입 예측(전월 가격차 반영)
   - 실제(actual)  = 가스공사 실제 공급량
   - 공백 분해     = 기온 요인(실제 총수요 − 평년 예측) + 직수입 요인(전년 동월 직수입 − 실제 직수입)

④·⑤ 두 전략을 시험 구간에서 월별로 비교 (재고 = 시작재고 + 계획 + 구매 − 실제 공급)
   A. 급매: 당월에 부족이 드러나면 그 달 스팟가격 × (1 + 긴급 프리미엄)으로 구매
   B. 조기경보: 전월에 예측으로 부족을 계산해 경보 → 전월 스팟가격으로 미리 구매,
      그래도 모자라면 A와 같은 급매
   두 전략의 기말 재고 차이는 마지막 달 가격으로 환산해 비용을 보정합니다.

※ 재고·안전재고·프리미엄·환율은 config의 가정치입니다. 결과는 '이 가정에서의 추정'으로만 말하세요.
출력: data/processed/simulation.csv, DB 테이블 simulation, metrics.json의 'simulation'
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import common  # noqa: E402


def to_eok(volume, price_usd_mmbtu):
    """물량 × $/MMBtu → 억 원."""
    usd = volume * config.VOLUME_UNIT_TON * config.MMBTU_PER_TON * price_usd_mmbtu
    return usd * config.FX_KRW_PER_USD / 1e8


def build_frame() -> pd.DataFrame:
    feat = common.load_csv(common.FEATURES_CSV, "src/preprocess.py를 먼저 실행하세요.")
    dem = common.load_csv(common.DEMAND_CSV, "src/model_demand.py를 먼저 실행하세요.")
    dirc = common.load_csv(common.DIRECT_CSV, "src/model_direct.py를 먼저 실행하세요.")

    df = feat[["month", "supply_total"] + [c for c in ["jkm", "import_price_mmbtu"] if c in feat]].merge(
        dem[["month", "split", "actual", "pred", "pred_normal"]].rename(
            columns={"actual": "demand_actual", "pred": "demand_pred", "pred_normal": "demand_normal"}),
        on="month").merge(
        dirc[["month", "actual", "pred", "direct_normal"]].rename(
            columns={"actual": "direct_actual", "pred": "direct_pred"}),
        on="month")

    # 스팟가격
    if common.has_data(df, "jkm", 12):
        df["spot"] = df["jkm"]
        spot_src = "JKM"
    elif common.has_data(df, "import_price_mmbtu", 12):
        df["spot"] = df["import_price_mmbtu"] * (1 + config.SPOT_MARKUP_IF_NO_JKM)
        spot_src = f"수입단가×{1 + config.SPOT_MARKUP_IF_NO_JKM:.2f}"
        print(f"[주의] JKM이 없어 스팟가격을 {spot_src}로 대체합니다.")
    else:
        sys.exit("JKM과 수입단가가 모두 없어 비용 시뮬레이션을 할 수 없습니다.")
    df["spot_prev"] = df["spot"].shift(1)  # 조기경보 전략은 전월 가격으로 구매

    # ③ 부담물량
    df["burden_actual"] = df["supply_total"]
    df["burden_fcst"] = df["demand_pred"] - df["direct_pred"]
    df["burden_plan"] = df["demand_normal"] - df["direct_normal"]
    df["gap_weather"] = df["demand_actual"] - df["demand_normal"]
    df["gap_direct"] = df["direct_normal"] - df["direct_actual"]  # +면 직수입사가 평소보다 빠짐
    df.attrs["spot_src"] = spot_src
    return df


def run_strategies(sim: pd.DataFrame) -> pd.DataFrame:
    stock_a = stock_b = config.INITIAL_STOCK
    rows = []
    for _, r in sim.iterrows():
        plan, actual, fcst = r["burden_plan"], r["burden_actual"], r["burden_fcst"]
        p_now, p_prev = r["spot"], r["spot_prev"]

        # A. 급매
        pre_a = stock_a + plan - actual
        urgent_a = max(config.SAFETY_STOCK - pre_a, 0.0)
        stock_a = pre_a + urgent_a

        # B. 조기경보 (전월 의사결정)
        projected = stock_b + plan - fcst
        short = config.SAFETY_STOCK - projected
        alert = short > config.ALERT_THRESHOLD
        advance = max(short, 0.0) if alert else 0.0
        pre_b = stock_b + plan + advance - actual
        urgent_b = max(config.SAFETY_STOCK - pre_b, 0.0)
        stock_b = pre_b + urgent_b

        rows.append({
            "month": r["month"],
            "a_urgent": urgent_a, "a_cost": to_eok(urgent_a, p_now * (1 + config.URGENT_PREMIUM)), "a_stock": stock_a,
            "b_alert": int(alert), "b_projected_short": max(short, 0.0), "b_advance": advance,
            "b_urgent": urgent_b,
            "b_cost": to_eok(advance, p_prev) + to_eok(urgent_b, p_now * (1 + config.URGENT_PREMIUM)),
            "b_stock": stock_b,
        })
    return pd.DataFrame(rows)


def summarize(sim: pd.DataFrame, spot_src: str) -> dict:
    last_price = sim["spot"].iloc[-1]
    stock_diff = sim["b_stock"].iloc[-1] - sim["a_stock"].iloc[-1]
    adj = to_eok(stock_diff, last_price)  # B가 재고를 더 남겼으면 그만큼은 비용이 아니라 자산
    cost_a, cost_b = sim["a_cost"].sum(), sim["b_cost"].sum()

    need = sim["a_urgent"] > 0
    hit = need & (sim["b_alert"] == 1)
    false_alarm = (~need) & (sim["b_alert"] == 1)

    yearly = sim.assign(year=sim["month"].dt.year).groupby("year").agg(
        a_cost=("a_cost", "sum"), b_cost=("b_cost", "sum"),
        a_urgent=("a_urgent", "sum"), b_urgent=("b_urgent", "sum"), b_advance=("b_advance", "sum"),
        alerts=("b_alert", "sum"), gap_weather=("gap_weather", "sum"), gap_direct=("gap_direct", "sum"),
        avg_spot=("spot", "mean"), burden=("burden_actual", "sum"))
    yearly["saving"] = yearly["a_cost"] - yearly["b_cost"]
    # 공백 중 직수입 요인 비중. 공백 자체가 연간 공급량의 1% 미만이면 비율이 무의미하므로 비워 둔다.
    pos = yearly[["gap_weather", "gap_direct"]].clip(lower=0)
    total_gap = pos.sum(axis=1)
    share = pos["gap_direct"] / total_gap.replace(0, np.nan) * 100
    yearly["direct_share_of_gap_pct"] = share.where(total_gap >= 0.01 * yearly["burden"])
    yearly = yearly.drop(columns="burden")

    first_need = sim.loc[need, "month"].min()
    return {
        "period": f"{sim['month'].min():%Y-%m} ~ {sim['month'].max():%Y-%m}",
        "spot_source": spot_src,
        "assumptions": {k: getattr(config, k) for k in
                        ["INITIAL_STOCK", "SAFETY_STOCK", "ALERT_THRESHOLD", "URGENT_PREMIUM",
                         "FX_KRW_PER_USD", "VOLUME_UNIT_TON", "MMBTU_PER_TON"]},
        "cost_reactive_eok": round(cost_a, 1),
        "cost_proactive_eok": round(cost_b, 1),
        "ending_stock_adjust_eok": round(adj, 1),
        "saving_eok": round(cost_a - (cost_b - adj), 1),
        "urgent_volume_reactive": round(sim["a_urgent"].sum(), 1),
        "urgent_volume_proactive": round(sim["b_urgent"].sum(), 1),
        "shortage_months": int(need.sum()),
        "alerts": int(sim["b_alert"].sum()),
        "alert_hit_rate_pct": round(hit.sum() / need.sum() * 100, 1) if need.sum() else None,
        "false_alarms": int(false_alarm.sum()),
        "first_shortage_month": None if pd.isna(first_need) else f"{first_need:%Y-%m}",
        "lead_months": 1,
        "yearly": {int(y): {k: (None if pd.isna(v) else round(float(v), 1)) for k, v in row.items()}
                   for y, row in yearly.iterrows()},
    }


def main():
    df = build_frame()
    spot_src = df.attrs["spot_src"]
    need_cols = ["burden_plan", "burden_fcst", "burden_actual", "spot", "spot_prev"]
    sim = df[(df["split"] == "test") & df[need_cols].notna().all(axis=1)].reset_index(drop=True)
    if sim.empty:
        sys.exit("시험 구간에 시뮬레이션할 수 있는 달이 없습니다 (가격·예측값 결측 확인).")

    sim = sim.merge(run_strategies(sim), on="month")
    s = summarize(sim, spot_src)

    print(f"[시뮬레이션] {s['period']} | 스팟가격: {s['spot_source']}")
    print(f"  급매 전략 비용      {s['cost_reactive_eok']:>10,.1f} 억 원 (긴급구매 {s['urgent_volume_reactive']:,.0f})")
    print(f"  조기경보 전략 비용  {s['cost_proactive_eok']:>10,.1f} 억 원 (긴급구매 {s['urgent_volume_proactive']:,.0f})")
    print(f"  기말재고 보정       {s['ending_stock_adjust_eok']:>10,.1f} 억 원")
    print(f"  → 절감 추정         {s['saving_eok']:>10,.1f} 억 원")
    print(f"  부족 발생 {s['shortage_months']}개월 중 사전 경보 적중 {s['alert_hit_rate_pct']}% | "
          f"오경보 {s['false_alarms']}회 | 경보는 부족 1개월 전 발령")
    for y, v in s["yearly"].items():
        share = v["direct_share_of_gap_pct"]
        print(f"  {y}: 절감 {v['saving']:,.1f}억 | 경보 {v['alerts']:.0f}회 | "
              f"공백 중 직수입 요인 {'-' if share is None else f'{share:.0f}%'}")

    sim.to_csv(common.SIM_CSV, index=False, encoding="utf-8-sig")
    common.save_tables({"simulation": sim})
    common.update_metrics("simulation", s)
    print(f"[저장] {common.SIM_CSV}")


if __name__ == "__main__":
    main()
