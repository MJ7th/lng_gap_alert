[기온·HDD] ────────────→ ① 총수요 예측 ──┐
                                          ├→ ③ 가스공사 부담물량 = 총수요 − 직수입
[JKM−수입단가 가격차·SMP] → ② 직수입 예측 ─┘            │
                                                        ↓
                                  ④ 재고 시뮬레이션 → 조기경보 (1개월 전)
                                                        ↓
                                  ⑤ 급매 vs 선구매 비용 비교 → Flask 대시보드

lng_gap/
├─ run_all.py                # 전체 파이프라인 일괄 실행
├─ app.py                    # Flask 대시보드 + JSON API
├─ config.py                 # 기간, 관측소, 컬럼 매핑, 모델·시뮬레이션 가정, DB 주소
├─ src/
│  ├─ collect_weather.py     # 기상청 ASOS 일별 기온 수집 (API)
│  ├─ preprocess.py          # HDD 계산, 파일 병합, 파생변수, DB 적재
│  ├─ model_demand.py        # ① 총수요 예측
│  ├─ model_direct.py        # ② 직수입 예측
│  ├─ simulate.py            # ③ 부담물량 ④ 경보 ⑤ 비용 시뮬레이션
│  ├─ common.py              # 공통 함수 (지표, 저장, 샘플 여부)
│  └─ make_sample_data.py    # 동작 확인용 가짜 데이터 (분석에 사용 금지)
├─ templates/dashboard.html
├─ tests/test_core.py        # 연월 파싱, HDD, MAPE, 시뮬레이션 불변식
└─ data/raw, data/processed
