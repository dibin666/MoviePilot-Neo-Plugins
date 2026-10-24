"""订阅日历插件单测。"""
import datetime
from types import SimpleNamespace

import pytest
import pytz

import subscribecal
from subscribecal import CalendarEvent, CalendarInfo, SubscribeCal, ics_fold


def make_sub(**kwargs):
    """构造订阅对象。"""
    data = {
        "id": 1, "name": "葬送的芙莉莲", "year": "2023", "type": "电视剧", "tmdbid": 209867,
        "bangumiid": None, "doubanid": None, "anilistid": None, "media_source": None, "media_id": None,
        "season": 1, "episode_group": None, "best_version": 0, "state": "R", "poster": "https://p/x.jpg",
        "backdrop": None, "vote": None, "note": [1, 2], "version_progress": {"r1": {"known_episodes": [3]}},
        "description": "简介", "date": "2023-09-01 00:00:00",
    }
    data.update(kwargs)
    sub = SimpleNamespace(**data)
    sub.to_dict = lambda: dict(data)
    return sub


@pytest.fixture
def plugin(monkeypatch):
    """启用状态的插件实例，订阅查询替换为内存数据。"""
    instance = SubscribeCal()
    instance.init_plugin({"enabled": True, "calname": "测试日历"})
    subs = [make_sub()]
    monkeypatch.setattr(subscribecal, "SubscribeOper", lambda: SimpleNamespace(
        list=lambda *a, **k: subs, get=lambda sid: next((s for s in subs if s.id == sid), None)))
    instance._test_subs = subs
    yield instance
    for key in instance.keys:
        instance.del_data(key)
    instance.del_data("__key__")


def tv_info(today):
    """三集：昨天、今天、明天。"""
    return [
        CalendarInfo(id=100 + i, air_date=(today + datetime.timedelta(days=i - 2)).isoformat(),
                     episode_number=i, season_number=1, name=f"第{i}话", runtime=24)
        for i in range(1, 4)
    ]


def test_plugin_metadata(plugin):
    from app.utils.object import ObjectUtils

    assert plugin.get_render_mode() == ("vue", "dist/assets")
    assert ObjectUtils.check_method(SubscribeCal.get_page)
    assert plugin.get_sidebar_nav()[0]["section"] == "subscribe"
    plugin.init_plugin({"enabled": True, "sidebar_nav": False})
    assert plugin.get_sidebar_nav() == []
    cols, attrs, elements = plugin.get_dashboard("")
    assert cols["md"] == 6 and elements is None and attrs["title"] == "订阅日历"
    paths = {api["path"]: api["auth"] for api in plugin.get_api()}
    assert paths["/subscribe"] == "apikey" and paths["/events"] == "bear"


def test_config_normalize(plugin):
    plugin.init_plugin({"enabled": True, "interval_minutes": "", "dashboard_size": "99", "calname": " "})
    assert plugin._interval_minutes == 15
    assert plugin._dashboard_size == 12
    assert plugin._calname == "追剧日历"


def test_invalid_cron_falls_back(plugin):
    plugin.init_plugin({"enabled": True, "cron": "bad cron"})
    service = plugin.get_service()[0]
    assert service["trigger"] == "interval" and service["kwargs"] == {"hours": 12}


def test_media_process_and_range(plugin):
    tz = subscribecal.get_tz()
    today = datetime.datetime.now(tz).date()
    sub = plugin._test_subs[0]
    key = plugin.media_process(sub, tv_info(today))
    plugin.save_keys([key])
    assert key == "__key_209867_2023_1__"

    events = plugin.get_event_data(key)
    assert len(events) == 3
    assert all(event.all_day for event in events.values())

    items = plugin.get_grouped_events(0, 0)
    assert [item.episode for item in items] == [2]
    assert items[0].date == today.isoformat()
    assert items[0].downloaded is True  # E02 在 note 中
    assert items[0].name == "葬送的芙莉莲"

    items = plugin.get_range_events((today - datetime.timedelta(days=1)).isoformat(),
                                    (today + datetime.timedelta(days=1)).isoformat())
    assert [(i.episode, i.downloaded) for i in items] == [(1, True), (2, True), (3, True)]


def test_media_process_keeps_uid_and_drops_removed(plugin):
    today = datetime.datetime.now(subscribecal.get_tz()).date()
    sub = plugin._test_subs[0]
    key = plugin.media_process(sub, tv_info(today))
    uid = plugin.get_event_data(key)["101"].uid
    plugin.media_process(sub, tv_info(today)[:2])
    events = plugin.get_event_data(key)
    assert events["101"].uid == uid
    assert "103" not in events


def test_timed_events(plugin, monkeypatch):
    plugin.init_plugin({"enabled": True, "calc_time": True})
    monkeypatch.setattr(plugin, "generate_average_time", lambda sub, info: 23 * 60)
    today = datetime.datetime.now(subscribecal.get_tz()).date()
    key = plugin.media_process(plugin._test_subs[0], tv_info(today))
    event = plugin.get_event_data(key)["102"]
    assert not event.all_day
    start = subscribecal.parse_utc(event.dtstart).astimezone(subscribecal.get_tz())
    end = subscribecal.parse_utc(event.dtend).astimezone(subscribecal.get_tz())
    assert (start.hour, start.minute) == (23, 0)
    assert (end - start) == datetime.timedelta(minutes=24)
    assert event.local_date() == today


def test_ics_content(plugin):
    today = datetime.date(2026, 10, 24)
    sub = plugin._test_subs[0]
    key = plugin.media_process(sub, tv_info(today))
    content = plugin.generate_ics_content(plugin.get_events([key]))
    assert content.startswith("BEGIN:VCALENDAR\r\n")
    assert content.endswith("END:VCALENDAR\r\n")
    assert "\n" not in content.replace("\r\n", "")
    assert content.count("BEGIN:VEVENT") == 3
    assert "DTSTART;VALUE=DATE:20261024" in content
    assert "DTEND;VALUE=DATE:20261025" in content
    assert "DTSTAMP:" in content
    assert "X-WR-CALNAME:测试日历" in content
    for line in content.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75


def test_ics_escape_and_fold():
    event = CalendarEvent(summary="A, B; C\\D", dtstart="20261024T000000Z", dtend="20261024T010000Z")
    lines = event.to_ics_lines()
    assert "SUMMARY:A\\, B\\; C\\\\D" in lines
    folded = ics_fold("DESCRIPTION:" + "中文" * 40)
    parts = folded.split("\r\n")
    assert all(len(p.encode("utf-8")) <= 75 for p in parts)
    assert "".join(p[1:] if i else p for i, p in enumerate(parts)) == "DESCRIPTION:" + "中文" * 40


def test_parse_episodes():
    assert SubscribeCal.parse_episodes("E01") == [1]
    assert SubscribeCal.parse_episodes("E01-E03") == [1, 2, 3]
    assert SubscribeCal.parse_episodes("E01-E02、E05") == [1, 2, 5]
    assert SubscribeCal.parse_episodes("") == []
    assert SubscribeCal.parse_episodes(None) == []


def test_generate_average_time(plugin, monkeypatch):
    base = datetime.date(2026, 10, 1)
    info = [CalendarInfo(id=i, air_date=(base + datetime.timedelta(days=7 * (i - 1))).isoformat(),
                         episode_number=i) for i in range(1, 6)]
    histories = [
        SimpleNamespace(date=f"{(base + datetime.timedelta(days=7 * (i - 1))).isoformat()} 23:{10 + i:02d}:00",
                        episodes=f"E{i:02d}", note={"source": "Subscribe|{}"}, subscribe_id=None)
        for i in range(1, 6)
    ]
    histories.append(SimpleNamespace(date="2026-10-02 10:00:00", episodes="E01-E03、E04",
                                     note={"source": "Manual"}, subscribe_id=None))
    monkeypatch.setattr(subscribecal, "DownloadHistoryOper",
                        lambda: SimpleNamespace(get_last_by=lambda **kwargs: histories))
    plugin._interval_minutes = 15
    sub = make_sub(date="2026-09-01 00:00:00")
    minutes = plugin.generate_average_time(sub, info)
    assert minutes == 23 * 60


def test_get_sub_key_compat():
    assert SubscribeCal.get_sub_key(make_sub()) == "__key_209867_2023_1__"
    assert SubscribeCal.get_sub_key(make_sub(tmdbid=None, bangumiid=123)) == "__key_bgm123_2023_1__"
    assert SubscribeCal.get_sub_key({"tmdbid": 5, "year": "2020", "season": None}) == "__key_5_2020_None__"


def test_bangumi_fetch(plugin, monkeypatch):
    pages = {
        0: {"data": [{"id": 1, "airdate": "2026-10-01", "ep": 1, "name": "a", "duration_seconds": 1440},
                     {"id": 2, "airdate": "", "ep": 2, "name": "b"}], "total": 2},
    }

    class FakeRequest:
        def __init__(self, *args, **kwargs):
            pass

        def get_json(self, url, params=None, **kwargs):
            assert url.endswith("/v0/episodes") and params["subject_id"] == 123
            return pages[params["offset"]]

    monkeypatch.setattr(subscribecal, "RequestUtils", FakeRequest)
    sub = make_sub(tmdbid=None, bangumiid=123)
    records = plugin._fetch_bangumi(sub)
    assert records[0]["runtime"] == 24 and records[0]["episode_number"] == 1
    key = plugin.media_process(sub, [CalendarInfo(**r) for r in records])
    assert len(plugin.get_event_data(key)) == 1


def test_modified_event_filter(plugin, monkeypatch):
    calls = []
    monkeypatch.setattr(plugin, "update_subscribe", lambda sub, cache=True: calls.append(sub.id))
    monkeypatch.setattr(plugin, "prune_keys", lambda: calls.append("prune"))
    plugin.sub_modified_event(SimpleNamespace(event_data={"subscribe_id": 1, "fields": ["state"]}))
    assert calls == []
    plugin.sub_modified_event(SimpleNamespace(event_data={"subscribe_id": 1, "fields": ["episode_group"]}))
    assert calls == [1, "prune"]


def test_prune_keys(plugin):
    plugin.save_data("__key_1_2020_1__", {"x": CalendarEvent(summary="x").model_dump()})
    plugin.save_keys(["__key_209867_2023_1__", "__key_1_2020_1__"])
    plugin.prune_keys()
    assert plugin.keys == ["__key_209867_2023_1__"]
    assert plugin.get_data("__key_1_2020_1__") is None


def test_best_version_skipped(plugin):
    plugin._test_subs[0].best_version = 1
    assert plugin.get_grouped_events(30, 30) == []


def test_legacy_stored_event_compatible(plugin):
    legacy = {
        "created": "20250101T000000Z", "dtstart": "20261023T160000Z", "dtend": "20261024T155900Z",
        "summary": "[1/3]x (2023)", "description": None, "season": 1, "episode": 1, "location": None,
        "uid": "u1", "transp": "OPAQUE", "sequence": 0, "status": "CONFIRMED", "last_modified": "20250101T000000Z",
    }
    plugin.save_data("__key_209867_2023_1__", {"1": legacy})
    event = plugin.get_event_data("__key_209867_2023_1__")["1"]
    assert event.uid == "u1"
    assert event.local_date() == datetime.datetime(2026, 10, 23, 16, tzinfo=pytz.utc).astimezone(
        subscribecal.get_tz()).date()


def test_api_routes(plugin, monkeypatch):
    """插件 API 能被 FastAPI 正常注册与调用。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    today = datetime.datetime.now(subscribecal.get_tz()).date()
    plugin.save_keys([plugin.media_process(plugin._test_subs[0], tv_info(today))])
    monkeypatch.setattr(plugin, "full_update", lambda cache=False: None)

    app = FastAPI()
    for api in plugin.get_api():
        api = dict(api)
        api.pop("auth", None)
        app.add_api_route(**api)
    client = TestClient(app)

    resp = client.get("/subscribe")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    assert resp.text.count("BEGIN:VEVENT") == 3

    resp = client.get("/download/calendar.ics")
    assert "attachment" in resp.headers["content-disposition"]

    resp = client.get("/grouped_events", params={"before_days": 1, "after_days": 1})
    assert [item["episode"] for item in resp.json()] == [1, 2, 3]

    resp = client.get("/events", params={"start": today.isoformat(), "end": today.isoformat()})
    data = resp.json()
    assert len(data) == 1 and data[0]["date"] == today.isoformat() and data[0]["tmdbid"] == 209867

    resp = client.post("/refresh")
    assert resp.json()["success"] is True
