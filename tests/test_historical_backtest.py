from __future__ import annotations

import pytest

from scripts.evaluation.run_historical_backtest import (
    HistoricalBacktestBlocked,
    run_historical_backtesting,
)


def test_historical_backtest_refuses_unsupported_ranking_evaluation():
    with pytest.raises(
        HistoricalBacktestBlocked,
        match="decision-time eligibility, candidate snapshots, and a valid outcome target",
    ):
        run_historical_backtesting()
