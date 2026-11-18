"""OMRON connect 的 MCP server（stdio）。"""

from __future__ import annotations

import datetime as _dt
import typing as T

from mcp.server.fastmcp import FastMCP

from .client import OmronConnectClient, OmronError

mcp = FastMCP("omron-connect")

_client: T.Optional[OmronConnectClient] = None


def _get() -> OmronConnectClient:
    global _client
    if _client is None:
        _client = OmronConnectClient()
        _client.connect()
    return _client


# OMRON's lastSyncDate (UTC epoch ms) limits how much history the server sends.
# Without it every call pages through the whole account history, which takes
# seconds and, together with a re-login, can exceed the client's timeout.
SYNC_MARGIN_DAYS = 3      # covers time zones and late uploads; rows are still filtered by date
LATEST_WINDOW_DAYS = 30   # omron_latest looks this far back first, then falls back to everything


def _since_ms(start_date: str) -> int:
    """lastSyncDate for a start date: midnight UTC SYNC_MARGIN_DAYS earlier; 0 = all history."""
    if not start_date:
        return 0
    try:
        day = _dt.date.fromisoformat(start_date)
    except ValueError:
        return 0
    day -= _dt.timedelta(days=SYNC_MARGIN_DAYS)
    return int(_dt.datetime.combine(day, _dt.time(), _dt.timezone.utc).timestamp() * 1000)


def _in_range(rows: T.List[dict], start: str, end: str) -> T.List[dict]:
    """用當地日期字串過濾。measured_at 已經是帶時區的 ISO 字串。"""
    return [r for r in rows if start <= r["measured_at"][:10] <= end]


def _today() -> str:
    return _dt.date.today().isoformat()


@mcp.tool()
def omron_status() -> dict:
    """確認 OMRON connect 連得上，並回報註冊了哪些裝置。"""
    try:
        devices = _get().devices()
        return {"connected": True, "device_count": len(devices), "devices": devices}
    except OmronError as exc:
        return {"connected": False, "error": str(exc)}


@mcp.tool()
def omron_list_devices() -> list[dict]:
    """列出這個 OMRON 帳號註冊過的裝置。"""
    return _get().devices()


@mcp.tool()
def omron_blood_pressure(start_date: str = "", end_date: str = "") -> dict:
    """取血壓紀錄。

    Args:
        start_date: 起始日 YYYY-MM-DD，留空代表不限。Set it whenever possible:
            without it the whole account history is downloaded, which is slow.
        end_date: 結束日 YYYY-MM-DD，留空代表今天。

    回傳每筆的 systolic、diastolic、pulse，以及 irregularHB、movementDetect、
    cuffWrapDetect 三個量測品質旗標。
    """
    rows = _get().measurements("bpm", _since_ms(start_date))
    rows = _in_range(rows, start_date or "0000-01-01", end_date or _today())
    return {"count": len(rows), "measurements": rows}


@mcp.tool()
def omron_weight(start_date: str = "", end_date: str = "") -> dict:
    """取體重與體組成紀錄（OMRON 體重計）。

    Args:
        start_date: 起始日 YYYY-MM-DD，留空代表不限。Set it whenever possible:
            without it the whole account history is downloaded, which is slow.
        end_date: 結束日 YYYY-MM-DD，留空代表今天。
    """
    rows = _get().measurements("scale", _since_ms(start_date))
    rows = _in_range(rows, start_date or "0000-01-01", end_date or _today())
    return {"count": len(rows), "measurements": rows}


@mcp.tool()
def omron_latest(category: str = "bpm") -> dict:
    """取最新一筆量測。

    Args:
        category: "bpm" 血壓，或 "scale" 體重。
    """
    if category not in ("bpm", "scale"):
        return {"error": "category 只接受 'bpm' 或 'scale'"}
    recent = (_dt.date.today() - _dt.timedelta(days=LATEST_WINDOW_DAYS)).isoformat()
    rows = _get().measurements(category, _since_ms(recent))  # type: ignore[arg-type]
    if not rows:  # nothing recent: look through the whole history once
        rows = _get().measurements(category)  # type: ignore[arg-type]
    if not rows:
        return {"found": False, "category": category}
    return {"found": True, "category": category, "measurement": rows[-1]}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
