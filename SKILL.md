---
name: missav-magnet
description: >
  MissAV 磁力链接提取。从 MissAV 页面自动抓取并提取最佳 BT 下载磁力链接，
  优先选体积最大、其次时间最新，keepshare.org 跳转链接自动还原为标准 magnet:? 格式。
  使用场景：用户提供 MissAV 网址要求提取磁力链接、BT 下载地址，或 keepshare.org/p/xxx/magnet 还原。
---

# MissAV Magnet Extractor

从 MissAV 页面提取最佳磁力链接。

## 核心脚本

脚本位于 `scripts/missav_magnet.py`，直接执行即可：

```bash
python3 scripts/missav_magnet.py <url>
```

## 代理配置（重要）

MissAV 在国内网络通常需要代理才能访问。脚本按以下顺序自动读取代理：

1. 命令行 `-p` 参数（最高优先级）
2. 环境变量 `HTTPS_PROXY` / `https_proxy`
3. 环境变量 `HTTP_PROXY` / `http_proxy`
4. 环境变量 `ALL_PROXY` / `all_proxy`

**每次使用前，提醒用户设置代理。示例：**

```bash
# 方式一：环境变量（推荐，一次设置整个终端会话生效）
export https_proxy=http://127.0.0.1:7890

# 方式二：命令行指定
python3 scripts/missav_magnet.py -p http://127.0.0.1:7890 <url>
```

如果用户未设置代理且脚本全部抓取失败，提示用户配置代理后重试。

## 反爬策略

脚本内置 4 层自动降级：
1. `cloudscraper` — 专门过 Cloudflare（需 `pip install cloudscraper`）
2. `curl_cffi` — TLS 指纹模拟 Chrome 131（需 `pip install curl_cffi`）
3. `requests` — 标准请求 + 完整浏览器头（需 `pip install requests`）
4. 系统 `curl` — 最终兜底，无需安装

至少需要安装 `requests` 以获得较高成功率：

```bash
pip install requests
```

推荐同时安装 `cloudscraper` 以应对 Cloudflare 防护：

```bash
pip install cloudscraper requests
```

## 排序规则

候选磁力链接按以下优先级排序：
1. **体积最大**优先（从 URL `&size=` 参数或页面上下文提取）
2. 体积相同时 **发布时间最新**优先
3. 以上均相同时按 btih 字典序

## 输出模式

| 参数 | 效果 |
|------|------|
| (无) | 详细输出：抓取过程、排名列表、最佳链接 |
| `-q` | 安静模式，只输出最佳 magnet 链接 |
| `-c` | 自动复制到 macOS 剪贴板 |
| `-j` | JSON 格式输出（含标题、体积、日期） |
| `-o FILE` | 将最佳链接写入文件 |

## keepshare 还原

脚本自动识别并还原 keepshare.org 跳转链接：

```
https://keepshare.org/p/5uj7smo/magnet:?xt=urn:btih:67B91DA1B16A182F8AE9B8822FD3EA7ED1A47634&size=4749940228&biz=ktr
→
magnet:?xt=urn:btih:67B91DA1B16A182F8AE9B8822FD3EA7ED1A47634&size=4749940228&biz=ktr
```

## 并发处理

多个 URL 并发抓取（最多 5 线程），可一次传入多个链接：

```bash
python3 scripts/missav_magnet.py url1 url2 url3
echo "url1 url2" | python3 scripts/missav_magnet.py
```

## 故障排查

### "所有策略均失败"
- 检查代理是否设置且可用
- 尝试安装 cloudscraper：`pip install cloudscraper`
- 手动用浏览器打开目标 URL 确认页面可访问

### "未找到磁力链接"
- 页面结构可能变化，尝试直接在 HTML 中搜索 `magnet:?xt=urn:btih:`
- 如果页面使用了 JavaScript 动态加载（非 SSR），需要用浏览器开发者工具手动提取
