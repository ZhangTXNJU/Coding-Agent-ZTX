"""联网工具：fetch——抓取 URL 并返回可读文本。

用标准库 urllib.request 实现（零额外依赖，符合"关键逻辑自行编写"约束）。
覆盖面：
  - 网络异常兜底：超时 / 连接失败 / DNS / 协议错误 / HTTP 4xx-5xx 全部包装为
    带可读信息的 ToolError，绝不裸抛崩溃。
  - 超大网页截断：限制下载字节数（max_bytes），并支持按 HTML 中的 <script>/<style>
    等噪声先剔除再截文本。
  - HTML → 文本：手写轻量转换器（去标签、抽 title、保留超链接与换行语义、
    剔除 script/style/注释），不依赖 bs4/lxml。
  - 编码处理：从 Content-Type / HTML meta 嗅探编码，utf-8 兜底。

与 bash+curl 的关系：fetch 把"抓取网页"确定性暴露为独立工具，自带超时、
大小限制与文本清洗，模型无需自行拼 curl；属于结构化、被工具发现驱动的联网入口。
"""
from __future__ import annotations

import html as html_mod
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from ..errors import ToolError
from .registry import Tool

# 默认单次下载上限（字节）。超大网页在此截断而非整页拉取。
_DEFAULT_MAX_BYTES = 512 * 1024  # 512 KiB
# 返回给模型的最大字符数（进一步保护上下文）。
_DEFAULT_MAX_CHARS = 12_000
# 请求超时（连接 + 读取）。
_DEFAULT_TIMEOUT = 15
# 默认 User-Agent：多数站点会拒绝通用 urllib UA。
_USER_AGENT = "Mozilla/5.0 (compatible; CodingAgent-fetch/1.0)"

# 常见资源类型后缀：对非文本资源直接放弃文本化。
_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
    ".pdf", ".zip", ".gz", ".tar", ".7z", ".rar", ".exe", ".dmg",
    ".mp3", ".mp4", ".avi", ".mov", ".woff", ".woff2", ".ttf", ".eot",
}

_HTML_STRIP_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINE_RE = re.compile(r"\n\s*\n+")


@dataclass
class FetchResult:
    """抓取结果：以 text 为准（已文本化），失败时 error 非空。"""

    success: bool
    text: str = ""
    error: str = ""


def _is_unsafe_host(host: str) -> str:
    """SSRF 防护：判断 host 是否指向非公网地址。

    安全返回 ""；否则返回拒绝原因。覆盖：
      - IP 字面量（loopback / 私网 / link-local / 云元数据 169.254.169.254 等，is_global=False）
      - 域名：解析所有地址，任一非公网即拒绝（对 DNS rebinding 做保守防御）
    解析失败时返回 ""，交给后续网络层报错，不在此误判。
    注意：getaddrinfo 校验与实际 urlopen 连接之间仍有理论上的 DNS rebinding 窗口，
    这里是成本/收益合理的首道防线。
    """
    host = host.strip().strip("[]")
    try:
        if not ipaddress.ip_address(host).is_global:
            return f"拒绝访问非公网地址 {host}"
        return ""
    except ValueError:
        pass  # 非 IP 字面量 → 走域名解析
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return ""
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if not ip.is_global:
            return f"域名 {host} 解析到非公网地址 {addr}"
    return ""


def _looks_binary(url: str, content_type: str) -> bool:
    """启发式判断是否二进制资源（后缀或 Content-Type）。"""
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    if any(path.endswith(ext) for ext in _BINARY_EXTENSIONS):
        return True
    ct = (content_type or "").lower()
    binary_sniff = ("application/" in ct and "json" not in ct and "xml" not in ct
                    and "javascript" not in ct) or "image/" in ct or "audio/" in ct
    return binary_sniff


def _decode_html(data: bytes, headers: dict) -> str:
    """从 Content-Type charset 或 HTML meta 推断编码；兜底 utf-8。"""
    # 1) 显式 charset
    ct = (headers.get("Content-Type") or "").lower()
    m = re.search(r"charset=([\w.-]+)", ct)
    if m:
        try:
            return data.decode(m.group(1), errors="replace")
        except (LookupError, UnicodeError):
            pass
    # 2) HTML meta charset（限制在前 4KiB）
    head = data[:4096].decode("utf-8", errors="ignore")
    m = re.search(r'<meta[^>]+charset=["\']?\s*([\w.-]+)', head)
    # utf-8 声明常见；其它则尝试
    if m and m.group(1).lower() not in ("utf-8", "utf8"):
        try:
            return data.decode(m.group(1), errors="replace")
        except (LookupError, UnicodeError):
            pass
    # 3) utf-8 兜底
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def html_to_text(fragment: str) -> str:
    """把一段 HTML 源码转换为可读的纯文本。

    - 剥离 script/style/注释噪声
    - 抽取 <title>
    - 把 <a href="..."> 转成 "text (link: url)"，避免丢失链接语义
    - 把块级标签（h1-6/p/li/tr/br/div 等）转成换行，保留结构
    - 折叠多余空白与空行
    """
    # 抽 title
    title_m = re.search(r"<title[^>]*>(.*?)</title>", fragment, re.IGNORECASE | re.DOTALL)
    title = html_mod.unescape(title_m.group(1)).strip() if title_m else ""
    # 剥注释
    frag = _COMMENT_RE.sub("", fragment)
    # 剥 script/style 及其内容
    frag = _HTML_STRIP_RE.sub("", frag)
    # 提取超链接
    frag = re.sub(
        r'<a\s+[^>]*href=["\']?([^"\' >]+)["\']?[^>]*>(.*?)</a>',
        lambda m: f"{html_mod.unescape(re.sub(r'<[^>]+>', '', m.group(2))).strip()} (link: {m.group(1)})",
        frag,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # 块级标签 → 换行
    frag = re.sub(
        r"</?(?:h[1-6]|p|div|li|tr|br|ul|ol|section|article|header|footer|table|blockquote|pre)"  # noqa: E501
        r"[^>]*>",
        "\n",
        frag,
        flags=re.IGNORECASE,
    )
    # 其余标签剥除
    frag = _HTML_TAG_RE.sub("", frag)
    frag = html_mod.unescape(frag)
    # 折叠空白与空行
    frag = _WHITESPACE_RE.sub(" ", frag)
    frag = _BLANK_LINE_RE.sub("\n", frag)
    frag = "\n".join(line.strip() for line in frag.splitlines()).strip()
    if title and title not in frag:
        frag = f"题目：{title}\n\n{frag}"
    return frag


def _read_with_cap(response, max_bytes: int) -> tuple[bytes, bool]:
    """带上限读取响应体；返回 (数据, 是否达到上限被截断)。"""
    chunks: list[bytes] = []
    remaining = max_bytes + 1  # 多读取 1 字节以判断是否恰好超限
    truncated = False
    while remaining > 0:
        chunk = response.read(min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    if remaining <= 0:
        truncated = True
    data = b"".join(chunks)
    if truncated and len(data) > max_bytes:
        data = data[:max_bytes]
    return data, truncated


def fetch_url(url: str, timeout: int = _DEFAULT_TIMEOUT, max_bytes: int = _DEFAULT_MAX_BYTES) -> FetchResult:  # noqa: E501
    """发起 GET 抓取；对外只返回 FetchResult，网络异常已兜底为 error 字段。"""
    if not url.startswith(("http://", "https://")):
        return FetchResult(success=False, error=f"仅支持 http/https URL，收到：{url[:80]!r}")

    host = urllib.parse.urlparse(url).hostname
    if not host:
        return FetchResult(success=False, error=f"无法从 URL 解析主机：{url[:80]!r}")
    unsafe = _is_unsafe_host(host)
    if unsafe:
        return FetchResult(success=False, error=unsafe)

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if _looks_binary(url, content_type):
                return FetchResult(
                    success=False,
                    error=f"资源疑似二进制（Content-Type: {content_type or 'unknown'}），仅支持文本/HTML",
                )
            raw, truncated = _read_with_cap(resp, max_bytes)
    except urllib.error.HTTPError as exc:
        return FetchResult(success=False, error=f"HTTP {exc.code} {exc.reason}: {url}")
    except urllib.error.URLError as exc:
        reason = exc.reason
        err = f"无法访问 {url}: {reason}"
        if isinstance(reason, socket.timeout):
            err = f"请求超时（>{timeout}s）: {url}"
        elif isinstance(reason, (socket.gaierror,)):
            err = f"域名解析失败: {url}（{reason}）"
        return FetchResult(success=False, error=err)
    except (socket.timeout, TimeoutError):
        return FetchResult(success=False, error=f"请求超时（>{timeout}s）: {url}")
    except (ConnectionError, OSError) as exc:
        return FetchResult(success=False, error=f"网络错误: {url}（{exc}）")
    except Exception as exc:  # 兜底：任何异常都不崩溃，转为可读错误
        return FetchResult(success=False, error=f"抓取失败: {url}（{exc}）")

    text = _decode_html(raw, dict(resp.headers))
    trimmed_text = html_to_text(text)
    note = ""
    if truncated:
        note = f"\n\n[注意：响应超过 {max_bytes} 字节已截断；返回内容为前段文本]"
    if not trimmed_text.strip():
        return FetchResult(success=False, error="获取到的页面未包含可提取的文本内容")
    return FetchResult(success=True, text=trimmed_text + note)


def fetch(args: dict, ctx) -> str:
    """fetch 工具 handler：抓取 URL，返回可读文本；失败返回清晰错误而非抛异常。"""
    url = str(args.get("url", "")).strip()
    if not url:
        raise ToolError("fetch 需要 url 参数")
    timeout = int(args.get("timeout") or _DEFAULT_TIMEOUT)
    max_bytes = int(args.get("max_bytes") or _DEFAULT_MAX_BYTES)
    # 收敛非法参数
    if timeout <= 0 or max_bytes <= 0:
        raise ToolError("timeout 与 max_bytes 必须为正整数")

    result = fetch_url(url, timeout=timeout, max_bytes=max_bytes)
    if not result.success:
        return f"错误：{result.error}"

    # 保护上下文：按 max_chars 二次截断
    max_chars = int(args.get("max_chars") or _DEFAULT_MAX_CHARS)
    if max_chars > 0 and len(result.text) > max_chars:
        return result.text[:max_chars] + f"\n…[内容已截断至 {max_chars} 字符]…"
    return result.text


FETCH = Tool(
    name="fetch",
    description=(
        "抓取一个 http/https URL，并把网页内容转换为简洁可读的纯文本返回。"
        "适用于获取在线文档、API 返回、博客文章等文本内容。"
        "内置超时、下载大小上限与自动截断，二进制资源会拒绝；"
        "拒绝访问本机/内网/云元数据等非公网地址。"
        "若页面无法访问或包含可读文本，会返回带原因的清晰错误信息。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的完整 http/https URL"},
            "max_chars": {
                "type": "integer",
                "description": "返回给模型的文本最大字符数（默认 12000）",
            },
            "timeout": {
                "type": "integer",
                "description": "请求超时秒数（默认 15）",
            },
            "max_bytes": {
                "type": "integer",
                "description": "下载字节上限，超限截断（默认 512KiB）",
            },
        },
        "required": ["url"],
    },
    handler=fetch,
)
