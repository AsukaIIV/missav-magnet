---
name: missav-magnet
description: >
  MissAV 磁力链接提取。从 MissAV 页面自动抓取最佳 BT 磁力链接（优先体积最大、时间最新），
  keepshare.org 跳转链接自动还原为标准 magnet:? 格式。
  触发场景：(1) 用户输入 /missav-magnet 命令 (2) 用户提供 MissAV/JAV 网址要求提取磁力链接
  (3) 用户提供 keepshare.org/p/xxx/magnet 要求还原。国内网络需代理。
---

# MissAV Magnet Extractor

核心脚本：`scripts/missav_magnet.py`

## 工作流

收到请求后严格按以下顺序执行。

### 1. 收集 URL

若用户消息中未提供 MissAV URL，询问：

> 请提供 MissAV 页面链接（多个请用空格分隔）：

### 2. 确认代理

先检查环境变量：

```bash
echo "https_proxy=$https_proxy HTTPS_PROXY=$HTTPS_PROXY all_proxy=$all_proxy"
```

若全部为空，提醒用户：

> ⚠️ 未检测到代理。MissAV 在国内通常需要代理访问。
> 请先设置：`export https_proxy=http://127.0.0.1:7890`
> 或直接回复代理地址，我将用 -p 参数传递。

若用户提供了代理地址但未设环境变量，执行时追加 `-p <proxy>`。

### 3. 运行脚本

```bash
# 默认：详细输出，让用户看到抓取过程和候选排名
python3 scripts/missav_magnet.py <url>

# 用户明确说"只要链接" → 安静模式
python3 scripts/missav_magnet.py -q <url>

# 指定代理
python3 scripts/missav_magnet.py -p <proxy> <url>

# 多 URL 并发（最多 5 线程）
python3 scripts/missav_magnet.py <url1> <url2> <url3>
```

默认使用详细模式。仅当用户明确要求"只要链接"或"安静输出"时使用 `-q`。

### 4. 展示结果

向用户呈现：
- 番号标题
- 最佳磁力链接及其体积、日期
- 候选总数

### 5. 故障处理

| 错误信息 | 原因 | 处理 |
|---------|------|------|
| 所有策略均失败 | 网络不通 / Cloudflare 拦截 | 确认代理可用；建议 `pip install cloudscraper` 后重试 |
| 未找到磁力链接 | 页面无 BT 下载或需 JS 渲染 | 告知用户用浏览器打开页面手动复制 magnet 链接 |
| ImportError: requests | 依赖缺失 | 执行 `pip install requests` 后重试 |

脚本内置 4 层自动降级（cloudscraper → curl_cffi → requests → curl），无需手动选择抓取策略。
