"""SQLite 参数适配层的单元测试。

sqlite3 只接受 None/int/float/str/bytes，而迁移层刻意产出驱动无关的值
（NUMERIC 列 -> Decimal、JSON 列 -> 原生对象）。适配必须发生在 connector
层，否则 executemany 直接抛 "type 'decimal.Decimal' is not supported"。
"""

from __future__ import annotations

import json
from decimal import Decimal

from open_navicat.drivers.sqlite_connector import _adapt_params


class TestAdaptParams:
    def test_passthrough_native_types(self):
        params = (None, 1, 2.5, "text", b"\x00\x01")
        assert _adapt_params(params) == params

    def test_empty(self):
        assert _adapt_params(None) == ()
        assert _adapt_params(()) == ()

    def test_decimal_becomes_float(self):
        # 数值导入的常规路径：NUMERIC 列 -> Decimal
        result = _adapt_params((Decimal("99.5"),))
        assert result == (99.5,)
        assert isinstance(result[0], float)

    def test_decimal_integer_stays_numeric(self):
        assert _adapt_params((Decimal("42"),)) == (42.0,)

    def test_dict_becomes_json_text(self):
        result = _adapt_params(({"a": 1, "b": [2, 3]},))
        assert isinstance(result[0], str)
        assert json.loads(result[0]) == {"a": 1, "b": [2, 3]}

    def test_list_becomes_json_text(self):
        assert _adapt_params(([1, "x"],)) == ("[1, \"x\"]",)

    def test_mixed_row(self):
        result = _adapt_params((7, "ada", Decimal("91.5"), {"tags": ["x"]}, None))
        assert result[2] == 91.5
        assert isinstance(result[3], str)
        assert result[4] is None
