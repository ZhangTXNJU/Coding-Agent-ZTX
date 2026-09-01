"""fetch 工具测试：网络异常兜底 / 截断 / HTML→文本 / 注册。

用 monkeypatch 替换 urllib.request.urlopen 模拟网络场景，避免真实联网依赖。
"""
from __future__ import annotations

from types import SimpleNamespace as NS
from urllib import error as urlerror

import pytest

from coding_agent.tools import build_default_registry, FETCH
from coding_agent.tools.fetch import (
    _decode_html,
    _is_unsafe_host,
    _looks_binary,
    fetch_url,
    html_to_text,
)
from coding_agent.tools.registry import ToolContext


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(workdir=tmp_path)


# --------------------------------------------------------------------------- #
# 构造可用的 fake HTTP response（支持 with 上下文 + .headers + .read(n)）
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, headers=None, chunks=None):
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self._chunks = list(chunks or [])
        self._closed = False

    def read(self, n=None):
        if not self._chunks:
            return b""
        if n is not None and n > 0:
            chunk = self._chunks[0][:n]
            self._chunks[0] = self._chunks[0][n:]
            if not self._chunks[0]:
                self._chunks.pop(0)
            return chunk
        chunk = b"".join(self._chunks)
        self._chunks = []
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_urlopen(monkeypatch, fake):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake)


def _urlopen_raising(exc):
    def _fake(req, timeout=None):
        raise exc
    return _fake


# --------------------------------------------------------------------------- #
# html_to_text：块级标签 / script 剥离 / 链接保留 / title 抽取
# --------------------------------------------------------------------------- #


def test_html_to_text_strips_script_and_keeps_paragraphs():
    html = ("<html><head><title>Hello</title></head>"
            "<body><h1>标题</h1><p>第一段</p><script>var x=1;</script>"
            "<p>第二段</p></body></html>")
    out = html_to_text(html)
    assert "标题" in out
    assert "第一段" in out
    assert "第二段" in out
    assert "Hello" in out  # title 文本已在正文中（不再重复加前缀）
    assert "var x=1" not in out
    assert "题目" not in out  # 因 title 已含于文本，不重复添加前缀


def test_html_to_text_keeps_links():
    html = '<a href="https://docs.example.com/page">官方文档</a>'
    out = html_to_text(html)
    assert "官方文档" in out
    assert "link: https://docs.example.com/page" in out


def test_html_to_text_handles_empty_or_garbage():
    assert html_to_text("   ") == ""
    assert html_to_text("<script>boom</script>") == ""
    assert "hello" in html_to_text("<div>hello</div>")


# --------------------------------------------------------------------------- #
# _looks_binary / _decode_html
# --------------------------------------------------------------------------- #


def test_looks_binary_detects_by_extension_and_content_type():
    assert _looks_binary("https://x.com/a.png", "image/png")
    assert _looks_binary("https://x.com/file.pdf", "")
    assert _looks_binary("https://x.com", "application/octet-stream")
    assert not _looks_binary("https://x.com/doc.html", "text/html")
    assert not _looks_binary("https://x.com/api.json", "application/json")
    assert not _looks_binary("https://x.com/page", "")
    assert not _looks_binary("https://x.com/app.js", "text/javascript")


def test_decode_html_uses_utf8_by_default():
    assert _decode_html("你好".encode("utf-8"), {}) == "你好"


def test_decode_html_respects_explicit_charset():
    data = "café".encode("latin-1")
    out = _decode_html(data, {"Content-Type": "text/html; charset=iso-8859-1"})
    assert out == "café"


# --------------------------------------------------------------------------- #
# SSRF 防护：拒绝非公网地址
# --------------------------------------------------------------------------- #


def test_is_unsafe_host_rejects_loopback_ip():
    assert _is_unsafe_host("127.0.0.1")
    assert _is_unsafe_host("::1")


def test_is_unsafe_host_rejects_private_and_linklocal():
    assert _is_unsafe_host("192.168.1.1")
    assert _is_unsafe_host("10.0.0.1")
    assert _is_unsafe_host("169.254.169.254")  # 云元数据


def test_is_unsafe_host_allows_public_ip():
    assert _is_unsafe_host("8.8.8.8") == ""
    assert _is_unsafe_host("93.184.216.34") == ""


def test_is_unsafe_host_rejects_hostname_resolving_to_private(monkeypatch):
    import coding_agent.tools.fetch as fetch_mod

    monkeypatch.setattr(
        fetch_mod.socket, "getaddrinfo",
        lambda host, port: [(0, 0, 0, "", ("10.0.0.5", 0))],
    )
    assert _is_unsafe_host("internal.example.com")


def test_is_unsafe_host_allows_public_hostname(monkeypatch):
    import coding_agent.tools.fetch as fetch_mod

    monkeypatch.setattr(
        fetch_mod.socket, "getaddrinfo",
        lambda host, port: [(0, 0, 0, "", ("93.184.216.34", 0))],
    )
    assert _is_unsafe_host("example.com") == ""


def test_fetch_rejects_loopback_url():
    r = fetch_url("http://127.0.0.1/x")
    assert not r.success
    assert "非公网" in r.error


def test_fetch_rejects_metadata_url():
    r = fetch_url("http://169.254.169.254/latest/meta-data")
    assert not r.success
    assert "非公网" in r.error


# --------------------------------------------------------------------------- #
# 网络异常兜底
# --------------------------------------------------------------------------- #


def test_fetch_http_error_returns_error(monkeypatch):
    _patch_urlopen(
        monkeypatch,
        _urlopen_raising(urlerror.HTTPError("u", 404, "Not Found", {}, None)),
    )
    r = fetch_url("https://example.com/x", timeout=5)
    assert not r.success
    assert "404" in r.error


def test_fetch_urlerror_returns_error(monkeypatch):
    _patch_urlopen(
        monkeypatch,
        _urlopen_raising(urlerror.URLError(NS(reason=ConnectionError("refused")))),
    )
    r = fetch_url("https://example.com/x", timeout=5)
    assert not r.success
    assert "refused" in r.error


def test_fetch_invalid_scheme_rejected():
    r = fetch_url("ftp://example.com/foo", timeout=5)
    assert not r.success
    assert "http" in r.error


def test_fetch_binary_rejected(monkeypatch):
    _patch_urlopen(
        monkeypatch,
        lambda req, timeout=None: FakeResponse(
            headers={"Content-Type": "image/png"}, chunks=[b"\x89PNG"]
        ),
    )
    r = fetch_url("https://example.com/a.png", timeout=5)
    assert not r.success
    assert "二进制" in r.error


def test_fetch_success_returns_text(monkeypatch):
    body = b"<html><body><h1>Hi</h1><p>content</p></body></html>"
    _patch_urlopen(
        monkeypatch,
        lambda req, timeout=None: FakeResponse(chunks=[body]),
    )
    r = fetch_url("https://example.com/page", timeout=5)
    assert r.success
    assert "Hi" in r.text
    assert "content" in r.text


def test_fetch_empty_page_is_error(monkeypatch):
    _patch_urlopen(
        monkeypatch,
        lambda req, timeout=None: FakeResponse(chunks=[b"<html></html>"]),
    )
    r = fetch_url("https://example.com/empty", timeout=5)
    assert not r.success


# --------------------------------------------------------------------------- #
# 超大网页截断
# --------------------------------------------------------------------------- #


def test_fetch_truncates_oversized_body(monkeypatch):
    # >max_bytes 的内容；分片让 chunk 跨越 the cap 边界以触发截断
    big = ("<html><p>" + "x" * 400 + "</p></html>").encode()
    _patch_urlopen(
        monkeypatch,
        lambda req, timeout=None: FakeResponse(chunks=[big]),
    )
    r = fetch_url("https://example.com/big", timeout=5, max_bytes=64)
    assert r.success
    assert "已截断" in r.text


def test_fetch_within_limit_not_truncated(monkeypatch):
    body = b"<html><p>short text</p></html>"
    _patch_urlopen(
        monkeypatch,
        lambda req, timeout=None: FakeResponse(chunks=[body]),
    )
    r = fetch_url("https://example.com/small", timeout=5, max_bytes=1024)
    assert r.success
    assert "已截断" not in r.text
    assert "short text" in r.text


# --------------------------------------------------------------------------- #
# handler 输出（注册表分发 + 错误信息成形）
# --------------------------------------------------------------------------- #


def test_fetch_registered_in_registry():
    reg = build_default_registry()
    assert "fetch" in reg.names()
    assert reg.get("fetch") is FETCH


def test_fetch_handler_missing_url_raises(ctx):
    from coding_agent.errors import ToolError

    with pytest.raises(ToolError):
        FETCH.handler({"max_chars": 100}, ctx)


def test_fetch_handler_invalid_params_raises(ctx, monkeypatch):
    from coding_agent.errors import ToolError

    _patch_urlopen(
        monkeypatch,
        lambda req, timeout=None: FakeResponse(chunks=[b"<p>x</p>"]),
    )
    with pytest.raises(ToolError):
        FETCH.handler({"url": "https://a.com", "timeout": -1}, ctx)


def test_fetch_handler_error_returned_not_raised(ctx, monkeypatch):
    _patch_urlopen(
        monkeypatch,
        _urlopen_raising(urlerror.URLError(NS(reason=ConnectionError()))),
    )
    out = FETCH.handler({"url": "https://a.com/x"}, ctx)
    assert out.startswith("错误：")
