import json
import re

import pytest
import yaml

from risk_tracker.cli import main
from risk_tracker.web import build_site, decrypt, encrypt


def test_encrypt_round_trip_and_wrong_password():
    payload = encrypt("<p>secret journal</p>", "correct horse battery", iterations=1000)
    assert "secret" not in json.dumps(payload)
    assert decrypt(payload, "correct horse battery") == "<p>secret journal</p>"
    with pytest.raises(Exception):
        decrypt(payload, "wrong password here")


def test_fresh_salt_and_iv_each_time():
    a, b = encrypt("x", "pw-pw-pw-pw-pw", 1000), encrypt("x", "pw-pw-pw-pw-pw", 1000)
    assert a["salt"] != b["salt"] and a["iv"] != b["iv"]


def _payload(html):
    return json.loads(re.search(r"const PAYLOAD = (.*?);\n", html).group(1))


def test_site_hides_content_and_ships_phone_files(tmp_path):
    views = '<div class="view" data-view="today"><p>My secret thesis</p></div>'
    page = build_site(views, tmp_path, "a-long-password-123")
    html = page.read_text()
    assert "secret thesis" not in html
    assert "not financial advice" in html            # disclaimer visible even while locked
    assert "backdrop-filter" in html and 'class="ambient"' in html   # shared Liquid Glass theme
    assert decrypt(_payload(html), "a-long-password-123") == views
    for f in ("manifest.webmanifest", "icon-180.png", "icon-512.png", ".nojekyll"):
        assert (tmp_path / f).exists()
    assert 'name="apple-mobile-web-app-capable"' in html


def test_public_site_is_plain(tmp_path):
    html = build_site('<div class="view" data-view="today">hello</div>', tmp_path, None).read_text()
    assert "hello" in html and "const PAYLOAD = null;" in html


def test_web_formatting_never_shows_negative_zero():
    from risk_tracker.web import _move, _tone
    assert _move(-0.00001) == "0.0%" and _tone(-0.00001) == ""
    assert _move(-0.02) == "-2.0%" and _tone(-0.02) == "danger"


def _cfg(tmp_path):
    cfg = {"paths": {"cache_dir": str(tmp_path / "c"), "positions": str(tmp_path / "positions.csv"),
                     "reports_dir": str(tmp_path / "r"), "charts_dir": str(tmp_path / "ch")},
           "history_years": 3, "bands": {"n_sims": 300}, "calibration": {"n_sims": 100, "step_days": 20}}
    (tmp_path / "positions.csv").write_text(
        "ticker,buy_date,buy_price,shares,reason,what_would_prove_me_wrong,sell_rule\n"
        "AAPL,2025-06-02,200,2,private-reason-xyz,test,limit\n")
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return str(p)


def test_cli_refuses_site_without_password(tmp_path, monkeypatch):
    monkeypatch.delenv("SITE_PASSWORD", raising=False)
    assert main(["report", "--demo", "--config", _cfg(tmp_path), "--site", str(tmp_path / "s")]) == 2
    monkeypatch.setenv("SITE_PASSWORD", "short")
    assert main(["report", "--demo", "--config", _cfg(tmp_path), "--site", str(tmp_path / "s")]) == 2


def test_cli_builds_encrypted_site(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_PASSWORD", "a-long-password-123")
    assert main(["report", "--demo", "--no-calibration", "--config", _cfg(tmp_path),
                 "--site", str(tmp_path / "s")]) == 0
    html = (tmp_path / "s" / "index.html").read_text()
    assert "private-reason-xyz" not in html
    body = decrypt(_payload(html), "a-long-password-123")
    assert "private-reason-xyz" in body and "Your money today" in body
    assert {f'data-view="{v}"' in body for v in ("today", "holdings", "market", "history")} == {True}
    assert body.count("data:image/png;base64,") >= 4  # light + dark charts travel inside the encrypted page


def test_public_site_allowed_only_without_journal(tmp_path, monkeypatch):
    monkeypatch.delenv("SITE_PASSWORD", raising=False)
    cfg = _cfg(tmp_path)                                  # writes a journal with a trade
    args = ["report", "--no-calibration", "--config", cfg, "--site", str(tmp_path / "s"), "--public", "--demo"]
    assert main(args) == 2                                # journal present -> refuse
    assert not (tmp_path / "s" / "index.html").exists()
    (tmp_path / "positions.csv").unlink()
    assert main(args) == 0                                # market-only page is fine
    html = (tmp_path / "s" / "index.html").read_text()
    assert "const PAYLOAD = null;" in html and "volatility" in html and "No journal yet" in html
