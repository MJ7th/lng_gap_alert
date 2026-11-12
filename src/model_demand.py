"""① 총수요 예측 모델.

- 목표변수: 직수입 데이터가 있으면 '국가 총수요 = 가스공사 공급 + 직수입', 없으면 '가스공사 공급량'
- 설명변수: HDD, 한파일수, 월 더미(계절성), 전년 동월 값, 전월 가격차(있을 때)
- 후보 모델: 선형회귀(설명력·해석 용이), Gradient Boosting(비선형) → 학습 구간 끝 검증으로 선택
- 평가: 시험 구간 MAPE를 전체 / 동절기 / 한파 구간으로 나눠서 (평균보다 피크 오차가 중요)
- 기상 시나리오: pred = 실제 HDD 사용(완벽한 기상예보 가정), pred_normal = 평년 HDD 사용(연초 계획용)

출력: data/processed/demand_pred.csv, DB 테이블 demand_pred, metrics.json의 'demand'
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LinearRegression

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import common  # noqa: E402


def build_target(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if common.has_data(df, "direct_import"):
        df["national_demand"] = df["supply_total"] + df["direct_import"]
        return df, "national_demand"
    print("[안내] 직수입 데이터가 없어 '가스공사 공급량'을 총수요 대신 예측합니다.")
    return df, "supply_total"


def design_matrix(df: pd.DataFrame, target: str, hdd_col="hdd", cold_col="cold_days") -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    X["hdd"] = df[hdd_col]
    X["cold_days"] = df[cold_col]
    X["lag12"] = df[target].shift(12)
    # 가격이 오르면 직수입 이탈뿐 아니라 가스발전 자체도 줄어든다(타 연료 대체) → 전월 가격차 반영
    if common.has_data(df, "price_spread_lag1"):
        X["price_spread_lag1"] = df["price_spread_lag1"]
    return pd.concat([X, common.month_dummies(df)], axis=1)


def normal_weather(df: pd.DataFrame, train: pd.Series) -> pd.DataFrame:
    """학습 구간의 같은 달 평균을 '평년값'으로."""
    clim = df[train].groupby(df["month"].dt.month)[["hdd", "cold_days"]].mean()
    m = df["month"].dt.month
    df["hdd_normal"] = m.map(clim["hdd"])
    df["cold_days_normal"] = m.map(clim["cold_days"])
    return df


def make_models():
    return {
        "linear": LinearRegression(),
        "gbr": GradientBoostingRegressor(n_estimators=300, max_depth=2, learning_rate=0.05,
                                         subsample=0.8, random_state=0),
    }


def evaluate(df, target, pred_col, test, cold_threshold) -> dict:
    t = df[test]
    winter = t["month"].dt.month.isin(config.WINTER_MONTHS)
    cold = t["hdd"] >= cold_threshold
    return {
        "mape_test": common.mape(t[target], t[pred_col]),
        "mape_winter": common.mape(t.loc[winter, target], t.loc[winter, pred_col]),
        "mape_cold": common.mape(t.loc[cold, target], t.loc[cold, pred_col]),
        "rmse_test": common.rmse(t[target], t[pred_col]),
        "n_test": int(t[pred_col].notna().sum()),
        "n_cold": int(cold.sum()),
    }


def main():
    df = common.load_csv(common.FEATURES_CSV, "src/preprocess.py를 먼저 실행하세요.")
    if not common.has_data(df, "hdd") or not common.has_data(df, "supply_total"):
        sys.exit("hdd 또는 supply_total 데이터가 부족합니다 (24개월 이상 필요).")

    df, target = build_target(df)
    train = common.split_mask(df)
    test = ~train
    if test.sum() == 0:
        sys.exit(f"시험 구간이 없습니다. config.TRAIN_END({config.TRAIN_END})를 데이터 끝보다 앞으로 당기세요.")
    df = normal_weather(df, train)

    X = design_matrix(df, target)
    X_normal = design_matrix(df, target, "hdd_normal", "cold_days_normal")
    # 연초 계획은 그해 가격 급등을 모른다 → 가격차도 학습 구간 중앙값(평상시)으로 고정
    if "price_spread_lag1" in X_normal:
        X_normal["price_spread_lag1"] = float(df.loc[train, "price_spread_lag1"].median())
    y = df[target]
    usable = X.notna().all(axis=1) & y.notna()

    # 1) 모델 선택: 학습 구간 마지막 VALID_MONTHS개월로 검증
    tr_idx = df.index[train & usable]
    fit_idx, val_idx = tr_idx[:-config.VALID_MONTHS], tr_idx[-config.VALID_MONTHS:]
    if len(fit_idx) < 24:
        sys.exit("학습 데이터가 너무 적습니다. START_MONTH를 앞당기거나 VALID_MONTHS를 줄이세요.")
    val_scores = {}
    for name, model in make_models().items():
        model.fit(X.loc[fit_idx], y.loc[fit_idx])
        val_scores[name] = common.mape(y.loc[val_idx], model.predict(X.loc[val_idx]))
    # 선형회귀를 기본으로 하고, GBR이 뚜렷이(GBR_MIN_GAIN %p 이상) 나을 때만 바꾼다.
    # 트리 모델은 학습 범위를 벗어난 값(기록적 한파)을 외삽하지 못해 피크 수요를 낮게 잡을 수 있기 때문.
    best = "gbr" if val_scores["linear"] - val_scores["gbr"] >= config.GBR_MIN_GAIN else "linear"
    print("[검증 MAPE] " + ", ".join(f"{k}: {v:.2f}%" for k, v in val_scores.items()) + f" → 선택: {best}")

    # 2) 선택 모델을 학습 구간 전체로 다시 학습 후 전 기간 예측
    model = make_models()[best]
    model.fit(X.loc[tr_idx], y.loc[tr_idx])
    ok = X.notna().all(axis=1)
    okn = X_normal.notna().all(axis=1)
    df["pred"] = np.nan
    df["pred_normal"] = np.nan
    df.loc[ok, "pred"] = model.predict(X.loc[ok])
    df.loc[okn, "pred_normal"] = model.predict(X_normal.loc[okn])
    df["split"] = np.where(train, "train", "test")

    # 3) 평가
    cold_thr = float(df.loc[train, "hdd"].quantile(config.COLD_HDD_QUANTILE))
    metrics = {"target": target, "model": best, "valid_mape": val_scores,
               "cold_hdd_threshold": cold_thr, **evaluate(df, target, "pred", test, cold_thr)}
    # 비교 기준선: 전년 동월 값을 그대로 쓰는 단순 예측
    metrics["mape_baseline_lag12"] = common.mape(df.loc[test, target], X.loc[test, "lag12"])
    if best == "linear":
        metrics["coef"] = {c: float(v) for c, v in zip(X.columns, model.coef_) if not c.startswith("m_")}

    print(f"[시험 MAPE] 전체 {metrics['mape_test']:.2f}% | 동절기 {metrics['mape_winter']:.2f}% | "
          f"한파 {metrics['mape_cold'] if metrics['mape_cold'] is not None else float('nan'):.2f}% "
          f"(한파 {metrics['n_cold']}개월) | 기준선(전년 동월) {metrics['mape_baseline_lag12']:.2f}%")

    out = df[["month", "split", target, "hdd", "hdd_normal", "cold_days", "pred", "pred_normal"]].rename(
        columns={target: "actual"})
    out["target"] = target
    out.to_csv(common.DEMAND_CSV, index=False, encoding="utf-8-sig")
    common.save_tables({"demand_pred": out})
    common.update_metrics("demand", metrics)
    print(f"[저장] {common.DEMAND_CSV}")


if __name__ == "__main__":
    main()
