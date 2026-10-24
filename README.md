# MoviePilot-Neo-Plugins

[MoviePilot NEO](https://github.com/4Nest/moviepilot-neo) 第三方插件库。

插件库地址（在 MoviePilot「设定 - 插件 - 插件市场」中添加）：

```
https://github.com/dibin666/MoviePilot-Neo-Plugins/
```

## 订阅日历 SubscribeCal

根据订阅生成追剧日历，可导入到设备日历，同时提供仪表盘时间轴与侧栏月历视图。

- **iCal 订阅**：在插件配置中复制订阅链接，添加到 iOS / macOS 日历、Outlook、Google Calendar 等；也可直接下载 `.ics` 文件。
- **侧栏月历**：启用后在主界面侧栏「订阅」分组显示「订阅日历」，按月查看每日播出，点击条目跳转媒体详情；窄屏自动切换为列表视图。也可在插件卡片「查看详情」中打开。
- **仪表盘**：横向时间轴展示近期播出，适配 NEO 网格仪表盘（自适应高度，编辑模式下可拖拽、调整尺寸）。
- **播出时间推算**：开启后根据订阅下载记录推算具体播出时刻，否则以全天事件显示。
- **数据来源**：优先使用 TMDB（支持剧集组），仅有 Bangumi 身份的订阅使用 Bangumi 放送数据；洗版订阅不生成日历。
- **自动更新**：订阅新增、调整、删除、完成时自动更新；另按设定周期（默认每 12 小时）全量刷新。

## 发布

插件在 `package.v2.json` 中声明 `"release": true`，NEO 会优先从 GitHub Release 安装：
Release 标签为 `SubscribeCal_v{版本号}`，资产为 `subscribecal_v{版本号}.zip`（压缩包根目录即插件文件）。
Release 不可用时自动回退为按文件列表安装。

## 开发

```bash
# 前端预览（http://localhost:5001，使用模拟数据）
./finalize-dist.sh dev frontend/subscribecal

# 构建前端并输出到 plugins.v2/subscribecal/dist
./finalize-dist.sh build frontend/subscribecal

# 后端单测（需要 moviepilot-neo 后端源码及其依赖）
MOVIEPILOT_BACKEND=/path/to/moviepilot-neo pytest tests
```
