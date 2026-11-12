"""전체 파이프라인 일괄 실행.

python run_all.py            # 실제 데이터 (data/raw에 파일을 넣은 뒤)
python run_all.py --sample   # 가짜 샘플 데이터를 만들어 전 과정 시험 실행
python run_all.py --weather  # 기상청 API 수집부터 (DATA_GO_KR_KEY 필요)
"""
import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from src import collect_weather, make_sample_data, model_demand, model_direct, preprocess, simulate  # noqa: E402


def step(title, fn):
    print(f"\n{'=' * 10} {title} {'=' * 10}")
    fn()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="가짜 샘플 데이터 생성 후 실행")
    ap.add_argument("--weather", action="store_true", help="기상청 API로 기온부터 수집")
    args = ap.parse_args()

    if args.sample:
        step("샘플 데이터 생성 (가짜)", make_sample_data.main)
    if args.weather:
        step("기온 수집", collect_weather.main)
    step("전처리", preprocess.main)
    step("① 총수요 예측", model_demand.main)
    step("② 직수입 예측", model_direct.main)
    step("③④⑤ 부담물량·경보·비용 시뮬레이션", simulate.main)
    print("\n완료. 대시보드: python app.py → http://127.0.0.1:5000")


if __name__ == "__main__":
    main()
