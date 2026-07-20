from dataclasses import is_dataclass

from atrade.per_symbol.report import SymbolReport


def test_symbol_report_is_dataclass():
    assert is_dataclass(SymbolReport)
