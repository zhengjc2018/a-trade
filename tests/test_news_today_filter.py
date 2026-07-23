"""filter_today_only 测试。"""
from datetime import datetime, timedelta


def _item(title="x", when=None):
    from atrade.news.collector import NewsItem
    return NewsItem(
        title=title,
        summary="",
        source="test",
        publish_time=when or datetime.now(),
        url="",
        category="macro",
    )


def test_filter_today_only_keeps_today():
    from atrade.news.collector import NewsCollector
    collector = NewsCollector()
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    items = [_item("today"), _item("yesterday", yesterday)]
    out = collector.filter_today_only(items)
    assert len(out) == 1
    assert out[0].title == "today"


def test_filter_today_only_drops_yesterday():
    from atrade.news.collector import NewsCollector
    collector = NewsCollector()
    yesterday = datetime.now() - timedelta(days=1)
    items = [_item("y", yesterday)]
    assert collector.filter_today_only(items) == []


def test_filter_today_only_handles_mixed():
    from atrade.news.collector import NewsCollector
    collector = NewsCollector()
    today = datetime.now()
    items = [
        _item("a", today - timedelta(hours=2)),
        _item("b", today - timedelta(days=1, hours=2)),
        _item("c", today),
    ]
    out = collector.filter_today_only(items)
    assert {x.title for x in out} == {"a", "c"}
