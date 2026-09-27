"""解析邏輯的離線測試。fixture 是去識別化過的真實回應。"""

import json
import pathlib

import omronconnect as oc
import pytest

from omron_connect_mcp.client import parse_sync_list

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "sync_bpm.json"


@pytest.fixture
def sync_list():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def parser():
    # 只用它的解析方法。建構子會去查該 server 的 AppID/AppKey，所以要給真實的
    # region URL，但整個測試不會發出任何請求，也不需要帳號。
    return oc.OmronConnect1("https://data-jp.omronconnect.com/api", "TW")


def test_parses_every_measurement(sync_list, parser):
    rows = parse_sync_list(sync_list, "bpm", parser=parser)
    assert len(rows) == 3


def test_values_are_plausible(sync_list, parser):
    for row in parse_sync_list(sync_list, "bpm", parser=parser):
        assert 70 <= row["systolic"] <= 260
        assert 30 <= row["diastolic"] < row["systolic"]
        assert 30 <= row["pulse"] <= 220


def test_rows_are_sorted_and_timezone_aware(sync_list, parser):
    rows = parse_sync_list(sync_list, "bpm", parser=parser)
    stamps = [r["measured_at"] for r in rows]
    assert stamps == sorted(stamps)
    assert all(r["timezone"] == "Asia/Taipei" for r in rows)
    assert all("+08:00" in r["measured_at"] for r in rows)


def test_quality_flags_present(sync_list, parser):
    row = parse_sync_list(sync_list, "bpm", parser=parser)[0]
    for flag in ("irregularHB", "movementDetect", "cuffWrapDetect"):
        assert isinstance(row[flag], bool)


def test_deleted_measurements_are_dropped(sync_list, parser):
    marked = json.loads(json.dumps(sync_list))
    devices = marked[0]["deviceCategoryList"][0]["deviceModelList"][0]["deviceSerialIDList"][0]
    devices["measureList"][0]["deleteFlag"] = 1
    assert len(parse_sync_list(marked, "bpm", parser=parser)) == 2


def test_scale_query_skips_bpm_records(sync_list, parser):
    # syncList 的 deviceCategory 是 None，分類只能靠 bodyIndexList 的欄位。
    assert parse_sync_list(sync_list, "scale", parser=parser) == []
