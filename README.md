# MissAV Magnet Extractor

从 [MissAV](https://missav.ws) 页面自动提取最佳 BT 磁力链接。

## 安装

```bash
pip install requests
# 推荐同时安装以应对 Cloudflare：
pip install cloudscraper curl_cffi
```

## 用法

```bash
# 基本用法
python3 missav_magnet.py https://missav.ws/dvmm-336

# 安静模式，只输出链接
python3 missav_magnet.py -q https://missav.ws/dvmm-336

# 自动复制到剪贴板 (macOS)
python3 missav_magnet.py -c https://missav.ws/dvmm-336

# JSON 格式输出
python3 missav_magnet.py -j https://missav.ws/dvmm-336

# 多 URL 并发抓取
python3 missav_magnet.py url1 url2 url3
echo "url1 url2" | python3 missav_magnet.py
```

## 代理配置

MissAV 在国内通常需要代理。脚本按以下顺序读取代理：

1. 命令行 `-p` 参数
2. 环境变量 `HTTPS_PROXY` / `https_proxy`
3. 环境变量 `HTTP_PROXY` / `http_proxy`
4. 环境变量 `ALL_PROXY` / `all_proxy`

```bash
# 环境变量方式（推荐）
export https_proxy=http://127.0.0.1:7890

# 命令行指定
python3 missav_magnet.py -p http://127.0.0.1:7890 https://missav.ws/dvmm-336
```

## 反爬策略

4 层自动降级：`cloudscraper` → `curl_cffi` → `requests` → 系统 `curl`

## 排序规则

候选磁力链接按以下优先级：
1. **体积最大**优先
2. 体积相同时 **发布时间最新**优先
3. 以上均相同时按 btih 字典序

## keepshare 跳转还原

自动将 `keepshare.org/p/xxx/magnet:?...` 还原为标准 `magnet:?` 链接。

## 许可证

MIT
