"""전처리: 일별 기온 → 월별 HDD, 수동 다운로드 파일 정리, 월 단위 병합, DB 적재.

입력: data/raw/weather_daily.csv + config.RAW_FILES에 적힌 파일들
출력: data/processed/monthly_features.csv, DB 테이블 weather_daily / monthly_features
"""
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

REQUIRED = {"gas_supply"}  # 없으면 중단. 나머지는 없으면 경고 후 건너뜀


# ───────────────────────── 공통 유틸 ─────────────────────────
def parse_month(value) -> pd.Timestamp:
    """'2015-01', '201501', '2015.1', '2015년 1월', 날짜형 등을 월초 Timestamp로 통일."""
    if pd.isna(value):
        return pd.NaT
    if isinstance(value, (pd.Timestamp, np.datetime64)) or hasattr(value, "year"):
        ts = pd.Timestamp(value)
        return pd.Timestamp(ts.year, ts.month, 1)
    s = str(value).strip()
    m = re.match(r"^(\d{4})\D*(\d{1,2})", s)
    if not m:
        return pd.NaT
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return pd.NaT
    return pd.Timestamp(year, month, 1)


def to_number(series: pd.Series) -> pd.Series:
    """'1,234', ' 56 ', '-' 같은 문자열을 숫자로."""
    return pd.to_numeric(
        series.astype(str).str.replace(",", "").str.strip().replace({"-": None, "": None}),
        errors="coerce",
    )


def read_table(path: Path) -> pd.DataFrame:
    # 전부 문자열로 읽는다: '2015.10'이 숫자 2015.1(=1월)로 바뀌는 사고 방지
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str)
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 읽을 수 없습니다: {path}")


# ───────────────────────── 기온 → HDD ─────────────────────────
def build_weather_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily["w"] = daily["stn_id"].map(config.STATIONS)
    daily = daily.dropna(subset=["avg_ta", "w"])

    # 관측소 가중평균 (일부 관측소 결측일은 남은 관측소 가중치로 재정규화)
    national = (
        daily.assign(wt=daily["avg_ta"] * daily["w"])
        .groupby("date")
        .agg(wt=("wt", "sum"), w=("w", "sum"), min_ta=("min_ta", "min"))
    )
    national["avg_ta"] = national["wt"] / national["w"]
    national["hdd"] = (config.HDD_BASE_TEMP - national["avg_ta"]).clip(lower=0)
    national["cold_day"] = (national["avg_ta"] <= config.COLD_DAY_TEMP).astype(int)

    monthly = national.resample("MS").agg(
        avg_temp=("avg_ta", "mean"),
        min_temp=("min_ta", "min"),
        hdd=("hdd", "sum"),
        cold_days=("cold_day", "sum"),
        obs_days=("avg_ta", "count"),
    )
    monthly.index.name = "month"
    return monthly.reset_index()


# ───────────────────────── 수동 파일 ─────────────────────────
def load_raw(name: str, spec: dict) -> pd.DataFrame | None:
    path = config.RAW_DIR / spec["file"]
    if not path.exists():  # 확장자만 다른 파일(csv↔xlsx)도 허용
        for ext in (".csv", ".xlsx", ".xls"):
            if path.with_suffix(ext).exists():
                path = path.with_suffix(ext)
                break
    if not path.exists():
        if name in REQUIRED:
            sys.exit(f"[필수 파일 없음] {path}")
        print(f"[건너뜀] {spec['file']} 없음 → 관련 변수는 비워 둡니다.")
        return None

    df = read_table(path)
    df.columns = [str(c).strip() for c in df.columns]
    if spec["month_col"] not in df.columns:
        sys.exit(f"[컬럼 없음] {spec['file']}에 '{spec['month_col']}' 컬럼이 없습니다. 실제 컬럼: {list(df.columns)}")

    keep = {c: std for c, std in spec["cols"].items() if c in df.columns}
    missing = set(spec["cols"]) - set(keep)
    if missing:
        print(f"[주의] {spec['file']}에 없는 컬럼: {sorted(missing)}")

    out = pd.DataFrame({"month": df[spec["month_col"]].map(parse_month)})
    for src, std in keep.items():
        out[std] = to_number(df[src])
    bad = out["month"].isna().sum()
    if bad:
        print(f"[주의] {spec['file']}: 연월을 해석하지 못한 {bad}행 제외")
    out = out.dropna(subset=["month"]).groupby("month", as_index=False).mean()
    print(f"[읽음] {path.name}: {len(out)}개월, 컬럼 {list(keep.values())}")
    return out


# ───────────────────────── 파생 변수 ─────────────────────────
def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("month").reset_index(drop=True)
    df["year"] = df["month"].dt.year
    df["mon"] = df["month"].dt.month
    df["is_winter"] = df["mon"].isin([11, 12, 1, 2, 3]).astype(int)

    # 직수입 이탈 신호: 스팟(JKM)과 장기계약 대용치(수입단가)의 차이, $/MMBtu
    if "import_price" in df:
        df["import_price_mmbtu"] = df["import_price"] / config.MMBTU_PER_TON
        if "jkm" in df:
            df["price_spread"] = df["jkm"] - df["import_price_mmbtu"]

    # 가스공사 부담 비중: 발전용 공급 대비 직수입 (둘 다 있을 때)
    if {"direct_import", "supply_total"} <= set(df.columns):
        df["direct_share"] = df["direct_import"] / (df["direct_import"] + df["supply_total"])

    # 시차 변수 (전월 값). 예측 시점에 이미 알 수 있는 정보만 쓰기 위함
    for col in ["supply_total", "hdd", "price_spread", "smp", "direct_import"]:
        if col in df:
            df[f"{col}_lag1"] = df[col].shift(1)
    # 전년 동월 공급량 (계절성 기준선)
    if "supply_total" in df:
        df["supply_total_lag12"] = df["supply_total"].shift(12)
    return df


def fill_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """최대 2개월짜리 결측만 선형보간. 그보다 긴 공백은 남겨서 보고."""
    num = df.select_dtypes("number").columns
    df[num] = df[num].interpolate(limit=2, limit_area="inside")
    return df


# ───────────────────────── DB ─────────────────────────
def save_to_db(tables: dict[str, pd.DataFrame]):
    url = config.DB_URL
    if url.startswith("sqlite:///"):
        conn = sqlite3.connect(url.replace("sqlite:///", "", 1))
        try:
            for name, df in tables.items():
                df.to_sql(name, conn, if_exists="replace", index=False)
        finally:
            conn.close()
    else:  # MySQL 등
        from sqlalchemy import create_engine
        engine = create_engine(url)
        for name, df in tables.items():
            df.to_sql(name, engine, if_exists="replace", index=False)
    print(f"[DB] {url.split('@')[-1]} 에 {', '.join(tables)} 저장")


# ───────────────────────── 품질 리포트 ─────────────────────────
def report(df: pd.DataFrame):
    print("\n========== 데이터 점검 ==========")
    print(f"기간: {df['month'].min():%Y-%m} ~ {df['month'].max():%Y-%m} ({len(df)}개월)")
    na = df.isna().sum()
    na = na[na > 0]
    if len(na):
        print("남은 결측(시차 변수의 첫 행 결측은 정상):")
        for col, n in na.items():
            print(f"  {col}: {n}개월")
    if "obs_days" in df:
        thin = df[df["obs_days"] < 25]
        if len(thin):
            print(f"[주의] 기온 관측일이 25일 미만인 달: {', '.join(thin['month'].dt.strftime('%Y-%m'))}")
    if {"hdd", "supply_total"} <= set(df.columns):
        r = df[["hdd", "supply_total"]].corr().iloc[0, 1]
        print(f"HDD-총공급량 상관계수: {r:.3f}  (0.8 이상이면 기온만으로도 설명력이 큼)")
    print("=================================\n")


def main():
    weather_path = config.RAW_DIR / "weather_daily.csv"
    if not weather_path.exists():
        sys.exit("weather_daily.csv가 없습니다. src/collect_weather.py를 먼저 실행하세요.")
    daily = pd.read_csv(weather_path)
    merged = build_weather_monthly(daily)

    for name, spec in config.RAW_FILES.items():
        part = load_raw(name, spec)
        if part is not None:
            merged = merged.merge(part, on="month", how="outer")

    start, end = pd.Timestamp(config.START_MONTH), pd.Timestamp(config.END_MONTH)
    merged = merged[(merged["month"] >= start) & (merged["month"] <= end)]
    merged = add_features(fill_gaps(merged))
    report(merged)

    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = config.PROCESSED_DIR / "monthly_features.csv"
    merged.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[저장] {out}")

    db_monthly = merged.assign(month=merged["month"].dt.strftime("%Y-%m"))
    save_to_db({"weather_daily": daily, "monthly_features": db_monthly})


if __name__ == "__main__":
    main()
