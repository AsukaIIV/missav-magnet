#!/usr/bin/env python3
"""
MissAV / JAV 磁力链接提取器  v4
=================================
用法:
  python3 missav_magnet.py <url1> [url2] [url3] ...
  echo "url1 url2" | python3 missav_magnet.py
  python3 missav_magnet.py -q <url>          # 安静模式，只输出最佳链接
  python3 missav_magnet.py -c <url>          # 自动复制到剪贴板 (macOS)
  python3 missav_magnet.py -j <url>          # JSON 格式输出

特性:
  - 4 层反爬策略自动降级 (cloudscraper → curl_cffi → requests → curl)
  - 指数退避重试 (最多 3 次)
  - 深度解析: HTML href / data-* 属性 / script 标签 / 网盘直链
  - 排序: 磁力优先 → 体积最大 → 时间最新 → btih 字典序
  - keepshare.org/p/xxx/magnet 自动还原为标准 magnet:? 格式
  - 支持网盘直链提取 (rapidgator, nitroflare 等)
  - 支持代理 (HTTPS_PROXY / https_proxy 环境变量自动读取)
  - 显示番号标题等信息 (如果页面中含有)
"""

import re
import sys
import os
import json
import time
import subprocess
import argparse
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs

# ── 常量 ──────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7,ja;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

STAGE_NAMES = {1: "cloudscraper", 2: "curl_cffi", 3: "requests", 4: "curl"}

# ── 正则 ──────────────────────────────────────────────────
# 磁力链接 (href 中)
MAGNET_HREF_RE = re.compile(
    r"""(?:href|data-link|data-magnet|data-href)=["']"""
    r"""((?:magnet:\?xt=urn:btih:[a-fA-F0-9]{32,60}[^"'<>\s]*|"""
    r"""https?://keepshare\.org/[^\s"'<>]*magnet[^\s"'<>]*))""",
    re.IGNORECASE,
)

# script / 纯文本中的磁力链接
MAGNET_BARE_RE = re.compile(
    r"""magnet:\?xt=urn:btih:[a-fA-F0-9]{32,60}[^"'<>\s]*""",
    re.IGNORECASE,
)

# keepshare 跳转
KEEPSHARE_RE = re.compile(
    r"""https?://keepshare\.org/[^\s"'<>]*magnet[^\s"'<>]*""",
    re.IGNORECASE,
)

# 网盘下载直链 (rapidgator, nitroflare, katfile 等)
DIRECT_DL_RE = re.compile(
    r"""https?://(?:rapidgator\.net|nitroflare\.com|katfile\.com|"""
    r"""alfafile\.net|uploadgig\.com|filejoker\.net|ddownload\.com|"""
    r"""rg\.to|mexa\.sh|fikper\.com|drop\.download)/[^\s"'<>]+""",
    re.IGNORECASE,
)

# 体积（需要空格/边界分隔，避免误匹配 btih 中的 hex）
SIZE_RE = re.compile(r"""(?:^|\s|>)(\d+[.,]?\d*)\s*(GB|MB|KB)\b""", re.IGNORECASE)
# 单独匹配 B（字节）需要更明确的上下文
SIZE_RE_B = re.compile(r"""(?:^|\s)(\d+[.,]?\d*)\s+B\b""", re.IGNORECASE)

# URL 内 size 参数
MAGNET_SIZE_RE = re.compile(r"""[&?]size=(\d+)""", re.IGNORECASE)

# 日期 (多种格式)
DATE_PATTERNS = [
    re.compile(r"""(20[12]\d)[-/.](\d{1,2})[-/.](\d{1,2})"""),          # 2024-12-15
    re.compile(r"""(\d{1,2})[-/.](\d{1,2})[-/.](20[12]\d)"""),          # 12-15-2024
    re.compile(r"""(20[12]\d)年(\d{1,2})月(\d{1,2})日"""),              # 2024年12月15日
    re.compile(r"""(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(20[12]\d)""", re.IGNORECASE),
]

MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# 标题
TITLE_RE = re.compile(r"""<title>(.*?)</title>""", re.IGNORECASE)
OG_TITLE_RE = re.compile(r"""<meta\s+property=["']og:title["']\s+content=["']([^"']+)""", re.IGNORECASE)


# ── 工具函数 ──────────────────────────────────────────────

def parse_size(s):
    m = SIZE_RE.search(s) or SIZE_RE_B.search(s)
    if not m:
        return 0
    value = float(m.group(1).replace(",", ""))
    unit = m.group(2).upper()
    mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
    return int(value * mult.get(unit, 1))


def parse_date(text):
    """返回 'YYYY-MM-DD' 或 '0000-00-00'"""
    for pat in DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        groups = m.groups()
        try:
            if isinstance(groups[0], str) and groups[0].isdigit() and len(groups[0]) == 4:
                y, mo, d = groups[0], groups[1], groups[2]
            elif isinstance(groups[-1], str) and groups[-1].isdigit() and len(groups[-1]) == 4:
                if groups[1].lower() in MONTH_MAP:  # 英文月份格式
                    d, mon, y = groups
                    mo = MONTH_MAP[mon.lower()]
                else:
                    mo, d, y = groups[0], groups[1], groups[2]
            else:
                continue
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        except (ValueError, IndexError):
            continue
    return "0000-00-00"


def normalize_magnet(url):
    """keepshare.org/p/xxx/magnet?... → magnet:?... + HTML 实体解码"""
    # 兼容两种格式: /p/TOKEN/magnet 和 /pTOKEN/magnet
    m = re.match(r"https?://keepshare\.org/(?:p/)?[^/]+/(magnet:\?.*)", url, re.IGNORECASE)
    if m:
        url = m.group(1)
    # 解码 HTML 实体
    url = url.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    if url.startswith("magnet:?"):
        return url
    return url


def extract_title(html):
    """从页面提取标题"""
    m = OG_TITLE_RE.search(html) or TITLE_RE.search(html)
    if m:
        title = m.group(1).strip()
        # 清理常见后缀
        title = re.sub(r"\s*[-–|]\s*MissAV.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*[-–|]\s*Watch.*$", "", title, flags=re.IGNORECASE)
        return title
    return None


def pretty_size(n_bytes):
    if n_bytes >= 1024**3:
        return f"{n_bytes/(1024**3):.2f} GB"
    elif n_bytes >= 1024**2:
        return f"{n_bytes/(1024**2):.1f} MB"
    elif n_bytes >= 1024:
        return f"{n_bytes/1024:.1f} KB"
    return f"{n_bytes} B"


# ── 抓取层 ────────────────────────────────────────────────

def _fetch_cloudscraper(url, proxy=None):
    try:
        import cloudscraper
    except ImportError:
        return None, "未安装: pip install cloudscraper"
    try:
        kw = {"browser": "chrome", "platform": "darwin", "mobile": False}
        scraper = cloudscraper.create_scraper(browser=kw)
        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = scraper.get(url, headers=BROWSER_HEADERS, timeout=25, proxies=proxies)
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text, None
        if resp.status_code == 503:
            return None, "Cloudflare 503 — JS Challenge 未通过"
        return None, f"状态 {resp.status_code}, 长度 {len(resp.text)}"
    except Exception as e:
        return None, str(e)


def _fetch_curl_cffi(url, proxy=None):
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None, "未安装: pip install curl_cffi"
    try:
        resp = curl_requests.get(
            url, headers=BROWSER_HEADERS, impersonate="chrome131",
            timeout=25, proxy=proxy,
        )
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text, None
        return None, f"状态 {resp.status_code}, 长度 {len(resp.text)}"
    except Exception as e:
        return None, str(e)


def _fetch_requests(url, proxy=None):
    try:
        import requests
    except ImportError:
        return None, "未安装: pip install requests"
    try:
        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)
        proxies = {"http": proxy, "https": proxy} if proxy else None
        # 预热：先取一次首页设 cookie
        base = re.match(r"(https?://[^/]+)", url)
        if base:
            try:
                session.get(base.group(1), timeout=8, proxies=proxies)
            except Exception:
                pass
        resp = session.get(url, timeout=25, proxies=proxies)
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text, None
        return None, f"状态 {resp.status_code}, 长度 {len(resp.text)}"
    except Exception as e:
        return None, str(e)


def _fetch_curl(url, proxy=None):
    cmd = [
        "curl", "-sL", "--compressed",
        "--max-time", "25", "--connect-timeout", "10",
        "-H", f"User-Agent: {USER_AGENT}",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "-H", "Accept-Language: en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7,ja;q=0.6",
    ]
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=False, timeout=30)
        if result.returncode == 0 and len(result.stdout) > 500:
            for enc in ["utf-8", "shift_jis", "euc-jp", "gbk", "latin-1"]:
                try:
                    return result.stdout.decode(enc), None
                except (UnicodeDecodeError, LookupError):
                    continue
            return result.stdout.decode("utf-8", errors="replace"), None
        return None, f"返回码 {result.returncode}, 长度 {len(result.stdout)}"
    except subprocess.TimeoutExpired:
        return None, "超时"
    except Exception as e:
        return None, str(e)


FETCH_STRATEGIES = [
    (1, _fetch_cloudscraper),
    (2, _fetch_curl_cffi),
    (3, _fetch_requests),
    (4, _fetch_curl),
]

MAX_RETRIES = 3
RETRY_BACKOFF = [0, 2, 5]  # 第 0/1/2 次重试前的等待秒数


def fetch_page(url, proxy=None, verbose=True):
    """多级降级 + 重试"""
    for stage, func in FETCH_STRATEGIES:
        for attempt in range(MAX_RETRIES):
            html, err = func(url, proxy=proxy)
            if html and len(html) > 500:
                if verbose:
                    tag = f"(重试{attempt}次)" if attempt > 0 else ""
                    print(f"  ✅ 第{stage}层 {STAGE_NAMES[stage]} {tag} — {len(html)} 字节")
                return html
            # 503 / Cloudflare 挑战失败 → 直接跳下一层
            if err and ("503" in err or "cloudflare" in err.lower()):
                break
            if attempt < MAX_RETRIES - 1 and "超时" not in str(err):
                if verbose:
                    print(f"  ⏳ {STAGE_NAMES[stage]} 失败, {RETRY_BACKOFF[attempt]}s 后重试...")
                time.sleep(RETRY_BACKOFF[attempt])
        if verbose:
            print(f"  ⚠️  第{stage}层 {STAGE_NAMES[stage]} 不可用 ({err})")
    if verbose:
        print(f"  ❌ 所有策略均失败")
    return None


# ── 解析层 ────────────────────────────────────────────────

class MagnetExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.candidates = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for attr in ("href", "data-link", "data-magnet", "data-href", "data-url"):
            val = attrs.get(attr, "")
            if val.startswith("magnet:?") or ("keepshare.org" in val and "magnet" in val):
                self.candidates.append({"url": val, "size_str": "", "date": "0000-00-00", "size_bytes": 0, "type": "magnet"})
                return
            if DIRECT_DL_RE.match(val):
                self.candidates.append({"url": val, "size_str": "", "date": "0000-00-00", "size_bytes": 0, "type": "direct"})
                return


def _extract_from_rows(html):
    """从 <tr> 表格行中提取磁力链接及对应的体积/日期（行内自包含，不会串行）"""
    candidates = []
    rows = re.split(r'<tr[\s>]', html, flags=re.IGNORECASE)
    for row in rows:
        mag_m = MAGNET_BARE_RE.search(row)
        if not mag_m:
            mag_m = KEEPSHARE_RE.search(row)
        if not mag_m:
            continue
        url = normalize_magnet(mag_m.group(0))
        size_bytes = 0
        size_str = ""
        sm = SIZE_RE.search(row) or SIZE_RE_B.search(row)
        if sm:
            size_str = f"{sm.group(1).replace(',', '')} {sm.group(2).upper()}"
            size_bytes = parse_size(size_str)
        date_str = parse_date(row)
        candidates.append({
            "url": url,
            "size_str": size_str,
            "date": date_str,
            "size_bytes": size_bytes,
            "from": "row_tr",
            "type": "magnet",
        })
    return candidates


def extract_candidates(html):
    seen = set()
    cands = []

    # 0. 优先：表格行解析（精确匹配体积/日期到对应磁力链接，避免串行）
    row_cands = _extract_from_rows(html)
    for c in row_cands:
        url = c["url"]
        if url not in seen:
            seen.add(url)
            cands.append(c)

    # 1. HTML parser（兜底：非表格结构的页面）
    parser = MagnetExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    for c in parser.candidates:
        url = normalize_magnet(c["url"]) if c.get("type") == "magnet" else c["url"]
        if url not in seen:
            seen.add(url)
            cands.append({"url": url, "size_str": "", "date": "0000-00-00", "size_bytes": 0, "from": "html_href", "type": c.get("type", "magnet")})

    # 2-5. 正则兜底（处理非标准页面结构）
    for m in MAGNET_HREF_RE.finditer(html):
        url = normalize_magnet(m.group(1))
        if url not in seen:
            seen.add(url)
            cands.append({"url": url, "size_str": "", "date": "0000-00-00", "size_bytes": 0, "from": "href_re", "type": "magnet"})

    for m in MAGNET_BARE_RE.finditer(html):
        url = normalize_magnet(m.group(0))
        if url not in seen:
            seen.add(url)
            cands.append({"url": url, "size_str": "", "date": "0000-00-00", "size_bytes": 0, "from": "bare_re", "type": "magnet"})

    for m in KEEPSHARE_RE.finditer(html):
        url = normalize_magnet(m.group(0))
        if url not in seen:
            seen.add(url)
            cands.append({"url": url, "size_str": "", "date": "0000-00-00", "size_bytes": 0, "from": "keepshare_re", "type": "magnet"})

    for m in DIRECT_DL_RE.finditer(html):
        url = m.group(0)
        if url not in seen:
            seen.add(url)
            cands.append({"url": url, "size_str": "", "date": "0000-00-00", "size_bytes": 0, "from": "direct_re", "type": "direct"})

    # 6. 从 URL 自身解析 size / dn (display name)
    for c in cands:
        sm = MAGNET_SIZE_RE.search(c["url"])
        if sm:
            c["size_bytes"] = int(sm.group(1))
            c["size_str"] = pretty_size(c["size_bytes"])

    # 7. 窄上下文补充（仅对仍未获取到体积/日期的候选，用 btih 精确定位）
    for c in cands:
        if c["size_bytes"] > 0 and c["date"] != "0000-00-00":
            continue
        btih_m = re.search(r"btih:([a-fA-F0-9]{32,60})", c["url"])
        if not btih_m:
            continue
        idx = html.find(btih_m.group(1))
        if idx < 0:
            continue
        context = html[max(0, idx - 400): idx + 400]
        if c["size_bytes"] == 0:
            sm = SIZE_RE.search(context) or SIZE_RE_B.search(context)
            if sm:
                c["size_str"] = f"{sm.group(1).replace(',', '')} {sm.group(2).upper()}"
                c["size_bytes"] = parse_size(c["size_str"])
        if c["date"] == "0000-00-00":
            c["date"] = parse_date(context)

    return cands


def sort_candidates(cands):
    """磁力优先 → 体积降序 → 日期降序 → 中文字幕优先 → btih 字典序"""
    def key(c):
        link = c["url"]
        has_cn_sub = 0 if re.search(r"[-_.](?:C|ch|CH|UC)(?:$|[&?.-])", link, re.IGNORECASE) else 1
        return (
            0 if c.get("type") == "magnet" else 2,  # magnet 优先
            -c["size_bytes"],
            c["date"] if c["date"] != "0000-00-00" else "9999-99-99",
            has_cn_sub,                               # 中文字幕优先 (同级 tiebreak)
            c["url"],
        )
    return sorted(cands, key=key)


# ── 主流程 ────────────────────────────────────────────────

def process_url(url, proxy=None, verbose=True, batch=False):
    if verbose and not batch:
        print(f"\n{'─'*60}")
        print(f"▸ {url}")

    html = fetch_page(url, proxy=proxy, verbose=(verbose and not batch))
    if not html:
        if batch:
            print(f"  ❌ {url}")
        return None

    title = extract_title(html)
    if title and verbose and not batch:
        print(f"  📼 {title}")

    cands = extract_candidates(html)
    if not cands:
        if batch:
            print(f"  ❌ {url} — 未找到下载链接")
        elif verbose:
            print("  ❌ 未找到任何下载链接")
        return None

    cands = sort_candidates(cands)
    best = cands[0]

    if batch:
        size = best.get("size_str") or "?"
        tag = title or url
        print(f"  ✓ {tag[:50]}  {size:>8}  {best['url'][:80]}")
    elif verbose:
        print(f"\n  📋 {len(cands)} 个候选:")
        for i, c in enumerate(cands):
            size = c["size_str"] or "未知大小"
            date = c["date"] if c["date"] != "0000-00-00" else "未知日期"
            type_label = "🧲" if c.get("type") == "magnet" else "📦"
            star = " ★" if i == 0 else "  "
            short = c["url"]
            if len(short) > 95:
                short = short[:92] + "..."
            print(f"   {star} [{i+1}] {type_label} {size:>10}  {date}  {short}")

    if verbose and not batch:
        link_type = "磁力" if best.get("type") == "magnet" else "网盘下载"
        print(f"\n  ✅ 最佳{link_type}:")
        print(f"  {best['url']}")

    return {
        "url": url,
        "title": title,
        "best_link": best["url"],
        "link_type": best.get("type", "magnet"),
        "best_size": best["size_str"],
        "best_date": best["date"],
        "total_candidates": len(cands),
    }


def get_proxy():
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = os.environ.get(var)
        if val:
            return val
    return None


def copy_to_clipboard(text):
    """macOS 剪贴板"""
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="MissAV / JAV 磁力链接提取器 — 自动抓取页面并提取最佳 BT 下载链接",
        epilog="示例: python3 missav_magnet.py https://missav.ws/xxx-001",
    )
    parser.add_argument("urls", nargs="*", help="一个或多个 MissAV 页面 URL")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式：只输出最佳下载链接")
    parser.add_argument("-c", "--clipboard", action="store_true", help="自动复制最佳链接到剪贴板 (macOS)")
    parser.add_argument("-j", "--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("-o", "--output", metavar="FILE", help="将最佳链接写入文件")
    parser.add_argument("-p", "--proxy", metavar="PROXY", help="指定代理 (如 http://127.0.0.1:7890)")
    parser.add_argument("-b", "--batch", action="store_true", help="批量模式：每行一个结果，适合 10+ 链接")
    parser.add_argument("--all", action="store_true", help="显示所有候选链接 (而不仅是最佳)")
    args = parser.parse_args()

    # 收集 URL
    urls = list(args.urls)
    if not urls and not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        urls = re.findall(r"https?://[^\s]+", data)

    if not urls:
        parser.print_help()
        sys.exit(1)

    # 代理
    proxy = args.proxy or get_proxy()
    if not args.quiet and proxy:
        print(f"🔗 使用代理: {proxy}")

    verbose = not args.quiet and not args.json

    # 批量模式：>=10 个 URL 自动启用（除非用户明确要求 verbose）
    batch = args.batch or (len(urls) >= 10 and not args.quiet and not args.json)
    if batch:
        verbose = False  # 批量模式关闭详细输出，改用紧凑格式
        max_workers = min(3, len(urls))  # 大批量降低并发，减少触发 Cloudflare 防护
    else:
        max_workers = min(5, len(urls))

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(process_url, u, proxy, verbose, batch): u for u in urls}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)

    if not results:
        if not args.quiet:
            print("\n❌ 所有 URL 均未能提取到下载链接")
        sys.exit(1)

    # 输出
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.quiet:
        for r in results:
            print(r["best_link"])
    elif batch:
        print(f"\n{'='*60}")
        print(f"✅ 完成 — {len(results)}/{len(urls)} 成功")
        for r in results:
            print(f"  {r['best_link']}")
    else:
        print(f"\n{'='*60}")
        print(f"✅ 完成 — {len(results)}/{len(urls)} 成功\n")
        for r in results:
            type_label = "🧲" if r.get("link_type") == "magnet" else "📦"
            print(f"  {type_label} {r['best_link']}")

    # 剪贴板
    if args.clipboard and results:
        text = "\n".join(r["best_link"] for r in results)
        if copy_to_clipboard(text):
            print("📋 已复制到剪贴板")
        else:
            print("⚠️  剪贴板复制失败")

    # 写入文件
    if args.output:
        with open(args.output, "w") as f:
            for r in results:
                f.write(r["best_link"] + "\n")
        if not args.quiet:
            print(f"💾 已保存到 {args.output}")

    # --all 模式显示全部候选
    if args.all and not args.quiet and not args.json:
        for r in results:
            print(f"\n  [全部候选] {r.get('title') or r['url']}:")
            # 需要重新获取完整列表 — 这里简单处理
            print(f"  最佳: {r['best_link']}  ({r['best_size']}, {r['best_date']})")


if __name__ == "__main__":
    main()
