"""Flask 대시보드.

python app.py → http://127.0.0.1:5000
- /           대시보드 (예측 정확도, 부담물량, 재고·경보, 비용 비교)
- /api/data   같은 데이터를 JSON으로 (다른 시스템 연계용)
- /api/alerts 경보 목록만 JSON으로
run_all.py를 먼저 실행해 data/processed에 결과 파일을 만들어 두어야 합니다.
"""
import math
import sys
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template

sys.path.append(str(Path(__file__).resolve().parent))
import config  # noqa: E402
from src import common  # noqa: E402

app = Flask(__name__)


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _series(df: pd.DataFrame, cols: list[str]) -> dict:
    out = {"labels": df["month"].dt.strftime("%Y-%m").tolist()}
    for c in cols:
        if c in df:
            out[c] = [_clean(round(float(v), 2)) if pd.notna(v) else None for v in df[c]]
    return out


def load_all() -> dict:
    missing = [p.name for p in (common.DEMAND_CSV, common.DIRECT_CSV, common.SIM_CSV) if not p.exists()]
    if missing:
        return {"error": f"결과 파일이 없습니다: {', '.join(missing)}. 먼저 python run_all.py 를 실행하세요."}

    demand = common.load_csv(common.DEMAND_CSV)
    direct = common.load_csv(common.DIRECT_CSV)
    sim = common.load_csv(common.SIM_CSV)
    metrics = common.read_metrics()

    alerts = sim[sim["b_alert"] == 1]
    alert_rows = [{
        "target_month": m.strftime("%Y-%m"),
        "issued_month": (m - pd.DateOffset(months=1)).strftime("%Y-%m"),
        "projected_short": round(float(s), 1),
        "advance_buy": round(float(a), 1),
        "actual_shortage": bool(u > 0),
    } for m, s, a, u in zip(alerts["month"], alerts["b_projected_short"], alerts["b_advance"], alerts["a_urgent"])]

    return {
        "sample": common.is_sample_data(),
        "train_end": config.TRAIN_END,
        "safety_stock": config.SAFETY_STOCK,
        "cold_q": config.COLD_HDD_QUANTILE,
        "metrics": metrics,
        "demand": _series(demand, ["actual", "pred", "pred_normal"]),
        "direct": _series(direct, ["actual", "pred", "direct_normal"]),
        "sim": _series(sim, ["burden_plan", "burden_fcst", "burden_actual", "a_stock", "b_stock",
                             "a_cost", "b_cost", "b_alert", "spot"]),
        "alerts": alert_rows,
    }


@app.route("/")
def index():
    data = load_all()
    return render_template("dashboard.html", data=data)


@app.route("/api/data")
def api_data():
    return jsonify(load_all())


@app.route("/api/alerts")
def api_alerts():
    data = load_all()
    return jsonify(data.get("alerts", data))


if __name__ == "__main__":
    app.run(debug=False, port=5000)
