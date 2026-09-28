from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import channels, features, serve  # noqa: E402

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
WINDOW = int(CFG["alerting"]["rolling_window_hours"])


def _batch():
    return channels.read_log(ROOT / CFG["paths"]["current_batch"])


class TestFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = features.build_features(_batch(), WINDOW)

    def test_columns_are_the_contract(self):
        self.assertEqual(list(self.frame.columns), features.FEATURE_COLUMNS)

    def test_indexed_by_hour_and_unique(self):
        self.assertTrue(self.frame.index.is_unique)
        self.assertGreater(len(self.frame), 100)

    def test_hour_of_day_is_sane(self):
        self.assertTrue(self.frame["hour_of_day"].between(0, 23).all())

    def test_rollups_are_finite(self):
        rolls = self.frame[["rollup_24h", "rollup_6h"]].dropna()
        self.assertGreater(len(rolls), 0)
        self.assertTrue((rolls.abs() < 1e6).all().all())


class TestServing(unittest.TestCase):
    def test_serving_frame_matches_training_columns(self):
        frame = serve.build_serving_frame(_batch(), WINDOW)
        self.assertEqual(list(frame.columns), features.FEATURE_COLUMNS)
        self.assertGreater(len(frame), 100)


class TestContract(unittest.TestCase):
    def test_score_hours_writes_the_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "alerts.csv"
            proc = subprocess.run(
                [sys.executable, "scripts/score_hours.py",
                 "--batch", str(ROOT / CFG["paths"]["current_batch"]), "--out", str(out)],
                cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            alerts = pd.read_csv(out)
            self.assertEqual(list(alerts.columns),
                             ["timestamp", "alert_probability", "rollup_24h"])
            self.assertTrue(alerts["alert_probability"].between(0, 1).all())
            self.assertGreater(alerts["alert_probability"].std(), 0.0)


if __name__ == "__main__":
    unittest.main()
