import re

import yaml

from risk_tracker import DISCLAIMER
from risk_tracker.cli import main


def _cfg(tmp_path, **extra):
    cfg = {"paths": {"cache_dir": str(tmp_path / "cache"), "positions": str(tmp_path / "positions.csv"),
                     "reports_dir": str(tmp_path / "reports"), "charts_dir": str(tmp_path / "charts")},
           "history_years": 3, "bands": {"n_sims": 500}, "calibration": {"n_sims": 200, "step_days": 10}}
    cfg.update(extra)
    (tmp_path / "positions.csv").write_text(
        "ticker,buy_date,buy_price,shares,reason,what_would_prove_me_wrong,sell_rule\n"
        "AAPL,2025-06-02,200,2,test,test,limit\n")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def test_demo_report_end_to_end(tmp_path, capsys):
    assert main(["report", "--demo", "--config", str(_cfg(tmp_path))]) == 0
    out = capsys.readouterr().out
    reports = list((tmp_path / "reports").glob("*.md"))
    assert len(reports) == 1
    text = reports[0].read_text()
    assert text.rstrip().endswith(f"*{DISCLAIMER}*")
    assert out.rstrip().endswith(DISCLAIMER)
    assert "SYNTHETIC" in text and "Historical ranges, not predictions" in text
    assert {p.name for p in (tmp_path / "charts").rglob("*.png")} >= {
        "VT_bands.png", "AAPL_bands.png", "VT_volatility.png", "calibration.png"}
    # no trading signals or directional calls anywhere in the output
    for phrase in ["buy signal", "sell signal", "strong buy", "you should buy", "you should sell",
                   "will rise", "will fall", "price target"]:
        assert phrase not in text.lower() and phrase not in out.lower()


def test_no_network_and_no_cache_fails_gracefully(tmp_path, capsys):
    rc = main(["report", "--offline", "--config", str(_cfg(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 1
    assert "No price data" in out and DISCLAIMER in out
