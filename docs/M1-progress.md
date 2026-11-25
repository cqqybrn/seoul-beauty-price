# M1 进展与待核实项

日期：2026-11-15。**M1 未验收，不能开启自动发布。**

## 本次实际 HTTP 核实

少量串行公开 GET，Babitalk 请求之间等待至少 3.1 秒，无登录、验证码处理、代理或重试。
核实时使用具名 `SeoulBeautyPrice/0.1` UA，但联系 URL 为占位 `https://example.invalid/`，
因为站长尚未提供域名。此诊断不等于满足正式运行 UA 要求；代码对 live UA 要求真实站点 URL。
未进一步采集用户内容，未保存完整网页或图片。

- `https://babitalk.com/robots.txt`：HTTP 200；通配 UA 允许根路径，禁止 login / mypage /
  elb-status / sentry-example-page / gad_source 查询；无 Crawl-delay。
- `https://babitalk.com/sitemap/sitemap-event.xml`：HTTP 200；索引含 event-0 与 event-1。
- `https://babitalk.com/sitemap/sitemap-event-0.xml`：HTTP 200；共 **5,000** 条 URL，**5,000** 条 lastmod。
  检查到的记录使用 `2026-11-08T18:15:29.183Z`。该时间可能是统一构建时间，
  尚未证明是逐活动真实更新时间，后续不能只因有 lastmod 就断言增量完整可靠。
- 活动 `27669`、`34486`：纯 HTTP 返回 Product JSON-LD，含主价格和医院名称；
  可见正文只有主价，未获得“이벤트 옵션”明细、稳定选项 ID 或医院地址。
  这两个样本是手术活动，只用于观察 HTTP 页面结构，不入皮肤科库。
- 活动 `60174`、`59057`：状态 HTTP 200，但 title 为 `Error - 바비톡`，无 Product。
  **不能直接当成 HTTP 404，也不能据此标 ended。**

结论：已证明某些页面纯 HTTP 能拿到主价 JSON-LD；**尚未证明皮肤科选项明细可由纯 HTTP 获取**。
需要在真实域名配置后，以 robots-aware 浏览器渲染验证详情、选项与医院信息。
没有伪造选项解析规则，也没有把平台公司页脚地址当医院地址。

## 已写代码和离线回归

- SitemapSpider 发现器保留逐条 lastmod 并去重，可解 gzip；不会下载详情页。
- 增量 helper 对缺 lastmod 的记录按天刷新；对于疑似统一构建时间，仍需实页验证制定保守重抓策略。
- 最小固定请求间隔、并发 1、robots 允许/拒绝、Crawl-delay 加严、robots 不可用 fail-closed。
- 默认 Scrapy 会忽略 Crawl-delay 且 robots 下载失败会放行；本实现补上这两点。
- 来源日级停采持久化；403、429、已知验证码标记停止并入本地告警 outbox；不重试。
- 在收到完整可信 EventFacts 时可幂等写库，含事实快照、价格历史、首尔预筛、选项失活与缓存哈希。
- 内容哈希除名称和价格外包含标题、VAT、附加费标记，避免营销条件变化后错误复用抽取。
- 测试网页为明确标注的 synthetic fixture，不伪称真实采集样本，不用于 M2 准确率。

## 未完成的验收项

1. 在皮肤科实页确认完整选项、医院地址及稳定 option ID。
2. 如需 Playwright，验证 robots-aware 所有请求（含浏览器子资源），同时落实按域名串行限速。
   当前中间件明确禁止直接打开未经验证的 Playwright 路径，避免子请求绕过政策。
3. 核实 Ubuntu ARM64 上 Chromium 实际运行。当前主机为 Windows x86_64，没有 ARM64 实机证明。
4. 阅读平台完整条款并摘录采集相关条文。此次页脚只见条款按钮，没有已核实条款 URL，不编造摘录。
5. 正式实现 collect → 事实投影 → events/options 的实页端到端管线并导出 100 条真实样本。
6. 告警 outbox 尚未连接 Telegram（M5），不能宣称已发送通知。

## Gemini 文档核实（为 M2 留档）

本次实际读取：

- 官方 SDK 文档：`https://googleapis.github.io/python-genai/`
- 官方包元数据：`https://pypi.org/pypi/google-genai/json`

PyPI 当时的版本为 **3.3.0**，已精确固定。
官方文档确认 `client.models.generate_content`、`types.GenerateContentConfig`、
`response_mime_type='application/json'`、Pydantic `response_schema` / `response_json_schema`，
及 `types.AutomaticFunctionCallingConfig(disable=True)` 与 `response.function_calls` 手动循环机制。
文档出现 `gemini-3.8-flash` 示例，但本次未核对模型价格及批量接口用法，未据此启用任何默认模型或 API 调用。
后续 M2 仍须重新核实官方模型目录、价格、批量提交/轮询/结果下载及实际配额。

## 站长缺失配置

正式 UA 需要本站真实域名；后续需要 Gemini 密钥、联系邮箱、Telegram 与 healthchecks 配置。
没有要求将任何密钥粘贴到聊天或写进代码。
