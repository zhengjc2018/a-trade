"""统一通知接口测试。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.notify import load_notifier, split_markdown_by_bytes


def test_split_markdown_short_returns_single():
    """短内容不切分。"""
    md = "# hello\n\nworld"
    parts = split_markdown_by_bytes(md, max_bytes=100)
    assert parts == [md]


def test_split_markdown_chinese_byte_boundary():
    """中文字符按 UTF-8 字节切分，不拆碎字符。"""
    # 100 个汉字 ≈ 300 字节，max=200 应切分
    md = "# 测试\n\n" + "你好世界" * 50
    parts = split_markdown_by_bytes(md, max_bytes=100)
    assert len(parts) >= 2
    for p in parts:
        # 每段都不超 max_bytes
        assert len(p.encode("utf-8")) <= 100


def test_split_markdown_prefers_paragraph_boundary():
    """尽量在段落边界（\n\n）拆分。"""
    md = "第一段内容" * 20 + "\n\n" + "第二段内容" * 20 + "\n\n" + "第三段" * 20
    parts = split_markdown_by_bytes(md, max_bytes=100)
    assert len(parts) >= 2
    # 第一段应该在 \n\n 处结束
    assert parts[0].endswith("第一段内容" * 20) or "\n\n" in parts[0]


def test_split_markdown_empty():
    assert split_markdown_by_bytes("", max_bytes=100) == []


def test_split_markdown_round_trip():
    """切分后重组应等于原文（无信息丢失）。"""
    md = "中文段落\n\n" * 30 + "最后一段"
    parts = split_markdown_by_bytes(md, max_bytes=100)
    # 拼接后长度应接近（去掉切分时 strip 的换行）
    joined = "\n\n".join(parts)
    assert joined.replace("\n\n", "") == md.replace("\n\n", "")


def test_load_notifier_placeholder_env(monkeypatch):
    """占位符应报错（无论 .env 怎么设）。"""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("QQ_TARGET_GROUP", "your_group_id")
    with pytest.raises(ValueError, match="占位符"):
        load_notifier()


def test_load_notifier_empty_env(monkeypatch):
    """空字符串应报错。"""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("QQ_TARGET_GROUP", "")
    with pytest.raises(ValueError, match="QQ_TARGET_GROUP"):
        load_notifier()
