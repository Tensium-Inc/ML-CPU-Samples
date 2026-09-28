from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config, features, register, serve  # noqa: E402

CFG = config.load()


def _batch(rows: int | None = 400) -> pd.DataFrame:
    frame = pd.read_csv(ROOT / CFG["paths"]["serving_batch"], low_memory=False)
    return frame if rows is None else frame.head(rows)


class TestConfig(unittest.TestCase):
    def test_policy_carries_every_required_key(self):
        self.assertEqual(config.missing_keys(CFG), [])


class TestRegister(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch = _batch()
        cls.reg = register.registers(cls.batch, CFG)

    def test_long_form_columns(self):
        self.assertEqual(list(self.reg.columns), ["encounter_id", "code"])

    def test_codes_are_distinct_per_encounter(self):
        self.assertFalse(self.reg.duplicated().any())

    def test_registers_belong_to_the_batch(self):
        self.assertTrue(set(self.reg["encounter_id"])
                        <= set(self.batch["encounter_id"].astype("int64")))

    def test_sizes_match_the_long_form(self):
        sizes = register.sizes(features.prepare(self.batch), CFG).sort_index()
        counted = (self.reg.groupby("encounter_id")["code"].size()
                   .reindex(sizes.index).fillna(0).astype(float))
        self.assertTrue((sizes.values == counted.values).all())


class TestFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = features.build_features(_batch(), CFG)

    def test_columns_are_the_contract(self):
        self.assertEqual(list(self.frame.columns), features.FEATURE_COLUMNS)

    def test_no_missing_values(self):
        self.assertFalse(self.frame.isna().any().any(), "feature frame has NaNs")

    def test_features_are_numeric_and_finite(self):
        self.assertTrue(all(pd.api.types.is_numeric_dtype(t) for t in self.frame.dtypes))
        self.assertTrue((self.frame.abs() < 1e6).all().all())

    def test_serving_frame_matches_training_columns(self):
        frame = serve.build_serving_frame(_batch(), CFG)
        self.assertEqual(list(frame.columns), features.FEATURE_COLUMNS)


class TestScoringContract(unittest.TestCase):
    def test_score_batch_writes_the_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "batch.csv"
            _batch(300).to_csv(batch, index=False)
            out = Path(tmp) / "scores.csv"
            proc = subprocess.run(
                [sys.executable, "scripts/score_batch.py", "--batch", str(batch),
                 "--out", str(out)],
                cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            scores = pd.read_csv(out)
            self.assertEqual(list(scores.columns), list(CFG["scoring"]["output_columns"]))
            self.assertTrue(scores["score"].between(0.0, 1.0).all())
            self.assertGreater(scores["score"].std(), 0.0, "scores are constant")


if __name__ == "__main__":
    unittest.main()
