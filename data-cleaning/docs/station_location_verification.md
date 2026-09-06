# 站点坐标核验与正式地图开放流程

状态：流程生效（2026-09-06 建立）；当前已核验站点数 **0/79**，正式地图点位尚未开放。

## 1. 背景与现状

MEE 国控断面实时接口不返回经纬度。当前坐标全部来自旧竞品项目注册表
（`taihugurad/data/stations.json`，经合并注册表 `config/data_factory/stations.json` 接入），
**全部为 `metadata_only`（注册表元数据），未经官方核验，不构成地图点位证据**。

复核工作表：`reports/station_coordinate_review_20260906.csv`（79 行，每站一行）。

现状分布（2026-09-06）：

| location_status | 数量 | 说明 |
|---|---:|---|
| verified | 0 | 官方坐标核验通过，可作正式地图点 |
| metadata_only | 48 | 注册表坐标（amap_geocode 47 / existing 3），页面临时以"位置待核验"口径显示 |
| suspicious | 8 | 多站共用同一坐标（coord_source=fallback 占位），必须重新取坐标 |
| missing | 23 | 无坐标（均为湖界外河道/河口站），MEE 接口不提供，待补登记 |

## 2. 复核表填写规范

每行填写：

- `official_lon` / `official_lat`：**官方来源坐标**（WGS84，小数度）。可接受来源：
  1. 生态环境部公开发布的国控断面位置文件（公告附件/批复文件）；
  2. 站点主管单位（监测中心/水文总站）出具的位置说明；
  3. 现场手持 GPS 测量记录（需照片+时间）。
  高德/百度的地理编码结果只能作为"待核验"参考，不能直接填为 official。
- `official_source`：来源描述 + 文件名/链接（存入 `storage/manifests/authorizations/station_locations/`）。
- `review_result`：`verified` / `rejected`（坐标错误，维持 metadata_only 或修正注册表坐标）。
- `reviewer` / `review_date`：双人复核时填两人。

## 3. 核验通过后如何生效（逐站开放）

1. 在 `config/data_factory/stations.json` 对应站点条目增加字段：
   ```json
   {"name": "拖山", "lon": 120.2156, "lat": 31.3422,
    "location_status": "verified", "verified_by": "姓名", "verified_at": "2026-09-XX",
    "evidence": "storage/manifests/authorizations/station_locations/xxx.pdf"}
   ```
2. 重建目录（幂等，不影响采集）：
   ```powershell
   cd data-cleaning; python -m data_factory build-mee-catalog
   ```
3. API `GET /api/v1/spatial-entities?mode=observed` 中该站 `location.location_status`
   自动变为 `verified`（`load_station_locations` 显式 verified 优先，且不会被共用坐标降级）。
4. 前端（`src/services/realtime.js::stationMapPoints`）对 verified 站：
   - 点位名称不再追加"（位置待核验）"后缀；
   - `suspicious/missing` 站永远不出现在地图（列表可见）。
5. 大屏 `/wallboard` 的"已核验坐标"计数随之增长。

## 4. 红线

- 任何未经 `location_status=verified` 的坐标不得用于：正式地图点位、空间插值、
  湖区网格归属判断（grid 映射另有 `station_grid_mapping.csv` 口径）。
- 共用坐标（suspicious）的 8 站在重新取坐标前禁止互相"参考"坐标。
- 前端禁止恢复任何形式的"百分比位置 → 经纬度"模拟换算（已从站点页移除）。
