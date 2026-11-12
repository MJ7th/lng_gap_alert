"""핵심 로직 단위 테스트. 실행: python -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import common, preprocess, simulate  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_month_formats(self):
        for raw in ["2015-10", "201510", "2015.10", "2015년 10월", "2015/10/01", pd.Timestamp("2015-10-17")]:
            self.assertEqual(preprocess.parse_month(raw), pd.Timestamp(2015, 10, 1), raw)

    def test_month_invalid(self):
        for raw in ["합계", "2015-13", None, ""]:
            self.assertTrue(pd.isna(preprocess.parse_month(raw)), raw)

    def test_number_cleanup(self):
        out = preprocess.to_number(pd.Series(["1,234", " 56 ", "-", "", "7.5"]))
        self.assertEqual(out.iloc[0], 1234)
        self.assertEqual(out.iloc[1], 56)
        self.assertTrue(pd.isna(out.iloc[2]) and pd.isna(out.iloc[3]))
        self.assertEqual(out.iloc[4], 7.5)


class WeatherTest(unittest.TestCase):
    def test_hdd_and_weight_renormalization(self):
        stations = list(config.STATIONS)
        rows = []
        for d, temp in [("2020-01-01", 8.0), ("2020-01-02", 20.0)]:
            for s in stations:
                rows.append({"date": d, "stn_id": s, "avg_ta": temp, "min_ta": temp - 3, "max_ta": temp + 3})
        # 셋째 날은 관측소 하나만 값이 있음 → 그 관측소 값이 그대로 전국값이 되어야 함
        rows.append({"date": "2020-01-03", "stn_id": stations[0], "avg_ta": -7.0, "min_ta": -10.0, "max_ta": -4.0})
        m = preprocess.build_weather_monthly(pd.DataFrame(rows)).iloc[0]
        # HDD = (18-8) + 0 + (18-(-7)) = 35
        self.assertAlmostEqual(m["hdd"], 35.0, places=6)
        self.assertEqual(m["cold_days"], 1)
        self.assertEqual(m["obs_days"], 3)
        self.assertAlmostEqual(m["min_temp"], -10.0)


class MetricTest(unittest.TestCase):
    def test_mape_ignores_nan(self):
        self.assertAlmostEqual(common.mape([100, 200, float("nan")], [110, 180, 5]), 10.0)
        self.assertIsNone(common.mape([float("nan")], [1]))


class SimulationTest(unittest.TestCase):
    def frame(self, plan, actual, fcst, spot, spot_prev):
        n = len(plan)
        return pd.DataFrame({"month": pd.date_range("2022-01-01", periods=n, freq="MS"),
                             "burden_plan": plan, "burden_actual": actual, "burden_fcst": fcst,
                             "spot": spot, "spot_prev": spot_prev})

    def test_cost_unit(self):
        # 1단위(천 톤) × 10 $/MMBtu = 1000톤 × 52 × 10 $ × 환율 ÷ 1억
        expect = config.VOLUME_UNIT_TON * config.MMBTU_PER_TON * 10 * config.FX_KRW_PER_USD / 1e8
        self.assertAlmostEqual(simulate.to_eok(1, 10), expect)

    def test_no_shortage_no_purchase(self):
        out = simulate.run_strategies(self.frame([100] * 3, [100] * 3, [100] * 3, [10] * 3, [10] * 3))
        self.assertEqual(out["a_urgent"].sum(), 0)
        self.assertEqual(out["b_alert"].sum(), 0)
        self.assertEqual(out["a_cost"].sum() + out["b_cost"].sum(), 0)

    def test_stock_never_below_safety(self):
        out = simulate.run_strategies(self.frame([100] * 4, [900, 100, 2500, 100], [100, 100, 100, 100],
                                                 [10, 20, 30, 40], [10, 10, 20, 30]))
        self.assertTrue((out["a_stock"] >= config.SAFETY_STOCK - 1e-9).all())
        self.assertTrue((out["b_stock"] >= config.SAFETY_STOCK - 1e-9).all())

    def test_perfect_forecast_saves_exactly_the_premium(self):
        # 예측이 정확하고 가격이 일정하면 조기경보는 프리미엄만큼만 싸야 한다
        short = config.INITIAL_STOCK - config.SAFETY_STOCK + 300  # 300 부족
        out = simulate.run_strategies(self.frame([0], [short], [short], [10], [10]))
        self.assertAlmostEqual(out["a_urgent"].iloc[0], 300)
        self.assertAlmostEqual(out["b_advance"].iloc[0], 300)
        self.assertEqual(out["b_urgent"].iloc[0], 0)
        self.assertAlmostEqual(out["a_cost"].iloc[0], out["b_cost"].iloc[0] * (1 + config.URGENT_PREMIUM))

    def test_missed_forecast_falls_back_to_urgent(self):
        short = config.INITIAL_STOCK - config.SAFETY_STOCK + 300
        out = simulate.run_strategies(self.frame([0], [short], [0], [10], [10]))  # 예측은 부족 없음
        self.assertEqual(out["b_alert"].iloc[0], 0)
        self.assertAlmostEqual(out["b_urgent"].iloc[0], 300)
        self.assertAlmostEqual(out["a_cost"].iloc[0], out["b_cost"].iloc[0])


if __name__ == "__main__":
    unittest.main()
