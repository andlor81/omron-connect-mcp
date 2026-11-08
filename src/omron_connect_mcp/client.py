"""OMRON connect 資料存取。

為什麼不直接用 omramin 的 `get_measurements()`：它打 `measureData` 端點，
實測在部分帳號上一律回 `deviceModelList: null`，而且它從 BLE MAC 反推的
deviceSerialID 跟伺服器記錄的不一定一樣。

這裡改打 `synchronizeMeasureData`，那是 OMRON connect App 自己在用的端點
（端點名稱取自 App 的 dex 字串）。它帶 `lastSyncDate` 就會把該時間點之後的
所有測量吐回來，不需要 serial 也不需要 user number，所以上面兩個問題都不會發生。

認證與 bodyIndexList 的欄位解析沿用 omramin 的 `omronconnect`，沒有重寫。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
import typing as T

import omronconnect as _oc

SYNC_ENDPOINT = "synchronizeMeasureData"

Category = T.Literal["bpm", "scale"]

_CATEGORY = {
    "bpm": _oc.DeviceCategory.BPM,
    "scale": _oc.DeviceCategory.SCALE,
}


class OmronError(RuntimeError):
    pass


@dataclasses.dataclass
class Credentials:
    email: str
    country: str
    password: str = ""

    @classmethod
    def from_env(cls) -> "Credentials":
        """密碼是選用的。已經有可用的 refresh token 時不需要它，
        這樣 MCP client 的設定檔裡可以不放密碼。"""
        email = os.environ.get("OMRON_EMAIL", "").strip()
        country = os.environ.get("OMRON_COUNTRY", "").strip().upper()
        missing = [n for n, v in (("OMRON_EMAIL", email), ("OMRON_COUNTRY", country)) if not v]
        if missing:
            raise OmronError("缺少環境變數：" + ", ".join(missing))
        return cls(email, country, os.environ.get("OMRON_PASSWORD", "").strip())


def _token_path() -> str:
    override = os.environ.get("OMRON_TOKEN_FILE")
    if override:
        return override
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "omron-connect-mcp", "token.json")


def _read_token() -> str:
    try:
        with open(_token_path(), encoding="utf-8") as fh:
            return json.load(fh).get("refresh_token", "")
    except (OSError, ValueError):
        return ""


def _write_token(refresh_token: str) -> None:
    path = _token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"refresh_token": refresh_token}, fh)
    os.chmod(path, 0o600)


class OmronConnectClient:
    """薄封裝：登入、抓同步資料、解析成 dict。"""

    def __init__(self, creds: T.Optional[Credentials] = None) -> None:
        self._creds = creds or Credentials.from_env()
        self._client: T.Optional[_oc.OmronClient] = None

    # --- 認證 -------------------------------------------------------------

    def connect(self) -> None:
        """先用快取的 refresh token，失敗才用帳密重登。"""
        client = _oc.OmronClient(self._creds.country)
        cached = _read_token()
        if cached:
            try:
                new_token = client.refresh_oauth2(cached)
                if new_token:
                    _write_token(new_token)
                    self._client = client
                    return
            except Exception:  # noqa: BLE001 - 壞掉的 token 就重登，不用細分原因
                pass

        if not self._creds.password:
            raise OmronError(
                "沒有可用的 refresh token，而且沒有設 OMRON_PASSWORD。"
                "第一次連線需要密碼。")
        token = client.login(self._creds.email, self._creds.password)
        if not token:
            raise OmronError("OMRON 登入失敗，檢查 email、密碼與 OMRON_COUNTRY")
        _write_token(token)
        self._client = client

    @property
    def _active(self):
        if self._client is None:
            self.connect()
        active = getattr(self._client, "_active_client", None)
        if active is None:
            raise OmronError("尚未連線")
        return active

    # --- 資料 -------------------------------------------------------------

    def devices(self) -> T.List[T.Dict[str, T.Any]]:
        if self._client is None:
            self.connect()
        found = self._client.get_registered_devices(None) or []
        return [{"name": d.name, "category": str(d.category), "macaddr": d.macaddr,
                 "serial": d.serial, "user": d.user} for d in found]

    def raw_sync(self, last_sync_date: int = 0) -> T.List[T.Dict[str, T.Any]]:
        """呼叫 synchronizeMeasureData，回傳未解析的 syncList。"""
        # 伺服器會分頁回傳：每頁帶 nextPaginationKey，要一直抓到沒有下一頁為止，
        # 否則只會拿到最舊的一頁（跟 omramin 的 synchronizeDeviceConfData 同樣做法）。
        active = self._active
        key = int(last_sync_date)
        out: T.List[T.Dict[str, T.Any]] = []
        for _ in range(500):  # 安全上限，避免伺服器回同一個 key 時無限迴圈
            response = active._client.post(
                f"{active._server}{active._APP_URL}/versions/current/{SYNC_ENDPOINT}",
                json={"lastSyncDate": key, "countOnlyFlag": 0},
                headers=active._headers, timeout=60,
            )
            response.raise_for_status()
            payload = response.json().get("returnedValue") or {}
            out.extend(payload.get("syncList") or [])
            next_key = int(payload.get("nextPaginationKey") or 0)
            if not next_key or next_key == key:
                break
            key = next_key
        return out

    def measurements(self, category: Category = "bpm",
                     last_sync_date: int = 0) -> T.List[T.Dict[str, T.Any]]:
        return parse_sync_list(self.raw_sync(last_sync_date), category,
                               parser=self._active)


# --- 解析 -----------------------------------------------------------------

def parse_sync_list(sync_list: T.Iterable[T.Dict[str, T.Any]],
                    category: Category = "bpm",
                    parser: T.Any = None) -> T.List[T.Dict[str, T.Any]]:
    """把 syncList 攤平成一筆一筆的量測。

    `parser` 是 omronconnect 的 OmronConnect 實例，用它的
    `_process_bpm_measurements` / `_process_scale_measurements`，
    這樣 bodyIndexList 的欄位對照跟單位換算不用自己重寫一份。
    """
    want = _CATEGORY[category]
    out: T.List[T.Dict[str, T.Any]] = []

    for record in sync_list:
        for cat in record.get("deviceCategoryList") or []:
            for model in cat.get("deviceModelList") or []:
                for dev in model.get("deviceSerialIDList") or []:
                    measure_list = [m for m in (dev.get("measureList") or [])
                                    if not m.get("deleteFlag")]
                    if not measure_list:
                        continue
                    if not _looks_like(measure_list[0], want):
                        continue
                    payload = dict(dev, measureList=measure_list)
                    if want is _oc.DeviceCategory.BPM:
                        items = parser._process_bpm_measurements(payload)
                    else:
                        items = parser._process_scale_measurements(payload)
                    for item in items:
                        out.append(_to_dict(item, model.get("deviceModel"),
                                            dev.get("userNumberInDevice")))

    out.sort(key=lambda r: r["measured_at"])
    return out


def _looks_like(measure: T.Dict[str, T.Any], want) -> bool:
    """用 bodyIndexList 出現的欄位判斷類別。

    syncList 的 deviceCategory 欄位在實測回應裡是 None，不能拿來分類，
    所以改看有沒有血壓專屬的欄位代碼。
    """
    keys = set((measure.get("bodyIndexList") or {}).keys())
    is_bpm = {str(int(_oc.ValueType.MMHG_MAX_FIGURE)), str(int(_oc.ValueType.MMHG_MIN_FIGURE))} <= keys
    return is_bpm if want is _oc.DeviceCategory.BPM else not is_bpm


def _to_dict(item: T.Any, model: T.Optional[str], user: T.Any) -> T.Dict[str, T.Any]:
    tz = item.timeZone
    moment = _dt.datetime.fromtimestamp(item.measurementDate / 1000, _dt.timezone.utc).astimezone(tz)
    row: T.Dict[str, T.Any] = {
        "measured_at": moment.isoformat(timespec="seconds"),
        "epoch_ms": item.measurementDate,
        "timezone": str(tz),
        "device_model": model,
        "user": user,
    }
    for field in dataclasses.fields(item):
        if field.name in ("measurementDate", "timeZone"):
            continue
        row[field.name] = getattr(item, field.name)
    return row
