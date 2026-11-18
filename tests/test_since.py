"""lastSyncDate derived from start_date limits how much history OMRON sends."""

import datetime as dt

from omron_connect_mcp import server as s


def _ms(y, m, d):
    return int(dt.datetime(y, m, d, tzinfo=dt.timezone.utc).timestamp() * 1000)


def test_empty_start_means_all_history():
    assert s._since_ms("") == 0


def test_invalid_start_means_all_history():
    assert s._since_ms("yesterday") == 0


def test_start_date_minus_margin_at_utc_midnight():
    assert s.SYNC_MARGIN_DAYS == 3
    assert s._since_ms("2026-11-18") == _ms(2026, 11, 15)


def test_margin_crosses_month_boundary():
    assert s._since_ms("2026-12-02") == _ms(2026, 11, 29)


class _FakeClient:
    def __init__(self, rows_by_since):
        self.rows_by_since = rows_by_since
        self.calls = []

    def measurements(self, category, last_sync_date=0):
        self.calls.append(last_sync_date)
        return self.rows_by_since(last_sync_date)


def test_range_tools_pass_start_date_on(monkeypatch):
    fake = _FakeClient(lambda since: [])
    monkeypatch.setattr(s, "_get", lambda: fake)
    s.omron_weight(start_date="2026-11-18")
    s.omron_blood_pressure(start_date="2026-11-18")
    assert fake.calls == [_ms(2026, 11, 15), _ms(2026, 11, 15)]


def test_latest_uses_recent_window_first(monkeypatch):
    row = {"measured_at": "2026-11-18T07:00:00+09:00"}
    fake = _FakeClient(lambda since: [row] if since else [])
    monkeypatch.setattr(s, "_get", lambda: fake)
    out = s.omron_latest("scale")
    assert out["found"] and len(fake.calls) == 1 and fake.calls[0] > 0


def test_latest_falls_back_to_full_history(monkeypatch):
    row = {"measured_at": "2025-01-01T07:00:00+09:00"}
    fake = _FakeClient(lambda since: [] if since else [row])
    monkeypatch.setattr(s, "_get", lambda: fake)
    out = s.omron_latest("bpm")
    assert out["found"] and fake.calls[-1] == 0 and len(fake.calls) == 2
