"""파이프라인 동작 확인용 '가짜' 데이터 생성기.

※ 여기서 만든 숫자는 실제 통계가 아닙니다. 코드가 끝까지 돌아가는지 확인하는 용도로만 쓰고,
  분석·자소서·면접에는 반드시 실제 데이터를 쓰세요.
  실행하면 data/raw의 같은 이름 파일을 덮어씁니다.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

rng = np.random.default_rng(42)


def main():
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    days = pd.date_range(f"{config.START_MONTH}-01", pd.Timestamp(config.END_MONTH) + pd.offsets.MonthEnd(0))

    # 일별 기온: 계절 사인파 + 관측소 편차 + 잡음, 일부 결측 포함
    rows = []
    offsets = {108: 0.0, 112: -0.3, 133: 0.2, 143: 1.0, 156: 1.2, 159: 2.5}
    seasonal = 13 - 14 * np.cos(2 * np.pi * (days.dayofyear - 15) / 365)
    for stn, off in offsets.items():
        avg = seasonal + off + rng.normal(0, 3, len(days))
        df = pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "stn_id": stn,
                           "avg_ta": avg.round(1), "min_ta": (avg - 5).round(1), "max_ta": (avg + 5).round(1)})
        df.loc[rng.random(len(df)) < 0.01, "avg_ta"] = np.nan
        rows.append(df)
    weather = pd.concat(rows)
    weather.to_csv(config.RAW_DIR / "weather_daily.csv", index=False, encoding="utf-8-sig")

    months = pd.date_range(config.START_MONTH, config.END_MONTH, freq="MS")
    w = weather.assign(date=pd.to_datetime(weather["date"])).groupby(pd.Grouper(key="date", freq="MS"))["avg_ta"].mean()
    hdd = (18 - w).clip(lower=0).values * 30

    n = len(months)
    jkm = 9 + 3 * rng.standard_normal(n).cumsum() / 6
    jkm[(months >= "2021-10") & (months <= "2022-12")] += 22  # 2022년 가격 급등 흉내
    jkm = jkm.clip(4)
    import_price = (10 + 0.4 * (jkm - 10)) * config.MMBTU_PER_TON  # $/톤, 스팟보다 완만
    spread = jkm - import_price / config.MMBTU_PER_TON

    direct = (900 - 25 * spread + rng.normal(0, 40, n)).clip(300)          # 가격차 클수록 직수입 감소
    total = 1500 + 2.6 * hdd + 0.6 * (900 - direct) + rng.normal(0, 60, n)  # 빠진 만큼 가스공사가 부담
    city = total * 0.55
    power = total - city

    def ym(fmt):
        return months.strftime(fmt)

    # 일부러 서로 다른 연월 형식·천 단위 쉼표를 섞어 전처리 견고성 확인
    pd.DataFrame({"연월": ym("%Y-%m"), "도시가스용": city.round(0), "발전용": power.round(0),
                  "합계": [f"{v:,.0f}" for v in total]}).to_csv(config.RAW_DIR / "gas_supply.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"연월": ym("%Y%m"), "SMP": (80 + 6 * jkm + rng.normal(0, 5, n)).round(2)}).to_csv(
        config.RAW_DIR / "smp.csv", index=False, encoding="cp949")
    pd.DataFrame({"연월": [f"{d.year}년 {d.month}월" for d in months], "LNG발전량": (12000 + 3 * hdd).round(0)}).to_excel(
        config.RAW_DIR / "generation_lng.xlsx", index=False)
    pd.DataFrame({"연월": ym("%Y.%m"), "수입단가": import_price.round(1), "JKM": jkm.round(2)}).to_csv(
        config.RAW_DIR / "lng_price.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"연월": ym("%Y-%m"), "직수입량": direct.round(0)}).to_csv(
        config.RAW_DIR / "direct_import.csv", index=False, encoding="utf-8-sig")
    # 대시보드에 '샘플 데이터' 경고를 띄우기 위한 표시 (실제 gas_supply 파일로 바꾸면 자동 해제)
    (config.RAW_DIR / "SAMPLE_DATA_FLAG").write_text("이 폴더의 데이터는 make_sample_data.py가 만든 가짜 데이터입니다.\n", encoding="utf-8")
    print(f"가짜 샘플 데이터 생성 완료: {config.RAW_DIR}")


if __name__ == "__main__":
    main()
