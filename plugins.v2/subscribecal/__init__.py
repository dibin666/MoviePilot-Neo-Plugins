import datetime
import re
import statistics
import threading
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Response
from pydantic import BaseModel

from app import schemas
from app.core.cache import Cache, fresh
from app.core.config import settings
from app.core.event import Event, eventmanager
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.db.models.subscribe import Subscribe
from app.db.subscribe_oper import SubscribeOper
from app.log import logger
from app.modules.themoviedb.tmdbapi import TmdbApi
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaType
from app.utils.http import RequestUtils

# 剧集信息缓存（TMDB / Bangumi 查询结果）
result_cache = Cache(maxsize=1000, ttl=3600 * 12)

# Bangumi 公共接口
BANGUMI_API_BASE = "https://api.bgm.tv"

# 日历 UTC 时间格式
ICS_DATETIME_FORMAT = "%Y%m%dT%H%M%SZ"

# 影响日历数据的订阅字段，修改后需要重新生成事件
SUBSCRIBE_CALENDAR_FIELDS = (
    "tmdbid", "bangumiid", "doubanid", "media_source", "media_id",
    "season", "year", "name", "type", "episode_group", "best_version",
)


def get_tz() -> datetime.tzinfo:
    """获取系统配置的本地时区，配置无效时回退到 Asia/Shanghai。"""
    try:
        return pytz.timezone(settings.TZ)
    except Exception:
        return pytz.timezone("Asia/Shanghai")


def parse_utc(value: Optional[str]) -> Optional[datetime.datetime]:
    """解析 `YYYYMMDDTHHMMSSZ` 格式的 UTC 时间字符串。"""
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, ICS_DATETIME_FORMAT).replace(tzinfo=pytz.utc)
    except (TypeError, ValueError):
        return None


def parse_date(value: Optional[str]) -> Optional[datetime.date]:
    """解析 `YYYY-MM-DD` 格式的日期字符串，非法时返回 None。"""
    if not value:
        return None
    try:
        return datetime.datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def ics_escape(text: Optional[str]) -> str:
    """按 RFC 5545 转义 TEXT 类型的属性值。"""
    if not text:
        return ""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def ics_fold(line: str) -> str:
    """按 RFC 5545 以 75 字节折行，避免截断 UTF-8 多字节字符。"""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts: List[str] = []
    current = ""
    current_size = 0
    limit = 75
    for char in line:
        char_size = len(char.encode("utf-8"))
        if current_size + char_size > limit:
            parts.append(current)
            current = char
            current_size = char_size
            # 续行以一个空格开头，占用 1 字节
            limit = 74
        else:
            current += char
            current_size += char_size
    if current:
        parts.append(current)
    return "\r\n ".join(parts)


class CalendarInfo:
    """日历数据源中的单集/单部影片信息。"""

    # 播出日期（YYYY-MM-DD）
    air_date: Optional[str] = None
    # 集号（剧集组下已按组内顺序重排）
    episode_number: Optional[int] = None
    # 集类型
    episode_type: Optional[str] = None
    # 季/电影标题
    title: Optional[str] = None
    # 集标题
    name: Optional[str] = None
    # 数据源唯一 ID
    id: Optional[Union[int, str]] = None
    # 简介
    overview: Optional[str] = None
    # 时长（分钟）
    runtime: Optional[int] = None
    # 季号
    season_number: Optional[int] = None

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            if key in self.__class__.__annotations__:
                setattr(self, key, value)
        if not self.air_date:
            self.air_date = kwargs.get("release_date") or kwargs.get("airdate") or None

    def utc_airdate(self, delay_minutes: Optional[float] = None) -> str:
        """以本地播出日 00:00 为基准，偏移指定分钟后转为 UTC 时间字符串。"""
        local_dt = datetime.datetime.strptime(self.air_date, "%Y-%m-%d") + datetime.timedelta(
            minutes=delay_minutes or 0)
        return get_tz().localize(local_dt).astimezone(pytz.utc).strftime(ICS_DATETIME_FORMAT)


class CalendarEvent(BaseModel):
    """日历事件，持久化到插件数据中并用于生成 ICS。"""

    # 创建时间
    created: Optional[str] = None
    # 开始时间（UTC）
    dtstart: Optional[str] = None
    # 结束时间（UTC）
    dtend: Optional[str] = None
    # 是否为全天事件（播出时间未知）
    all_day: bool = False
    # 本地播出日期（YYYY-MM-DD）
    air_date: Optional[str] = None
    # 标题
    summary: Optional[str] = None
    # 集标题
    episode_name: Optional[str] = None
    # 描述（备注）
    description: Optional[str] = None
    # 季
    season: Optional[int] = None
    # 集
    episode: Optional[int] = None
    # 总集数
    total_episodes: Optional[int] = None
    # 地点
    location: Optional[str] = None
    # 唯一标识
    uid: Optional[str] = None
    # 类型
    transp: str = "TRANSPARENT"
    # 序号
    sequence: int = 0
    # 状态
    status: str = "CONFIRMED"
    # 最后修改时间
    last_modified: Optional[str] = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.uid is None:
            self.uid = str(uuid.uuid4())
            self.created = self.utc_now()

    @staticmethod
    def utc_now() -> str:
        """当前 UTC 时间字符串。"""
        return datetime.datetime.now(pytz.utc).strftime(ICS_DATETIME_FORMAT)

    def __setattr__(self, name, value):
        if name in self.__dict__ and self.__dict__[name] == value:
            return
        super().__setattr__(name, value)
        if name not in ("last_modified", "sequence"):
            super().__setattr__("last_modified", self.utc_now())

    def local_date(self) -> Optional[datetime.date]:
        """事件在本地时区下的日期。"""
        if self.all_day and self.air_date:
            return parse_date(self.air_date)
        start = parse_utc(self.dtstart)
        if start:
            return start.astimezone(get_tz()).date()
        return parse_date(self.air_date)

    @staticmethod
    def ics_header(calname: str = "追剧日历") -> List[str]:
        """日历头部。"""
        return [
            "BEGIN:VCALENDAR",
            "PRODID:-//dibin666//MoviePilot SubscribeCal 2.0//CN",
            "VERSION:2.0",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{ics_escape(calname)}",
            f"X-WR-TIMEZONE:{settings.TZ}",
            "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
            "X-PUBLISHED-TTL:PT6H",
        ]

    def to_ics_lines(self) -> List[str]:
        """转换为 VEVENT 文本行。"""
        lines = ["BEGIN:VEVENT", f"UID:{self.uid or uuid.uuid4()}"]
        lines.append(f"DTSTAMP:{self.last_modified or self.utc_now()}")
        local_date = self.local_date() if self.all_day else None
        if local_date:
            lines.append(f"DTSTART;VALUE=DATE:{local_date.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(local_date + datetime.timedelta(days=1)).strftime('%Y%m%d')}")
        else:
            if self.dtstart:
                lines.append(f"DTSTART:{self.dtstart}")
            if self.dtend:
                lines.append(f"DTEND:{self.dtend}")
        if self.summary:
            lines.append(f"SUMMARY:{ics_escape(self.summary)}")
        if self.description:
            lines.append(f"DESCRIPTION:{ics_escape(self.description)}")
        if self.location:
            lines.append(f"LOCATION:{ics_escape(self.location)}")
        if self.created:
            lines.append(f"CREATED:{self.created}")
        lines.append(f"LAST-MODIFIED:{self.last_modified or self.utc_now()}")
        lines.append(f"SEQUENCE:{self.sequence or 0}")
        lines.append(f"STATUS:{self.status or 'CONFIRMED'}")
        lines.append(f"TRANSP:{self.transp or 'TRANSPARENT'}")
        lines.append("END:VEVENT")
        return lines


class TimeLineItem(BaseModel):
    """返回给前端的日历条目（订阅信息 + 事件信息）。"""

    # 订阅表 ID
    id: int
    # 本地播出日期
    date: Optional[str] = None
    # 起始时间（UTC）
    dtstart: Optional[str] = None
    # 结束时间（UTC）
    dtend: Optional[str] = None
    # 是否全天（播出时间未知）
    all_day: bool = False
    # 标题
    summary: Optional[str] = None
    # 订阅名称
    name: Optional[str] = None
    # 集标题
    episode_name: Optional[str] = None
    # 描述
    description: Optional[str] = None
    # 地点
    location: Optional[str] = None
    # 唯一标识
    uid: Optional[str] = None
    # 年份
    year: Optional[str] = None
    # 类型
    type: Optional[str] = None
    # 季号
    season: Optional[int] = None
    # 集号
    episode: Optional[int] = None
    # 总集数
    total_episodes: Optional[int] = None
    # 海报
    poster: Optional[str] = None
    # 背景图
    backdrop: Optional[str] = None
    # 评分
    vote: Optional[float] = None
    # 状态：N-新建 R-订阅中 P-待定 S-暂停
    state: Optional[str] = None
    # 是否已下载/已入库
    downloaded: bool = False
    # 媒体身份
    tmdbid: Optional[int] = None
    doubanid: Optional[str] = None
    bangumiid: Optional[int] = None
    anilistid: Optional[int] = None
    media_source: Optional[str] = None
    media_id: Optional[str] = None


class SubscribeCal(_PluginBase):
    # 插件名称
    plugin_name = "订阅日历"
    # 插件描述
    plugin_desc = "根据订阅生成追剧日历，支持 iCal 订阅、仪表盘时间轴与侧栏月历视图"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/dibin666/MoviePilot-Neo-Plugins/main/icons/calendar_a.png"
    # 插件版本
    plugin_version = "2.0.1"
    # 插件作者
    plugin_author = "dibin666"
    # 作者主页
    author_url = "https://github.com/dibin666"
    # 插件配置项ID前缀
    plugin_config_prefix = "subscribecal_"
    # 加载顺序
    plugin_order = 42
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _scheduler: Optional[BackgroundScheduler] = None
    _search_sub_region = "plugin.subscribecal.search_sub"
    _update_lock = threading.Lock()

    # 配置属性
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _calc_time: bool = False
    _calname: str = "追剧日历"
    _interval_minutes: int = 15
    _dashboard_size: int = 6
    _sidebar_nav: bool = True

    _config_keys = (
        "enabled",
        "onlyonce",
        "cron",
        "calc_time",
        "calname",
        "interval_minutes",
        "dashboard_size",
        "sidebar_nav",
    )

    def init_plugin(self, config: dict = None):
        """生效配置信息。"""
        self.stop_service()
        self.load_config(config or {})

        if self._onlyonce:
            self.schedule_once()

    def load_config(self, config: dict):
        """加载并规整配置。"""
        for key in self._config_keys:
            if key in config:
                setattr(self, f"_{key}", config.get(key))
        self._enabled = bool(self._enabled)
        self._onlyonce = bool(self._onlyonce)
        self._calc_time = bool(self._calc_time)
        self._sidebar_nav = bool(self._sidebar_nav) if self._sidebar_nav is not None else True
        self._cron = str(self._cron or "").strip()
        self._calname = str(self._calname or "").strip() or "追剧日历"
        self._interval_minutes = self._to_int(self._interval_minutes, 15, 0, 1440)
        self._dashboard_size = self._to_int(self._dashboard_size, 6, 1, 12)

    @staticmethod
    def _to_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        """将配置值转换为限定范围内的整数。"""
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, number))

    def schedule_once(self):
        """调度一次性全量刷新任务。"""
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        logger.info("订阅日历，立即运行一次")
        self._scheduler.add_job(
            func=self.full_update,
            trigger="date",
            run_date=datetime.datetime.now(tz=get_tz()) + datetime.timedelta(seconds=3),
            name="订阅日历全量刷新",
        )
        self._scheduler.start()

        # 关闭一次性开关
        self._onlyonce = False
        self.__update_config()

    def __update_config(self):
        """保存当前配置。"""
        self.update_config({key: getattr(self, f"_{key}") for key in self._config_keys})

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """使用 Vue 联邦组件渲染。"""
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """Vue 模式下表单由前端组件提供，仅返回默认配置。"""
        return None, {
            "enabled": False,
            "onlyonce": False,
            "cron": "",
            "calc_time": False,
            "calname": "追剧日历",
            "interval_minutes": 15,
            "dashboard_size": 6,
            "sidebar_nav": True,
        }

    def get_page(self) -> Optional[List[dict]]:
        """Vue 模式详情页由前端 Page 组件提供。"""
        return None

    def get_state(self) -> bool:
        """插件是否启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """不注册远程命令。"""
        return []

    def get_sidebar_nav(self) -> List[Dict[str, Any]]:
        """注册主界面侧栏「订阅日历」月历入口。"""
        if not self._enabled or not self._sidebar_nav:
            return []
        return [
            {
                "nav_key": "main",
                "title": "订阅日历",
                "icon": "mdi-calendar-month-outline",
                "section": "subscribe",
                "permission": "subscribe",
                "order": 90,
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册插件定时刷新服务。"""
        if not self._enabled:
            return []
        trigger: Any = "interval"
        kwargs: Dict[str, Any] = {"hours": 12}
        if self._cron:
            try:
                trigger = CronTrigger.from_crontab(self._cron, timezone=settings.TZ)
                kwargs = {}
            except Exception as err:
                logger.error(f"订阅日历 cron 表达式无效：{self._cron}，已改为每 12 小时刷新 - {err}")
        return [
            {
                "id": "SubscribeCal",
                "name": "日历数据刷新",
                "trigger": trigger,
                "func": self.full_update,
                "kwargs": kwargs,
            }
        ]

    def stop_service(self):
        """停止插件一次性任务。"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"退出插件失败：{str(e)}")

    def get_api(self) -> List[Dict[str, Any]]:
        """注册插件 API。"""
        return [
            {
                "path": "/subscribe",
                "endpoint": self.get_ics,
                "methods": ["GET"],
                "auth": "apikey",
                "summary": "订阅日历",
                "description": "获取 iCal 订阅日历（apikey 认证）",
            },
            {
                "path": "/download/calendar.ics",
                "endpoint": self.download_ics,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "下载日历",
                "description": "下载订阅日历 ICS 文件",
            },
            {
                "path": "/grouped_events",
                "endpoint": self.get_grouped_events,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取日历事件",
                "description": "获取今天前后指定天数内的日历事件",
            },
            {
                "path": "/events",
                "endpoint": self.get_range_events,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "按日期范围获取日历事件",
                "description": "获取 start 至 end（YYYY-MM-DD，含）之间的日历事件",
            },
            {
                "path": "/refresh",
                "endpoint": self.api_refresh,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "刷新日历数据",
                "description": "后台重新获取全部订阅的播出信息",
            },
        ]

    def get_dashboard(self, key: str = "", **kwargs) -> Optional[
        Tuple[Dict[str, Any], Dict[str, Any], Optional[List[dict]]]]:
        """仪表盘：1、栅格宽度；2、全局配置；3、vue 模式为 None。"""
        size = self._dashboard_size
        return (
            {"cols": 12, "sm": 6, "md": size},
            {
                "refresh": 1800,
                "border": True,
                "title": "订阅日历",
            },
            None,
        )

    # ------------------------------------------------------------------ #
    # ICS
    # ------------------------------------------------------------------ #

    def generate_ics_content(self, calevent: Dict[str, CalendarEvent]) -> str:
        """构建 ICS 日历文本。"""
        lines = CalendarEvent.ics_header(self._calname)
        for event in calevent.values():
            lines.extend(event.to_ics_lines())
        lines.append("END:VCALENDAR")
        return "\r\n".join(ics_fold(line) for line in lines) + "\r\n"

    def get_ics(self) -> Response:
        """iCal 订阅内容。"""
        content = self.generate_ics_content(self.get_events(self.keys))
        return Response(content=content, media_type="text/calendar; charset=utf-8")

    def download_ics(self) -> Response:
        """下载 ICS 文件。"""
        content = self.generate_ics_content(self.get_events(self.keys))
        return Response(
            content=content,
            media_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=calendar.ics"},
        )

    # ------------------------------------------------------------------ #
    # 数据更新
    # ------------------------------------------------------------------ #

    def api_refresh(self) -> schemas.Response:
        """后台触发一次全量刷新。"""
        if self._update_lock.locked():
            return schemas.Response(success=True, message="日历数据正在刷新中")
        threading.Thread(target=self.full_update, kwargs={"cache": False}, daemon=True).start()
        return schemas.Response(success=True, message="已开始刷新日历数据")

    @staticmethod
    def _is_calendar_subscribe(sub: Subscribe) -> bool:
        """是否需要生成日历（洗版订阅的内容通常已播出，跳过）。"""
        return bool(sub) and not sub.best_version

    def full_update(self, cache: bool = False):
        """日历全量更新。"""
        if not self._update_lock.acquire(blocking=False):
            logger.info("订阅日历正在刷新，跳过本次请求")
            return
        try:
            subs = SubscribeOper().list() or []
            keys: List[str] = []
            for sub in subs:
                if not self._is_calendar_subscribe(sub):
                    continue
                try:
                    key = self.update_subscribe(sub, cache=cache)
                except Exception as err:
                    logger.error(f"{sub.name} ({sub.year}) 日历处理失败：{err}", exc_info=True)
                    key = self.get_sub_key(sub)
                    # 失败时保留旧数据，避免网络波动导致日历被清空
                    if key not in self.keys:
                        key = None
                if key and key not in keys:
                    keys.append(key)
            for key in set(self.keys) - set(keys):
                self.del_data(key)
            self.save_keys(keys)
            logger.info(f"订阅日历数据更新完成，共 {len(keys)} 个订阅")
        finally:
            self._update_lock.release()

    def update_subscribe(self, sub: Subscribe, cache: bool = True) -> Optional[str]:
        """获取单个订阅的播出信息并生成事件，返回数据 key。"""
        info = self.search_sub(sub=sub, cache=cache)
        if not info:
            # 查询失败时沿用已有数据
            key = self.get_sub_key(sub)
            return key if self.get_data(key=key) else None
        return self.media_process(sub, info)

    def prune_keys(self):
        """清理已不存在订阅的日历数据。"""
        valid = {self.get_sub_key(sub) for sub in (SubscribeOper().list() or [])
                 if self._is_calendar_subscribe(sub)}
        keys = self.keys
        removed = [key for key in keys if key not in valid]
        if not removed:
            return
        for key in removed:
            self.del_data(key)
        self.save_keys([key for key in keys if key in valid])
        logger.info(f"订阅日历已清理 {len(removed)} 个失效订阅")

    def _add_key(self, key: Optional[str]):
        """登记数据 key。"""
        if not key:
            return
        keys = self.keys
        if key not in keys:
            keys.append(key)
            self.save_keys(keys)

    @eventmanager.register(EventType.SubscribeAdded)
    def sub_add_event(self, event: Event):
        """新增订阅后生成日历。"""
        if not event or not self._enabled:
            return
        sub = SubscribeOper().get((event.event_data or {}).get("subscribe_id"))
        if not self._is_calendar_subscribe(sub):
            return
        try:
            self._add_key(self.update_subscribe(sub, cache=False))
        except Exception as err:
            logger.error(f"{sub.name} ({sub.year}) 日历处理失败：{err}", exc_info=True)

    @eventmanager.register(EventType.SubscribeModified)
    def sub_modified_event(self, event: Event):
        """订阅调整后按需重新生成日历。"""
        if not event or not self._enabled:
            return
        data = event.event_data or {}
        fields = data.get("fields")
        if isinstance(fields, list):
            # NEO 在事件中直接给出真实变更字段
            if not set(fields) & set(SUBSCRIBE_CALENDAR_FIELDS):
                return
        else:
            old_info: Mapping[str, Any] = data.get("old_subscribe_info") or {}
            new_info: Mapping[str, Any] = data.get("subscribe_info") or {}
            if old_info and new_info and all(
                    old_info.get(field) == new_info.get(field) for field in SUBSCRIBE_CALENDAR_FIELDS):
                return
        sub = SubscribeOper().get(data.get("subscribe_id"))
        try:
            if self._is_calendar_subscribe(sub):
                self._add_key(self.update_subscribe(sub, cache=False))
        except Exception as err:
            logger.error(f"订阅 {data.get('subscribe_id')} 日历处理失败：{err}", exc_info=True)
        finally:
            self.prune_keys()

    @eventmanager.register([EventType.SubscribeDeleted, EventType.SubscribeComplete])
    def sub_removed_event(self, event: Event):
        """订阅删除或完成后清理日历数据。"""
        if not event or not self._enabled:
            return
        self.prune_keys()

    # ------------------------------------------------------------------ #
    # 播出信息获取
    # ------------------------------------------------------------------ #

    def search_sub(self, sub: Subscribe, cache: bool = True) -> Optional[List[CalendarInfo]]:
        """查询订阅的播出信息（优先 TMDB，其次 Bangumi）。"""
        cache_key = f"{self.get_sub_key(sub)}{sub.episode_group or ''}"
        cache_params = {"key": cache_key, "region": self._search_sub_region}
        title_year = f"{sub.name} ({sub.year})"
        if cache and result_cache.exists(**cache_params):
            info = result_cache.get(**cache_params)
            if info:
                logger.debug(f"{title_year} 使用缓存数据")
                return [CalendarInfo(**item) if isinstance(item, dict) else item for item in info]

        records: List[dict] = []
        with fresh(not cache):
            if sub.tmdbid:
                records = self._fetch_tmdb(sub)
            elif sub.bangumiid or (sub.media_source == "bangumi" and sub.media_id):
                records = self._fetch_bangumi(sub)
            else:
                logger.info(f"{title_year} 没有 TMDB/Bangumi ID，无法生成日历")
                return None

        if not records:
            logger.warn(f"{title_year} 获取播出信息失败")
            return None
        result_cache.set(value=records, **cache_params)
        return [CalendarInfo(**item) for item in records]

    def _fetch_tmdb(self, sub: Subscribe) -> List[dict]:
        """从 TMDB 获取电视剧季集或电影上映信息。"""
        result = None
        if sub.type == MediaType.TV.value and sub.episode_group:
            result = TmdbApi().get_tv_group_detail(group_id=sub.episode_group, season=sub.season)
            if result:
                # 剧集组中的季号统一为订阅季
                for episode in result.get("episodes", []):
                    episode["season_number"] = sub.season
        if not result:
            result = self.chain.tmdb_info(tmdbid=sub.tmdbid, mtype=MediaType(sub.type), season=sub.season)
        if not result:
            return []
        if sub.type == MediaType.TV.value:
            return [dict(item) for item in result.get("episodes") or []]
        return [dict(result)]

    def _fetch_bangumi(self, sub: Subscribe) -> List[dict]:
        """从 Bangumi 获取番剧放送信息（仅有 Bangumi 身份的订阅）。"""
        try:
            bangumiid = int(sub.bangumiid or sub.media_id)
        except (TypeError, ValueError):
            return []
        req = RequestUtils(ua=settings.NORMAL_USER_AGENT, proxies=settings.PROXY, timeout=15)
        if sub.type != MediaType.TV.value:
            subject = req.get_json(f"{BANGUMI_API_BASE}/v0/subjects/{bangumiid}")
            if not subject or not subject.get("date"):
                return []
            return [{
                "id": bangumiid,
                "air_date": subject.get("date"),
                "title": subject.get("name_cn") or subject.get("name"),
                "overview": subject.get("summary"),
            }]
        records: List[dict] = []
        offset, limit = 0, 100
        while True:
            data = req.get_json(f"{BANGUMI_API_BASE}/v0/episodes",
                                params={"subject_id": bangumiid, "type": 0, "limit": limit, "offset": offset})
            if not data or not isinstance(data.get("data"), list):
                break
            for item in data["data"]:
                ep = item.get("ep") or item.get("sort")
                try:
                    ep = int(float(ep))
                except (TypeError, ValueError):
                    continue
                seconds = item.get("duration_seconds") or 0
                records.append({
                    "id": f"bgm{item.get('id')}",
                    "air_date": item.get("airdate") or None,
                    "episode_number": ep,
                    "name": item.get("name_cn") or item.get("name"),
                    "overview": item.get("desc"),
                    "runtime": round(seconds / 60) if seconds else None,
                    "season_number": sub.season,
                })
            offset += limit
            if offset >= int(data.get("total") or 0):
                break
        return records

    # ------------------------------------------------------------------ #
    # 事件生成
    # ------------------------------------------------------------------ #

    def media_process(self, sub: Subscribe, cal_info: List[CalendarInfo]) -> Optional[str]:
        """
        根据播出信息生成日历事件并保存
        :param sub: 订阅
        :param cal_info: 播出信息
        :return: 数据 key
        """
        if not cal_info:
            return None
        title_year = f"{sub.name} ({sub.year})"
        key = self.get_sub_key(sub)
        is_tv = sub.type == MediaType.TV.value
        # 剧集播出时间（距播出日 00:00 的分钟数）
        minutes = self.generate_average_time(sub, cal_info) if self._calc_time and is_tv else None
        # 剧集时长中位数
        median_runtime = self.compute_median_runtime(cal_info)
        total_episodes = len(cal_info)
        old_events = self.get_event_data(key=key)
        events: Dict[str, CalendarEvent] = {}
        for epinfo in cal_info:
            if not parse_date(epinfo.air_date):
                continue
            epinfo.air_date = str(epinfo.air_date)[:10]
            event_id = str(epinfo.id if epinfo.id is not None else f"{epinfo.season_number}-{epinfo.episode_number}")
            cal = old_events.get(event_id) or CalendarEvent()
            runtime = epinfo.runtime or median_runtime
            if minutes is not None:
                cal.all_day = False
                cal.dtstart = epinfo.utc_airdate(minutes)
                if runtime:
                    cal.dtend = epinfo.utc_airdate(minutes + runtime)
                else:
                    # 无时长时持续到当天 23:59
                    cal.dtend = epinfo.utc_airdate(minutes + (-minutes % 1440 or 1440) - 1)
            else:
                cal.all_day = True
                cal.dtstart = epinfo.utc_airdate(0)
                cal.dtend = epinfo.utc_airdate(1440 - 1)
            cal.air_date = epinfo.air_date
            cal.summary = f"[{epinfo.episode_number}/{total_episodes}]{title_year}" if is_tv else title_year
            cal.episode_name = epinfo.name if is_tv else None
            cal.description = self._build_description(sub, epinfo, is_tv)
            cal.season = epinfo.season_number if is_tv else None
            cal.episode = epinfo.episode_number if is_tv else None
            cal.total_episodes = total_episodes if is_tv else None
            events[event_id] = cal
        if not events:
            logger.info(f"{title_year} 暂无播出日期")
            self.del_data(key)
            return None
        self.save_data(key=key, value={k: v.model_dump() for k, v in events.items()})
        logger.info(f"{title_year} 日历事件处理完成，共 {len(events)} 条")
        return key

    @staticmethod
    def _build_description(sub: Subscribe, epinfo: CalendarInfo, is_tv: bool) -> Optional[str]:
        """事件描述：集标题 + 简介。"""
        parts = []
        if is_tv:
            season = f"S{int(epinfo.season_number):02d}" if epinfo.season_number is not None else ""
            episode = f"E{int(epinfo.episode_number):02d}" if epinfo.episode_number is not None else ""
            heading = f"{season}{episode} {epinfo.name or ''}".strip()
            if heading:
                parts.append(heading)
        overview = epinfo.overview or (sub.description if not is_tv else None)
        if overview:
            overview = str(overview).strip()
            parts.append(overview[:300] + ("…" if len(overview) > 300 else ""))
        return "\n".join(parts) or None

    # ------------------------------------------------------------------ #
    # 前端数据
    # ------------------------------------------------------------------ #

    def get_grouped_events(self, before_days: int = 3, after_days: int = 3) -> List[TimeLineItem]:
        """获取今天前 before_days 天至后 after_days 天的日历条目。"""
        today = datetime.datetime.now(get_tz()).date()
        before_days = max(0, min(int(before_days or 0), 366))
        after_days = max(0, min(int(after_days or 0), 366))
        return self._collect_items(today - datetime.timedelta(days=before_days),
                                   today + datetime.timedelta(days=after_days))

    def get_range_events(self, start: str, end: str) -> List[TimeLineItem]:
        """获取 start 至 end（含）之间的日历条目，最长 62 天。"""
        start_date, end_date = parse_date(start), parse_date(end)
        if not start_date or not end_date:
            return []
        if end_date < start_date:
            start_date, end_date = end_date, start_date
        end_date = min(end_date, start_date + datetime.timedelta(days=62))
        return self._collect_items(start_date, end_date)

    def _collect_items(self, start_date: datetime.date, end_date: datetime.date) -> List[TimeLineItem]:
        """汇总日期范围内所有订阅的日历条目。"""
        items: List[TimeLineItem] = []
        seen_keys = set()
        for sub in SubscribeOper().list() or []:
            if not self._is_calendar_subscribe(sub):
                continue
            key = self.get_sub_key(sub)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            events = self.get_event_data(key=key)
            if not events:
                continue
            obtained = self._obtained_episodes(sub)
            sub_info = sub.to_dict()
            for event in events.values():
                local_date = event.local_date()
                if not local_date or not (start_date <= local_date <= end_date):
                    continue
                if sub.type == MediaType.TV.value:
                    downloaded = event.episode in obtained
                else:
                    downloaded = bool(obtained)
                try:
                    items.append(TimeLineItem(**{
                        **sub_info,
                        **event.model_dump(),
                        "date": local_date.isoformat(),
                        "downloaded": downloaded,
                        "media_id": str(sub.media_id) if sub.media_id is not None else None,
                    }))
                except Exception as err:
                    logger.debug(f"{sub.name} 日历条目转换失败：{err}")
        items.sort(key=lambda x: (x.date or "", x.dtstart or "", x.id, x.episode or 0))
        return items

    @staticmethod
    def _obtained_episodes(sub: Subscribe) -> set:
        """订阅中已下载或已入库的集（note 与各版本 known_episodes 的并集）。"""
        episodes = set()

        def collect(values: Any):
            if isinstance(values, (list, tuple, set)):
                for value in values:
                    try:
                        episodes.add(int(value))
                    except (TypeError, ValueError):
                        continue

        collect(sub.note)
        progress = getattr(sub, "version_progress", None)
        if isinstance(progress, dict):
            for item in progress.values():
                if isinstance(item, dict):
                    collect(item.get("known_episodes"))
        return episodes

    @staticmethod
    def compute_median_runtime(cal_items: List[CalendarInfo]) -> Optional[float]:
        """剧集时长中位数。"""
        runtimes = [item.runtime for item in cal_items if isinstance(item.runtime, (int, float)) and item.runtime > 0]
        return statistics.median(runtimes) if runtimes else None

    def get_event_data(self, key: str) -> Dict[str, CalendarEvent]:
        """读取日历事件数据。"""
        data = self.get_data(key=key) or {}
        if not isinstance(data, dict):
            return {}
        events = {}
        for k, v in data.items():
            try:
                events[k] = CalendarEvent.model_validate(v)
            except Exception:
                continue
        return events

    def get_events(self, keys: Optional[List[str]] = None) -> Dict[str, CalendarEvent]:
        """获取全部（或指定 key 的）日历事件，没有数据时先刷新一次。"""
        if not keys:
            self.full_update(cache=True)
            keys = self.keys
        events: Dict[str, CalendarEvent] = {}
        for key in keys:
            for event_id, event in self.get_event_data(key=key).items():
                events[f"{key}{event_id}"] = event
        return events

    # ------------------------------------------------------------------ #
    # 播出时间推算
    # ------------------------------------------------------------------ #

    @staticmethod
    def parse_episodes(value: Optional[str]) -> List[int]:
        """解析下载记录中的集数，支持 `E01`、`E01-E03`、`E01-E03、E05`。"""
        episodes: List[int] = []
        for start, end in re.findall(r"E(\d+)(?:\s*-\s*E?(\d+))?", str(value or ""), flags=re.IGNORECASE):
            begin = int(start)
            finish = int(end) if end else begin
            if finish < begin or finish - begin > 500:
                continue
            episodes.extend(range(begin, finish + 1))
        return episodes

    @staticmethod
    def dynamic_statistical_analysis(delay_time: List[float]) -> Optional[float]:
        """小样本动态统计，寻找最稳定的播出时间（分钟）。"""
        if not delay_time:
            return None
        sorted_times = sorted(delay_time)
        n_samples = len(sorted_times)
        if n_samples < 3:
            result = sorted_times[0]
            logger.info(f"样本数不足3个，使用最小值: {result:.2f}")
            return result

        window_size = min(5, max(3, n_samples // 2))
        best_cluster: List[float] = sorted_times[:window_size]
        min_stdev = float("inf")
        for i in range(n_samples - window_size + 1):
            window = sorted_times[i:i + window_size]
            stdev = statistics.stdev(window)
            if stdev < min_stdev:
                min_stdev = stdev
                best_cluster = window

        if min_stdev < 100 or max(best_cluster) == min(best_cluster):
            result = statistics.median(best_cluster)
            method = "密集区间中位数"
        else:
            median = statistics.median(best_cluster)
            spread = max(best_cluster) - min(best_cluster)
            weights = [1.0 - abs(x - median) / spread for x in best_cluster]
            result = sum(x * w for x, w in zip(best_cluster, weights)) / (sum(weights) or 1)
            method = "密集区间加权平均"
        logger.info(f"播出时间统计：样本 {n_samples} 个，方法 {method}，"
                    f"区间 [{min(best_cluster):.1f}, {max(best_cluster):.1f}]，结果 {result:.2f} 分钟")
        return result

    def generate_average_time(self, sub: Subscribe, cal_info: List[CalendarInfo]) -> Optional[float]:
        """
        根据订阅下载记录推算剧集播出时间
        :param sub: 订阅
        :param cal_info: 播出信息
        :return: 距播出日 00:00 的分钟数
        """
        season = f"S{int(sub.season):02d}" if sub.season is not None else None
        histories = DownloadHistoryOper().get_last_by(mtype=sub.type, title=sub.name, year=sub.year,
                                                      season=season, tmdbid=sub.tmdbid) or []
        histories = [his for his in histories if self._is_subscribe_history(his)]
        if not histories:
            logger.info(f"{sub.name} ({sub.year}) 没有订阅下载记录")
            return None

        sub_date = self._parse_datetime(sub.date)
        episode_dt: Dict[int, datetime.datetime] = {}
        for history in histories:
            history_date = self._parse_datetime(history.date)
            if not history_date:
                continue
            # 排除订阅添加后 10 分钟内的首次补全
            if sub_date and (history_date - sub_date).total_seconds() < 60 * 10:
                continue
            for ep in self.parse_episodes(history.episodes):
                # 同一集保留最早的下载时间
                if ep not in episode_dt or history_date < episode_dt[ep]:
                    episode_dt[ep] = history_date

        # 剔除订阅补全：集号更大但下载更早
        prev_value = None
        for ep in sorted(episode_dt.keys(), reverse=True):
            current_value = episode_dt[ep]
            if prev_value is not None and current_value > prev_value:
                del episode_dt[ep]
                logger.info(f"{sub.name} - 第 {ep} 集 疑似订阅补全记录，已排除, 下载日期: {current_value}")
                continue
            prev_value = current_value

        air_dates = {i.episode_number: parse_date(i.air_date) for i in cal_info if i.episode_number is not None}
        delay_time = []
        for ep, dt in episode_dt.items():
            air_date = air_dates.get(ep)
            if not air_date:
                continue
            # 下载时间按系统本地时间记录
            base = datetime.datetime.combine(air_date, datetime.time())
            delay_time.append(self.quantize_to_interval((dt - base).total_seconds() / 60, self._interval_minutes))
        # 过滤明显异常（播出前一天或一周后才下载）的数据
        delay_time = [t for t in delay_time if -1440 < t < 1440 * 7]
        return self.dynamic_statistical_analysis(delay_time)

    @staticmethod
    def _is_subscribe_history(history: Any) -> bool:
        """是否为订阅产生的下载记录。"""
        if getattr(history, "subscribe_id", None):
            return True
        note = getattr(history, "note", None)
        if not isinstance(note, dict):
            return False
        return str(note.get("source") or "").split("|", 1)[0] == "Subscribe"

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime.datetime]:
        """解析 `YYYY-MM-DD HH:MM:SS` 时间字符串。"""
        if not value:
            return None
        try:
            return datetime.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return None

    @staticmethod
    def quantize_to_interval(time: float, interval_minutes: int = 15) -> float:
        """按间隔向下取整。"""
        if not interval_minutes or interval_minutes <= 0:
            return time
        return time - time % interval_minutes

    # ------------------------------------------------------------------ #
    # key 管理
    # ------------------------------------------------------------------ #

    def save_keys(self, value: Iterable[str]):
        """保存数据 key 列表。"""
        self.save_data(key="__key__", value=list(value))

    @property
    def keys(self) -> List[str]:
        """已保存的数据 key 列表。"""
        keys = self.get_data(key="__key__") or []
        return list(keys) if isinstance(keys, list) else []

    @staticmethod
    def get_sub_key(sub: Union[Subscribe, Mapping[str, Any]]) -> str:
        """订阅的数据 key（TMDB 订阅保持旧格式以兼容历史数据）。"""
        def value(name: str) -> Any:
            if isinstance(sub, Mapping):
                return sub.get(name)
            return getattr(sub, name, None)

        tmdbid = value("tmdbid")
        if tmdbid:
            identity = str(tmdbid)
        elif value("bangumiid"):
            identity = f"bgm{value('bangumiid')}"
        elif value("media_source") and value("media_id"):
            identity = f"{value('media_source')}{value('media_id')}"
        else:
            identity = f"sub{value('id')}"
        return f"__key_{identity}_{value('year')}_{value('season')}__"
