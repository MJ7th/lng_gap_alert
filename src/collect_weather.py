"""기상청 ASOS 일별 기온 수집.

공공데이터포털에서 '기상청_지상(종관, ASOS) 일자료 조회서비스' 활용신청 후
발급받은 일반 인증키(Decoding)를 .env의 DATA_GO_KR_KEY에 넣으세요.

결과: data/raw/weather_daily.csv  (date, stn_id, avg_ta, min_ta, max_ta)
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

OUT_FILE = config.RAW_DIR / "weather_daily.csv"
YESTERDAY = (date.today() - timedelta(days=1)).strftime("%Y%m%d")


def fetch_station_year(stn_id: int, year: int) -> pd.DataFrame:
    """관측소 1곳의 1년치 일자료를 가져온다 (1회 요청 최대 999행이라 연 단위로 나눔)."""
    params = {
        "serviceKey": config.DATA_GO_KR_KEY,
        "pageNo": 1,
        "numOfRows": 999,
        "dataType": "JSON",
        "dataCd": "ASOS",
        "dateCd": "DAY",
        "startDt": f"{year}0101",
        "endDt": min(f"{year}1231", YESTERDAY),  # API는 전날 자료까지만 제공
        "stnIds": stn_id,
    }
    for attempt in range(3):
        try:
            res = requests.get(config.ASOS_URL, params=params, timeout=30)
            res.raise_for_status()
            if not res.text.lstrip().startswith("{"):
                # 인증키 오류 등은 JSON이 아니라 XML로 내려온다 → 재시도해도 소용없으니 바로 중단
                sys.exit(f"API가 JSON이 아닌 응답을 보냈습니다(인증키·활용신청 승인 여부 확인):\n{res.text[:300]}")
            body = res.json()["response"]
            code = body["header"]["resultCode"]
            if code != "00":
                raise RuntimeError(f"API 오류 {code}: {body['header']['resultMsg']}")
            items = body["body"]["items"]["item"]
            df = pd.DataFrame(items)[["tm", "stnId", "avgTa", "minTa", "maxTa"]]
            df.columns = ["date", "stn_id", "avg_ta", "min_ta", "max_ta"]
            return df
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"  재시도 {attempt + 1}/3 ({stn_id}, {year}): {e}")
            time.sleep(2)
    raise RuntimeError(f"수집 실패: 관측소 {stn_id}, {year}년")


def main():
    if not config.DATA_GO_KR_KEY:
        sys.exit("DATA_GO_KR_KEY가 비어 있습니다. .env 파일을 확인하세요.")

    start_year = int(config.START_MONTH[:4])
    end_year = min(int(config.END_MONTH[:4]), int(YESTERDAY[:4]))
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    for stn in config.STATIONS:
        for year in range(start_year, end_year + 1):
            print(f"수집 중: 관측소 {stn}, {year}년")
            frames.append(fetch_station_year(stn, year))
            time.sleep(0.3)  # 호출 간격

    df = pd.concat(frames, ignore_index=True)
    for col in ["avg_ta", "min_ta", "max_ta"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["stn_id"] = df["stn_id"].astype(int)
    df.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUT_FILE} ({len(df):,}행)")


if __name__ == "__main__":
    main()
