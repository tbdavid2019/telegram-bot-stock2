"""Offline smoke tests for quantitative-analysis helpers.

Run with ``python3 -m unittest tests/test_stock_analysis.py`` after installing
``requirements.txt``. Network-backed tools are intentionally not exercised.
"""

import unittest

import numpy as np
import pandas as pd

from tools.stock_analysis import _flatten_columns, _vcp_diagnostic


class StockAnalysisHelperTests(unittest.TestCase):
    def test_flatten_columns(self):
        frame = pd.DataFrame([[1, 2]], columns=pd.MultiIndex.from_tuples([("Close", "TSLA"), ("Volume", "TSLA")]))
        flattened = _flatten_columns(frame)
        self.assertEqual(list(flattened.columns), ["Close", "Volume"])

    def test_vcp_diagnostic_returns_expected_fields(self):
        index = pd.date_range("2025-01-01", periods=240)
        close = pd.Series(np.linspace(100, 160, len(index)), index=index)
        frame = pd.DataFrame(
            {"Close": close, "High": close * 1.01, "Low": close * 0.99, "Volume": 100_000},
            index=index,
        )
        result = _vcp_diagnostic(frame)
        self.assertIn("detected", result)
        self.assertIn("range_contraction_ratios", result)
        self.assertIsInstance(result["detected"], bool)


if __name__ == "__main__":
    unittest.main()
