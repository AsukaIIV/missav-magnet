# MissAV Magnet Extractor

从 [MissAV](https://missav.ws) 页面自动提取最佳 BT 磁力链接 —— 同时支持**命令行独立使用**和 **DeepSeek TUI Skill 调用**。

## DeepSeek Skill 用法

在 DeepSeek TUI 中直接输入：

```
/missav-magnet https://missav.ws/dvmm-336
```

或只输入 `/missav-magnet`，按提示提供链接。Skill 会自动检查代理、抓取页面、排序候选并返回最佳磁力链接。

## 命令行用法

```bash
# 安装依赖
pip install requests
pip install cloudscraper curl_cffi   # 可选，增强反爬

# 基本用法
python3 missav_magnet.py https://missav.ws/dvmm-336

# 安静模式，只输出链接
python3 missav_magnet.py -q https://missav.ws/dvmm-336

# 多 URL 并发
python3 missav_magnet.py url1 url2 url3

# JSON 输出
python3 missav_magnet.py -j https://missav.ws/dvmm-336

# 复制到剪贴板 (macOS)
python3 missav_magnet.py -c https://missav.ws/dvmm-336
```

## 代理

MissAV 在国内通常需要代理。脚本自动读取环境变量或命令行参数：

```bash
# 环境变量（推荐）
export https_proxy=http://127.0.0.1:7890

# 命令行指定
python3 missav_magnet.py -p http://127.0.0.1:7890 https://missav.ws/dvmm-336
```

优先级：`-p` 参数 > `HTTPS_PROXY` > `HTTP_PROXY` > `ALL_PROXY`

## 工作原理

- **4 层反爬自动降级**：cloudscraper → curl_cffi → requests → 系统 curl
- **排序**：磁力优先 → 体积最大 → 时间最新 → btih 字典序
- **keepshare 还原**：自动将 `keepshare.org/p/xxx/magnet:?...` 还原为标准 `magnet:?` 链接

## 许可证

MIT
