# omron-connect-mcp

把 OMRON connect 的血壓與體重資料接進 MCP client 的 server。

## 這個專案解決什麼

OMRON 沒有公開的自助式 API，`omron connect` 的資料只能從 App 看。社群工具
[omramin](https://github.com/bugficks/omramin) 可以把資料同步到 Garmin Connect，
但它走的 `measureData` 端點在部分帳號上一律回 `deviceModelList: null`，抓不到任何東西。

這裡改打 `synchronizeMeasureData`。那是 OMRON connect App 自己在用的端點，
端點名稱取自 App 的 dex 字串。帶 `lastSyncDate` 就會把該時間點之後的所有量測吐回來。

實測差異（同一個帳號、同一組憑證，HEM-7600T）：

| 端點 | 結果 |
|---|---|
| `measureData`（omramin 用的） | 0 筆 |
| `synchronizeMeasureData` | 340 筆，最早 2022-02 |

## 為什麼 omramin 抓不到

兩個獨立的原因：

1. **端點。** `measureData` 對某些帳號不回資料。試過 30 天到 400 天、user 0 到 4、
   帶 serial 與不帶 serial、加上 `deviceModel`，全部回 null。
2. **序號推導。** `ble_mac_to_serial()` 從 BLE MAC 反推的 deviceSerialID
   跟伺服器記錄的不一定一樣。實測 MAC `b2:ff:fe:af:29:d8` 推出
   `d829affefffeffb2`，伺服器上是 `d829affeffb2ff28`，後 6 碼不同。

`synchronizeMeasureData` 不需要 serial 也不需要 user number，兩個問題都繞開了。

## 安裝

```bash
uv pip install git+https://github.com/aircon-chen/omron-connect-mcp.git
```

## 設定

三個環境變數：

```bash
export OMRON_EMAIL="you@example.com"
export OMRON_PASSWORD="..."
export OMRON_COUNTRY="TW"     # ISO 3166-1 alpha-2
```

`OMRON_COUNTRY` 決定連哪個區域的伺服器。目前支援的區域由 omramin 的
`regionserver` 決定，台灣、日本、香港都對應 `data-jp`。

登入後的 refresh token 會存在 `$XDG_STATE_HOME/omron-connect-mcp/token.json`
（預設 `~/.local/state/...`，權限 600），之後啟動優先用它，失敗才用帳密重登。
要換位置就設 `OMRON_TOKEN_FILE`。

### MCP client 設定

```json
{
  "mcpServers": {
    "omron-connect": {
      "command": "omron-connect-mcp",
      "env": {
        "OMRON_EMAIL": "you@example.com",
        "OMRON_PASSWORD": "...",
        "OMRON_COUNTRY": "TW"
      }
    }
  }
}
```

## 工具

| 工具 | 說明 |
|---|---|
| `omron_status` | 確認連得上，回報註冊了幾台裝置 |
| `omron_list_devices` | 列出帳號底下的裝置 |
| `omron_blood_pressure` | 取血壓，可給 `start_date` / `end_date`（YYYY-MM-DD） |
| `omron_weight` | 取體重與體組成 |
| `omron_latest` | 取最新一筆，`category` 填 `bpm` 或 `scale` |

血壓每筆包含：

```json
{
  "measured_at": "2026-09-27T23:00:27+08:00",
  "epoch_ms": 1790521227000,
  "timezone": "Asia/Taipei",
  "device_model": "HEM-7600T",
  "user": 1,
  "systolic": 98,
  "diastolic": 62,
  "pulse": 76,
  "irregularHB": false,
  "movementDetect": false,
  "cuffWrapDetect": false
}
```

體重的欄位是 `weight`、`bmiValue`、`bodyFatPercentage`、`skeletalMusclePercentage`、
`visceralFatLevel`、`restingMetabolism`、`metabolicAge`。

## 限制

- **只支援 OMRON connect 有的資料。** 量測結果要先從裝置同步到 App，
  留在機器記憶體裡的讀不到。
- **體重那條沒有實機驗證過。** 解析沿用 omramin 的 `_process_scale_measurements`，
  邏輯是它的，但作者手上只有血壓計。有 OMRON 體重計的話歡迎回報。
- **`syncList` 的 `deviceCategory` 欄位實測是 `None`**，所以分類是看
  `bodyIndexList` 裡有沒有血壓專屬的欄位代碼，不是看它自己標的類別。
- 沒有做增量快取。每次查詢都會抓完整歷史再過濾。資料量大的帳號會慢。

## 開發

```bash
uv venv && uv pip install -e . pytest
.venv/bin/pytest
```

測試不需要帳號。`tests/fixtures/sync_bpm.json` 是去識別化過的真實回應，
序號與帳號資訊都換掉了。

## 授權與致謝

GPL-2.0-only。

認證流程與 `bodyIndexList` 的欄位解析直接沿用
[omramin](https://github.com/bugficks/omramin) 的 `omronconnect` 模組，
那份是 GPLv2，所以這裡也是。這個專案的貢獻是換掉抓資料的端點，
以及包成 MCP server。
