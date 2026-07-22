"""通知头部结论渲染器测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.notify import (
    chinese_signal_label,
    infer_conclusion,
    prepend_headline,
    render_headline,
    split_by_symbol_headlines,
)


def test_render_buy_strong():
    out = render_headline("buy", strength="strong", symbols=["600522"])
    assert "🟢" in out
    assert "买入" in out
    assert "置信: 强" in out
    assert "600522" in out


def test_render_sell_medium():
    out = render_headline("sell", strength="medium")
    assert "🔴" in out
    assert "卖出" in out
    assert "置信: 中" in out


def test_render_stop_loss_no_strength():
    out = render_headline("stop_loss")
    assert "🚨" in out
    assert "止损" in out
    # stop_loss 不带置信
    assert "置信" not in out


def test_render_watch_strength_ignored():
    out = render_headline("watch", strength="strong")
    assert "⏸️" in out
    assert "观望" in out
    assert "置信" not in out


def test_render_no_signal_no_strength():
    out = render_headline("no_signal")
    assert "⏸️" in out
    assert "观望" in out


def test_render_unknown_falls_back_to_watch():
    out = render_headline("foobar")
    assert "⏸️" in out


def test_render_multi_symbols():
    out = render_headline("buy", strength="strong", symbols=["600522", "601318"])
    assert "600522" in out
    assert "601318" in out


def test_infer_conclusion_empty():
    assert infer_conclusion([]) == ("no_signal", None)


def test_infer_conclusion_priority_stop_loss_over_buy():
    alerts = [
        {"signal_type": "buy", "strength": "strong"},
        {"signal_type": "stop_loss", "strength": "strong"},
    ]
    assert infer_conclusion(alerts)[0] == "stop_loss"


def test_infer_conclusion_priority_sell_over_buy():
    alerts = [
        {"signal_type": "buy", "strength": "strong"},
        {"signal_type": "sell", "strength": "medium"},
    ]
    assert infer_conclusion(alerts)[0] == "sell"


def test_infer_conclusion_returns_strength():
    alerts = [{"signal_type": "buy", "strength": "STRONG"}]
    conclusion, strength = infer_conclusion(alerts)
    assert conclusion == "buy"
    assert strength == "strong"


def test_prepend_headline_basic():
    md = "# Body\n\nDetails"
    out = prepend_headline(md, conclusion="buy", strength="strong", symbols=["600522"])
    assert out.startswith("🟢 操作结论")
    assert "Body" in out


def test_prepend_headline_empty_body():
    out = prepend_headline("", conclusion="watch")
    assert "⏸️" in out


def test_split_by_symbol_headlines():
    alerts = [
        {"symbol": "600522", "signal_type": "buy", "strength": "strong"},
        {"symbol": "600522", "signal_type": "buy", "strength": "strong"},
        {"symbol": "601318", "signal_type": "sell", "strength": "medium"},
    ]
    out = split_by_symbol_headlines(alerts)
    syms = {x[0] for x in out}
    assert syms == {"600522", "601318"}
    by_sym = {x[0]: (x[1], x[2]) for x in out}
    assert by_sym["600522"] == ("buy", "strong")
    assert by_sym["601318"] == ("sell", "medium")


def test_split_skips_empty_symbol():
    alerts = [
        {"signal_type": "buy"},
        {"symbol": "600522", "signal_type": "buy", "strength": "strong"},
    ]
    out = split_by_symbol_headlines(alerts)
    assert len(out) == 1
    assert out[0][0] == "600522"


def test_chinese_signal_label():
    assert chinese_signal_label("buy") == "低吸"
    assert chinese_signal_label("sell") == "高抛"
    assert chinese_signal_label("stop_loss") == "止损"
    assert chinese_signal_label("watch") == "观察"
    assert chinese_signal_label("unknown") == "unknown"
