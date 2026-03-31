from __future__ import annotations

from app.main import _build_yql_query, _escape_yql_string, _extract_groups


def test_escape_yql_string_escapes_quotes_and_backslashes() -> None:
    raw = 'a"b\\c'
    assert _escape_yql_string(raw) == 'a\\"b\\\\c'


def test_build_yql_query_constructs_where_clauses() -> None:
    yql = _build_yql_query(
        q="",
        category='electronics"pro',
        brand="BrandX",
        min_price=10.0,
        max_price=None,
        in_stock=True,
    )

    assert 'select * from product where true' in yql
    assert 'category contains "electronics\\"pro"' in yql
    assert 'brand contains "BrandX"' in yql
    assert "price >= 10.0" in yql
    assert "in_stock = true" in yql
    assert "userQuery()" not in yql


def test_extract_groups_parses_grouping_response() -> None:
    data = {
        "root": {
            "children": [
                {
                    "children": [
                        {
                            "children": [
                                {
                                    "value": "electronics",
                                    "fields": {"count()": 3},
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }

    groups = _extract_groups(data)
    assert len(groups) == 1
    assert groups[0].label == "electronics"
    assert groups[0].count == 3

