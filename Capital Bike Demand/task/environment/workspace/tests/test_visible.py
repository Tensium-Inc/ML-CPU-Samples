from __future__ import annotations

import unittest

import pandas as pd

from pipeline.features import make_features


class VisibleContractTests(unittest.TestCase):
    def test_feature_contract_excludes_outcomes(self) -> None:
        frame = pd.DataFrame(
            {
                "season": [1],
                "yr": [1],
                "mnth": [4],
                "hr": [8],
                "holiday": [0],
                "weekday": [1],
                "workingday": [1],
                "weathersit": [1],
                "temp": [0.5],
                "atemp": [0.5],
                "hum": [0.4],
                "windspeed": [0.2],
                "dteday": [pd.Timestamp("2012-04-01")],
                "instant": [1],
            }
        )
        matrix = make_features(frame)
        self.assertEqual(len(matrix), 1)
        self.assertFalse({"cnt", "casual", "registered"}.intersection(matrix.columns))
        self.assertTrue(all(pd.api.types.is_numeric_dtype(matrix[name]) for name in matrix))


if __name__ == "__main__":
    unittest.main()
