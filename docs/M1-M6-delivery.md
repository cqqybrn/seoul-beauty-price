# M1–M6 本轮实现与验收边界

> 早期交付记录：其中页数、数据量与实网状态已被后续工作更新。当前状态请看 `chinese-consumer-redesign.md` 和 `expanded-crawl-2026-11-15.md`，不要将本文早期结论作为当前验收结果。

2026-11-15。此文件是实际进度，不是“全部完成”证明。

## 可立即查看的网站

本机 `http://127.0.0.1:4321/` 已启动，Astro + Tailwind，静态构建为 13 页。
在 390px 手机 viewport 检查了首页和 Ulthera 项目页，无横向溢出，项目导航成功。
无真实价格时如实显示“数据待核实”，不将 synthetic fixtures 发布到网站。
医院页面模板、价格历史、分布、条件分区、品牌过滤和搜索已写；有数据时静态生成。

## M1 / M4：采集

已实现 Scrapy 独立子进程 worker、robots / Crawl-delay / 域名路径约束、串行限速、
KST 凌晨窗口、来源日级停采、sitemap 元数据、暂存事实、来源量下降门禁后再入库、
连续两天缺失/404 下架判定、保守医院合并。

但 **完整实页适配器没有验收**：

- Babitalk 普通 Product 单主价不当成选项。仅接受明确独立命名/稳定 ID/KRW 价格/医院地址
  的多 Offer 结构，实际皮肤科 DOM 还未验证。
- Yeoshin 解析器仍明确未就绪，券价和标价必须在真实页面区分后才可启用。
- 浏览器子资源 robots / 限速路径未实现，因此 Playwright 采集没有启用。
- 缺本站实际域名，`pipeline run --live` 已实测在网络请求前失败：要求 `PIPELINE_SITE_URL`。
- 本轮没有新增两平台真实活动采集；此前少量诊断结果见 M1-progress，不夸大为全量爬取。
- 平台条款阅读、中韩多样本价格对照、真实 100 条选项导出仍未完成。

## M2：抽取

已实现 Pydantic 输出模型、十项目规则、工具关闭、明确数据/指令隔离提示、
内容哈希缓存、低置信度或规则失败高档重试一次、失败率门禁、已失败结果跨运行继续阻断。
原生 Gemini 同步调用与 batch submit/get/import 代码使用 google-genai 3.3.0，
提交/轮询和结果导入有离线测试，metadata 防止错配或重复导入。

批量入口可单独运行，尚未接到“首次自动选择批量、跨日自动轮询”的调度策略。
金标评估器要求 100 个不同 option_id、四字段分别 ≥95%；没有设计方金标，**准确率未验收**。
本机没有抽取用原生 Gemini 密钥，也未替用户把分析网关密钥写成原生 Google 密钥。

官方文档实际核实：

- https://googleapis.github.io/python-genai/
- https://ai.google.dev/gemini-api/docs/batch-api

确认 generate_content / response_schema / AutomaticFunctionCallingConfig(disable=True)、
batches.create(model,src,config)、batches.get(name)、dest.inlined_responses / dest.file_name、
files.download(file)。对应 SDK 参数也在本机实例化校验成功；尚无真实批量任务结果。

## M3：计算与静态站

Decimal 含税/次数/剂量单位价；分桶、分位数、样本量门禁、异常低价、限制分区，
保留未变 ID、过滤过期 hash，已离线验证。网站从数据库导出的 JSON 在构建期读取，
不会把 SQLite 或密钥发给浏览器。

构建输出写入不可变 release，成功后原子替换 current 符号链接。构建失败保留旧站。
Windows 主机缺少符号链接权限，成功原子发布测试跳过；失败保留旧站测试通过。
此处不把 Windows 本地预览冒充 Linux 生产原子发布。
Frankfurter v2 的 KRW/CNY 端点本次实际可用；已写每天缓存和失败沿用带日期旧值。

## M5：运维

systemd 04:00 KST timer、flock、资源上限、最小可写目录、Caddy、Litestream 配置与服务已写。
告警 outbox、Telegram 发送、heartbeats、来源量下降、抽取成功率、下架判定、
三日失败提示、AI 预算预留/结算、构建失败保留、运行失败短路均有离线覆盖。

尚未连接站长 Telegram、healthchecks、对象存储、Ubuntu ARM64 主机，也未做备份恢复演练。
成本账本要求先配实际供应商价格，未知价格时拒绝自动付费；异常断连保留最大预留，不盲目退款。
单次 `analyst-check` 是显式连通测试，不属于自动任务账本。

Oracle 官方页面本次核实：A1 2 OCPU/12GB、7 天闲置回收条件；详见 deploy/README。
Playwright ARM64 实际运行未验证。

## M6：分析

用户指定网关按 OpenAI-compatible Chat Completions 传输，自写循环，无自动函数执行。
四项工具：run_sql / get_previous_report / propose_dictionary_entry / submit_report。
只读连接 + authorizer + 单 SELECT + 视图白名单 + 200 行 + 5 秒 VM 超时；
每轮检查 15 轮、总 token、10 分钟和成本预留。工具参数与日报 schema 校验失败不发布。
日报仅允许 ID/纯文本，不允许数字价格、HTML/链接；数字和医院名按 ID 由代码查询历史价格渲染。
别名证据由数据库计算，超过 20 个不同选项才可加入已有项目，不允许模型新增项目。

本轮真实分析接口连通成功：请求 gemini-4-hydrogen-xhigh，响应 gemini-4-hydrogen。
真实生产日报未执行：没有来源数据和已核实费率；离线模拟循环和拒写测试不等于真实日报验收。
原 HANDOFF 指定 google-genai 分析传输，本轮按用户最新明确要求改为兼容网关；抽取传输未改。

## 继续实网前必须具备

1. 本站真实域名，用于具名爬虫 UA。
2. 原生 Gemini 抽取密钥及型号，或用户明确要求另做兼容网关抽取传输。
3. 实际供应商 token 费率（输入、输出），供自动成本上限控制。
4. 选项 DOM / 医院地址 / 券价证据、平台条款；M1 后设计方 100 条金标。
5. 部署主机和运维目标配置。密钥只放环境变量，不贴进源码或前端。

## 最终本机验证

- Python：130 passed，1 skipped（Windows symlink privilege），测试禁止真实网络访问。
- Ruff：检查通过。
- Astro：13 个静态页面构建通过；npm 安装当时审计 0 漏洞。
- 网站：本地服务 127.0.0.1:4321 正常，首页与项目页导航及 390px 无横向溢出已检查。
- live 管线：缺本站 URL 时在首阶段拒绝网络采集并记录失败，不伪称成功。
