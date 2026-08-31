"""parsing 模块测试：tool_call arguments 的解析与修复。"""
from __future__ import annotations

import pytest

from coding_agent.errors import ParsingError
from coding_agent.parsing import parse_tool_arguments


def test_normal_json():
    assert parse_tool_arguments('{"path": "a.py", "n": 3}') == {"path": "a.py", "n": 3}


def test_empty_and_whitespace():
    assert parse_tool_arguments("") == {}
    assert parse_tool_arguments("   ") == {}


def test_markdown_code_fence():
    raw = '```json\n{"path": "a.py"}\n```'
    assert parse_tool_arguments(raw) == {"path": "a.py"}


def test_trailing_comma():
    assert parse_tool_arguments('{"path": "a.py",}') == {"path": "a.py"}


def test_single_quotes():
    assert parse_tool_arguments("{'path': 'a.py'}") == {"path": "a.py"}


def test_trailing_garbage():
    raw = '{"path": "a.py"} 这是额外说明'
    assert parse_tool_arguments(raw) == {"path": "a.py"}


def test_truncated_missing_brace():
    assert parse_tool_arguments('{"path": "a.py"') == {"path": "a.py"}


def test_nested_object():
    raw = '{"todos": [{"id": 1, "content": "x", "status": "pending"}]}'
    assert parse_tool_arguments(raw)["todos"][0]["id"] == 1


def test_non_object_raises():
    with pytest.raises(ParsingError):
        parse_tool_arguments('[1, 2, 3]')


def test_garbage_raises():
    with pytest.raises(ParsingError):
        parse_tool_arguments("这不是 JSON")
