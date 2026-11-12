"""프로젝트 공통 설정.

API 키와 DB 주소는 .env 파일에 넣습니다(.env.example 참고).
수동으로 내려받은 파일의 컬럼명이 다르면 RAW_FILES의 매핑만 고치면 됩니다.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

# 분석 기간 (월 단위)
START_MONTH = "2015-01"
END_MONTH = "2025-12"

# ── 기상청 ASOS 일자료 (공공데이터포털 '기상청_지상(종관, ASOS) 일자료 조회서비스') ──
DATA_GO_KR_KEY = os.getenv("DATA_GO_KR_KEY", "")
ASOS_URL = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"

# 전국 대표 기온을 만들 관측소와 가중치 (인구 비중 등으로 조정 가능)
# 108 서울, 112 인천, 133 대전, 143 대구, 156 광주, 159 부산
STATIONS = {108: 0.40, 112: 0.10, 133: 0.10, 143: 0.12, 156: 0.08, 159: 0.20}

# 난방도일(HDD) 기준온도 (국내 통계에서 흔히 쓰는 18℃)
HDD_BASE_TEMP = 18.0

# 한파일 기준: 전국 가중평균 일평균기온이 이 값 이하인 날
COLD_DAY_TEMP = -5.0

# 수입단가($/톤)를 JKM과 같은 단위($/MMBtu)로 바꾸는 환산계수 (LNG 1톤 ≈ 52 MMBtu, 근사치)
MMBTU_PER_TON = 52.0

# ── 수동 다운로드 파일 ──
# file: data/raw 아래 파일명 (csv 또는 xlsx)
# month_col: 연월 컬럼명, cols: {원본 컬럼명: 표준 컬럼명}
RAW_FILES = {
    # 가스공사 천연가스 공급실적 (공공데이터포털 / 가스공사 홈페이지 통계)
    "gas_supply": {
        "file": "gas_supply.csv",
        "month_col": "연월",
        "cols": {"도시가스용": "supply_city", "발전용": "supply_power", "합계": "supply_total"},
    },
    # 전력거래소 EPSIS: 월별 SMP (육지, 원/kWh)
    "smp": {
        "file": "smp.csv",
        "month_col": "연월",
        "cols": {"SMP": "smp"},
    },
    # 전력거래소 EPSIS: 연료원별 발전량 중 LNG (GWh)
    "generation": {
        "file": "generation_lng.csv",
        "month_col": "연월",
        "cols": {"LNG발전량": "gen_lng"},
    },
    # LNG 가격: 수입단가(관세청 수출입무역통계 HS 271111, 금액/중량)와 JKM(선택)
    "lng_price": {
        "file": "lng_price.csv",
        "month_col": "연월",
        "cols": {"수입단가": "import_price", "JKM": "jkm"},
    },
    # 직수입 물량 또는 직수입 발전량 (에너지통계월보, 국정감사 자료 등)
    "direct_import": {
        "file": "direct_import.csv",
        "month_col": "연월",
        "cols": {"직수입량": "direct_import"},
    },
}

# ── 모델 (①·②) ──
# 이 달까지 학습, 이후는 시험(out-of-sample). 기본값은 2022년 위기를 시험 구간에 넣기 위한 설정
TRAIN_END = "2021-12"
# 학습 구간 마지막 N개월로 모델을 고른 뒤(검증), 시험 구간 성능을 보고
VALID_MONTHS = 24
# Gradient Boosting이 선형회귀보다 검증 MAPE가 이만큼(%p) 이상 낮을 때만 채택
GBR_MIN_GAIN = 0.5
# 동절기 정의
WINTER_MONTHS = [11, 12, 1, 2, 3]
# '한파 구간' = 학습 구간 HDD 상위 몇 % 이상인 달
COLD_HDD_QUANTILE = 0.80

# ── 경보·비용 시뮬레이션 (③·④·⑤) ──  ※ 모두 가정치. 실제 값을 알면 바꾸세요. 물량 단위는 공급실적과 같게(예: 천 톤)
INITIAL_STOCK = 1500.0    # 시뮬레이션 시작 재고
SAFETY_STOCK = 1000.0     # 이 아래로 내려가면 부족으로 보고 추가 구매
ALERT_THRESHOLD = 0.0     # 예상 재고가 안전재고보다 이만큼 이상 모자랄 때만 경보
URGENT_PREMIUM = 0.10     # 급매(당월 긴급 구매) 시 스팟가격 대비 추가 프리미엄 비율
FX_KRW_PER_USD = 1300.0   # 원/달러 환율 (단일 가정치)
VOLUME_UNIT_TON = 1000.0  # 물량 1단위가 몇 톤인지 (공급실적이 '천 톤'이면 1000)
# 스팟가격: JKM이 있으면 JKM, 없으면 수입단가($/MMBtu)×(1+이 값)으로 대체
SPOT_MARKUP_IF_NO_JKM = 0.30

# ── DB ──
# 기본값은 별도 설치가 필요 없는 SQLite.
# MySQL 예: mysql+pymysql://user:pw@localhost:3306/lng_gap  (sqlalchemy, pymysql 필요)
DB_URL = os.getenv("DB_URL", f"sqlite:///{ROOT / 'lng_gap.db'}")
