"""② 직수입 공급 예측 모델.

가격 신호로 '직수입사가 언제 빠지는가'를 예측합니다.
- 목표변수: direct_import (월별 직수입량)
- 설명변수: 전월 가격차(JKM − 수입단가), 전월 SMP, HDD, 월 더미, 전년 동월 직수입량
  (가격 변수는 전월 값만 사용 → 예측 시점에 이미 알 수 있는 정보)
- 계획용 값: direct_normal = 전년 동월 직수입량 (연초에 가격 급변을 모른다고 가정)

직수입 데이터가 없으면 직수입을 0으로 두고 건너뜁니다(③에서 총수요 = 가스공사 공급으로 처리).
출력: data/processed/direct_pred.csv, DB 테이블 direct_pred, metrics.json의 'direct'
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import common  # noqa: E402


def main():
    df = common.load_csv(common.FEATURES_CSV, "src/preprocess.py를 먼저 실행하세요.")
    train = common.split_mask(df)
    test = ~train

    if not common.has_data(df, "direct_import"):
        print("[건너뜀] 직수입 데이터가 없어 직수입 예측을 0으로 둡니다.")
        out = pd.DataFrame({"month": df["month"], "split": np.where(train, "train", "test"),
                            "actual": np.nan, "pred": 0.0, "direct_normal": 0.0})
        out.to_csv(common.DIRECT_CSV, index=False, encoding="utf-8-sig")
        common.save_tables({"direct_pred": out})
        common.update_metrics("direct", {"available": False})
        return

    X = pd.DataFrame(index=df.index)
    used = []
    for col in ["price_spread_lag1", "smp_lag1"]:
        if common.has_data(df, col):
            X[col] = df[col]
            used.append(col)
    if "price_spread_lag1" not in used:
        print("[주의] JKM 또는 수입단가가 없어 가격차 신호 없이 학습합니다. 이탈 예측력이 크게 떨어질 수 있습니다.")
    X["hdd"] = df["hdd"]
    X["lag12"] = df["direct_import"].shift(12)
    X = pd.concat([X, common.month_dummies(df)], axis=1)
    y = df["direct_import"]

    fit = train & X.notna().all(axis=1) & y.notna()
    if fit.sum() < 24:
        sys.exit("직수입 모델 학습 데이터가 24개월 미만입니다.")
    model = LinearRegression().fit(X[fit], y[fit])

    ok = X.notna().all(axis=1)
    df["pred"] = np.nan
    df.loc[ok, "pred"] = model.predict(X[ok])
    df["direct_normal"] = X["lag12"]

    coef = {c: float(v) for c, v in zip(X.columns, model.coef_) if not c.startswith("m_")}
    metrics = {
        "available": True,
        "features": used + ["hdd", "lag12"],
        "mape_test": common.mape(y[test], df.loc[test, "pred"]),
        "mape_baseline_lag12": common.mape(y[test], df.loc[test, "direct_normal"]),
        "coef": coef,
    }
    msg = f"[직수입 시험 MAPE] 모델 {metrics['mape_test']:.2f}% | 기준선(전년 동월) {metrics['mape_baseline_lag12']:.2f}%"
    if "price_spread_lag1" in coef:
        msg += f" | 가격차 1$/MMBtu 확대 시 직수입 {coef['price_spread_lag1']:+.1f} (물량 단위)"
    print(msg)

    out = pd.DataFrame({"month": df["month"], "split": np.where(train, "train", "test"),
                        "actual": y, "pred": df["pred"], "direct_normal": df["direct_normal"]})
    out.to_csv(common.DIRECT_CSV, index=False, encoding="utf-8-sig")
    common.save_tables({"direct_pred": out})
    common.update_metrics("direct", metrics)
    print(f"[저장] {common.DIRECT_CSV}")


if __name__ == "__main__":
    main()
