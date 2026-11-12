"""모델·시뮬레이션·대시보드가 함께 쓰는 함수."""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

FEATURES_CSV = config.PROCESSED_DIR / "monthly_features.csv"
DEMAND_CSV = config.PROCESSED_DIR / "demand_pred.csv"
DIRECT_CSV = config.PROCESSED_DIR / "direct_pred.csv"
SIM_CSV = config.PROCESSED_DIR / "simulation.csv"
METRICS_JSON = config.PROCESSED_DIR / "metrics.json"
SAMPLE_FLAG = config.RAW_DIR / "SAMPLE_DATA_FLAG"


def load_csv(path: Path, required_msg: str = "") -> pd.DataFrame:
    if not path.exists():
        sys.exit(f"[파일 없음] {path}\n{required_msg}")
    df = pd.read_csv(path)
    df["month"] = pd.to_datetime(df["month"])
    return df


def has_data(df: pd.DataFrame, col: str, min_rows: int = 24) -> bool:
    return col in df.columns and df[col].notna().sum() >= min_rows


def split_mask(df: pd.DataFrame) -> pd.Series:
    """True = 학습 구간."""
    return df["month"] <= pd.Timestamp(config.TRAIN_END)


def month_dummies(df: pd.DataFrame) -> pd.DataFrame:
    """월 더미(1월 기준 제외). 계절성 반영."""
    d = pd.get_dummies(df["month"].dt.month, prefix="m", drop_first=True).astype(float)
    for m in range(2, 13):  # 데이터에 없는 달도 컬럼은 항상 존재하게
        d[f"m_{m}"] = d.get(f"m_{m}", 0.0)
    return d[[f"m_{m}" for m in range(2, 13)]].set_index(df.index)


def mape(actual, pred) -> float | None:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    ok = ~(np.isnan(a) | np.isnan(p)) & (a != 0)
    if ok.sum() == 0:
        return None
    return float(np.mean(np.abs((a[ok] - p[ok]) / a[ok])) * 100)


def rmse(actual, pred) -> float | None:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    ok = ~(np.isnan(a) | np.isnan(p))
    if ok.sum() == 0:
        return None
    return float(np.sqrt(np.mean((a[ok] - p[ok]) ** 2)))


def update_metrics(section: str, values: dict):
    data = {}
    if METRICS_JSON.exists():
        data = json.loads(METRICS_JSON.read_text(encoding="utf-8"))
    data[section] = values
    METRICS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_metrics() -> dict:
    if METRICS_JSON.exists():
        return json.loads(METRICS_JSON.read_text(encoding="utf-8"))
    return {}


def save_tables(tables: dict[str, pd.DataFrame]):
    """CSV와 같은 내용을 DB에도 저장 (SQLite 기본, MySQL은 DB_URL 설정 시)."""
    out = {}
    for name, df in tables.items():
        df = df.copy()
        if "month" in df and np.issubdtype(df["month"].dtype, np.datetime64):
            df["month"] = df["month"].dt.strftime("%Y-%m")
        out[name] = df
    url = config.DB_URL
    if url.startswith("sqlite:///"):
        conn = sqlite3.connect(url.replace("sqlite:///", "", 1))
        try:
            for name, df in out.items():
                df.to_sql(name, conn, if_exists="replace", index=False)
        finally:
            conn.close()
    else:
        from sqlalchemy import create_engine
        engine = create_engine(url)
        for name, df in out.items():
            df.to_sql(name, engine, if_exists="replace", index=False)


def is_sample_data() -> bool:
    """가짜 샘플 데이터로 만든 결과인지. 샘플 생성 이후 gas_supply 파일을 바꿨으면 실제 데이터로 본다."""
    if not SAMPLE_FLAG.exists():
        return False
    gas = [p for p in config.RAW_DIR.glob("gas_supply.*")]
    return not gas or max(p.stat().st_mtime for p in gas) <= SAMPLE_FLAG.stat().st_mtime + 1
