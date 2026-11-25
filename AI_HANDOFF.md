# 首尔价研所 · 后续 AI 接手文档

更新日期：2026-11-15（用户时区 Asia/Taipei）。

## 0. 先读这里

用户最新决定：**现阶段先保留现状；江南姐姐留接口槽位、继续禁用；后续测试与补充交给另一个 AI。**
本次交接没有新增抓取、没有伪装搜索引擎、没有启动部署或付费模型任务。

- 项目根目录：仓库根目录（`<repo-root>`）
- 本交接文件：`AI_HANDOFF.md`
- 原始需求：`HANDOFF.md`；没有覆盖原需求。
- 阅读顺序：本文件 → 原始 `HANDOFF.md` → 本文末尾列出的最新进度文档 → 具体代码。
- **不要重新从零搭建，不要覆盖 `.env`、清空数据库或用演示数据替代实采数据。**
- 早期 `docs/M0-delivery.md`、`docs/M1-progress.md`、`docs/M1-M6-delivery.md` 是阶段记录，其中数据量和采集状态可能已过时。
- 当前不是 M0–M6 全部生产验收通过；测试、构建、局部实网验证和生产上线是四种不同状态。

## 1. 产品与用户预期

面向中国顾客的韩国首尔轻医美公开活动价比较网站，中文名“首尔价研所”。
只做首尔、十类皮肤科轻医美，不做手术预约、代收款、医疗质量排行。

十类项目：肉毒素、玻尿酸、美版超声刀、热玛吉、舒立可超声提拉、丽珠兰、水光、皮秒、InMode 射频、黄金微针。

用户特别强调：

1. 要爬真实韩国网站，不要少量示例或虚构报价。
2. 面向中国顾客，不能直接堆韩文和工程字段。
3. Gemini 用于分析，并希望实际检查接口，而不是只配空壳。
4. 参考 PriceAI 的信息组织方式：项目总览、规格、突出价格、来源与日期、条件说明。
5. 江南姐姐现阶段不再继续尝试，保留后续接入位置即可。

实际参考过 https://priceai.io/?home=1 和 https://priceai.io/products/chatgpt-plus 。
采取蓝白布局和总览 → 项目页 → 来源核对的层级，没有复制其品牌素材或制造“官方价/全网最低”基准。

## 2. 交接时真实数据快照

交接时重新以 SQLite 只读连接和前端生成文件核对：

- 实际数据来源：**Yeoshin（女神门票）一站**；数据库 71 个活动全部属于 `yeoshin`。
- sitemap 去重发现：34,901 个活动链接；发现链接不代表抓过、有效、在首尔或已入库。
- 有效活动：71 个。
- 机构：37 家。
- 有效原始活动选项：218 个。
- 规则标准化展示报价：124 条。
- 可计算单位价：28 条；其余不能因显示了总价就视为可直接排名。
- 待复杂抽取：94 个原始选项。
- 已缓存唯一中文译文：319 条；218 个原始选项的中文名称没有缺失。
- 生成机构详情页：24 页，不是 37 页；当前机构详情来自已标准化报价覆盖范围。
- 静态总页数：38（首页、活动、说明、日报共 4 页 + 十项目页 + 24 机构页）。
- 九个项目已有标准化条目；InMode 当前为空，不要补虚构价格。
- 当前人民币参考汇率：2026-11-15，`1 KRW = 0.0049917 CNY`；不是付款保证。
- 日报数据库有 2026-11-15 草稿，`published=0`；当前前端 `report_preview=true`，仅开发预览。

数据为 2026-11-15 的采集记录，不代表接手时仍有效。刷新前应保留观察日期，不能改日期冒充新抓取。

## 3. 技术栈和目录

本机已安装并实测：Python 3.12.16（项目 `.venv`）、Node v24.21.0、npm 11.19.0。
Python 依赖在 `pyproject.toml` / `uv.lock`，前端在 `web/package.json` / `web/package-lock.json`。
Astro 7.4.12 + Tailwind 4.3.5；Scrapy 2.13.3、Pydantic 2.12.5、google-genai 3.3.0。

以下路径均相对仓库根目录：

- `pipeline/`：Python 管线实现。
- `pipeline/config.py`：环境配置及凭据读取。
- `pipeline/sources/`：来源适配器、发现、采集、robots、限速与来源停采。
- `pipeline/extract/`：规则抽取、Gemini 原生抽取、批量、金标评估。
- `pipeline/pricing.py`：含税价、单位价、分桶、分位数、标签。
- `pipeline/localize.py`：展示层中文缓存及数字不变校验。
- `pipeline/analyst/`：兼容网关客户端、受限只读工具、分析循环和日报 schema。
- `pipeline/publish.py`：展示字段白名单、汇率、构建与原子发布。
- `dictionary/procedures.yaml`：项目/品牌/别名词典。
- `migrations/001_initial.sql` 至 `004_localization.sql`：数据库迁移；已执行迁移有哈希校验，不要直接改旧迁移。
- `scripts/`：有界开发实采、规则导入、翻译和分析草稿脚本。
- `web/src/data/generated.json`：当前前端真实数据投影，构建时读取，不是模拟数据。
- `web/src/data/catalog.ts`：项目名、中文标签、来源名、地区、规格、搜索别名与展示辅助函数。
- `web/src/components/OfferCard.astro`：项目页/机构页的报价卡片。
- `web/src/pages/index.astro`：PriceAI 风格项目总览。
- `web/src/pages/activities.astro`：218 个原始选项的中文展示与搜索。
- `web/src/pages/procedures/[id].astro`：十项目、分区与品牌筛选。
- `web/src/pages/clinics/[id].astro`：机构活动页。
- `web/src/pages/report.astro`：开发分析草稿展示。
- `web/src/pages/about.astro`：来源/方法/限制说明。
- `web/src/styles/global.css`：样式；目前是早期样式加消费端改版覆盖，后续可保行为重构。
- `web/dist/`：当前前端静态构建产物；根目录 `dist/` 不是当前网站输出目录。
- `deploy/`：Caddy、systemd、Litestream 模板；不是已经部署运行的证明。
- `tests/`：离线回归；`tests/golden/unlabeled.jsonl` 是 100 条真实未标注样本，**不是金标**。

## 4. 启动、测试与构建

以下均为 Windows PowerShell，从项目根目录执行。不需要先激活虚拟环境。
当前浏览器旧标签不能证明服务仍运行；如果打不开，按命令重启本地服务。不要重复占用 4321 端口。

### 4.1 启动本地开发预览

```powershell
npm.cmd run dev --prefix .\web -- --port 4321
```

预览地址：

- http://127.0.0.1:4321/
- http://127.0.0.1:4321/activities/
- http://127.0.0.1:4321/procedures/ulthera/
- http://127.0.0.1:4321/procedures/botox/
- http://127.0.0.1:4321/report/
- http://127.0.0.1:4321/about/

开发服务是前台进程，`Ctrl+C` 停止。手机断点已做 390px 验证，不需要改成监听公网才能测响应式。

### 4.2 常规回归

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd run build --prefix .\web
```

交接前刚重新执行：Ruff 通过，**164 passed、1 skipped**，Astro **38 页构建成功**。
跳过项为 Windows 目录符号链接权限，不是采集或解析测试失败，也不等于 Linux 原子发布成功。
测试套件禁止真实网络访问；通过测试不代表 Babitalk 或生产采集已验收。

### 4.3 数据投影重新生成

```powershell
.\.venv\Scripts\python.exe scripts/import_verified.py --include-draft
npm.cmd run build --prefix .\web
```

该脚本会幂等导入 `data/verified/yeoshin/` 的事实、重做保守规则抽取、计算并更新前端 JSON；
**会尝试更新汇率网络数据，但不爬活动页、不调用模型**。`--include-draft` 仅供当前开发观察预览。
正式发布去掉该参数并核对报告发布状态；不要把草稿改成“正式日报”来凑验收。
如果 Vite 开发页没显示最新 JSON，重启开发服务；JSON 由模块里的文件读取加载，未必自动热更新。

### 4.4 新机器依赖安装

```powershell
uv sync --frozen --extra dev
npm.cmd ci --prefix .\web
.\.venv\Scripts\pipeline.exe migrate
```

要求 Python 3.12；路径迁移后调整命令。不要将模板 `.env.example` 直接覆盖现有 `.env`。

`pipeline run` / `pipeline step ...` **不带 `--live` 时仍是 scaffold 空流程**；日志成功不能冒充实采。
带 `--live` 才执行真实阶段，但还受域名、时间、费率、来源解析等门禁，不要接手就整条盲跑。

## 5. 数据、备份和 Git

重要文件：

- SQLite：`data/kbeauty.sqlite3`
- 实采事实 JSON：`data/verified/yeoshin/`
- 允许事实快照：`data/snapshots/`
- 扩采进度：`data/yeoshin-expansion-progress.json`
- 中文翻译调用摘要：`data/verified/translation-preview.json`
- 分析草稿调用摘要：`data/verified/analysis-preview.json`
- 江南姐姐 robots 复核：`data/verified/unni-robots-check.json`

交接前以 SQLite backup API 制作了独立一致性备份：

`data/backups/handoff-2026-11-15.sqlite3`

备份大小 6,438,912 字节；备份 `PRAGMA quick_check` 为 `ok`。
原数据库 `quick_check=ok`，外键违规数为 0。不要在运行中只复制主 `.sqlite3` 而漏掉未合并的 WAL；后续快照仍应使用 SQLite backup API。

页面截图：

- `docs/assets/preview-desktop.jpg`
- `docs/assets/preview-mobile.jpg`

**Git 当前还没有任何提交，也没有配置远端。文件大多为未跟踪；尚无可克隆的远端备份。**
`.env`、`data/`、`web/src/data/generated.json`、`.venv/`、`node_modules/` 等被忽略。
交接给同机 AI 直接使用此目录即可。迁移机器时，仅复制 Git 源码会丢真实数据、译文缓存与前端投影；需单独携带上述数据和备份。
`.env` 含凭据，走单独私密配置流程，不放进公开仓库、公开交接附件或前端。

## 6. 江南姐姐：槽位保留，保持禁用

**用户已决定“算了，先这样，槽位留下来”，不要接手后继续尝试伪装代理采集。**

已保留内容：

- `pipeline/sources/unni.py`：`UnniAdapter(SourceAdapter)`、域名 `unni.app`、延迟配置，解析明确抛出 `NotImplementedError`。
- `pipeline/sources/policy.py`：`permitted_url()` 对 `policy.name == 'unni'` 拒绝访问。
- `migrations/001_initial.sql`：`events`、`clinic_sources` 的来源枚举已预留 `unni`。
- `tests/test_m0.py`：已有 `test_unni_disabled` 回归。

这不是“只改开关就能爬”的完整插件：

- `EventFacts.source` 目前只接受 `babitalk`、`yeoshin`。
- `pipeline/collection.py` 来源白名单只允许上述两站。
- `pipeline/sources/crawl.py` 的 `ADAPTERS` 也只有上述两站。
- 前端 `sourceNames` 尚未登记启用的 Unni 来源。

以后具备合适接入条件，再一起补齐 parser、事实 schema、注册与白名单、前端来源名、robots/限速和回归，不要只删除一层禁用保护。

2026-11-15 实际复核 `https://unni.app/robots.txt` 为 HTTP 200；本站自有 UA 适用 `User-agent: * / Disallow: /`。
未请求其内容页、评价、社区或内部 API。复核详情见 `docs/unni-source-check-2026-11-15.md`。

## 7. 采集链路与补充入口

### 女神门票：有真实数据，仍是有界开发采集

- `pipeline/sources/yeoshin.py`：公开 HTML 内嵌 JSON 的活动/选项/机构解析。
- `scripts/verify_yeoshin.py`：早期小范围真实核对脚本。
- `scripts/expand_yeoshin.py --limit 20`：示例为后续显式执行的有界扩采；不是接手自动要运行的命令。
- `scripts/import_verified.py`：实采 JSON → 数据库 → 规则抽取 → 计算 → 站点数据。

开发扩采脚本使用本站名加本地说明页的 UA；没有公开站点域名，因此不应把开发设置原样当生产身份。
生产采集配置仍要求公开 `PIPELINE_SITE_URL`，并在韩国凌晨时间窗运行；本机开发扩采与生产自动采集不要混为一谈。

已有 parser 修复：同 ID 机构摘要字段为空时，仅合并互不冲突的非空字段；不同实际名称或地址仍拒绝。
有些活动同选项 ID 出现不同原价/名称，按事实冲突跳过，不取最低值、不猜成券后价。
不要按中文名字直接去重不同 source option ID，也不要从活动标题强行把品牌套给所有选项。

### Babitalk：下一项真实来源补充工作

已有 `pipeline/sources/babitalk.py` 和采集注册，但真实可购买选项 DOM、地址与价格适配还未验收。
普通 Product 主价不能直接当购买选项价格；先取允许的公开页面做最小验证，再加 fixture/回归和有界导入。
浏览器子资源 robots/限速路径未完善，Playwright 采集当前不启用；不要默认为浏览器已可用于批量采集。

### 继承原始采集约束

- robots 始终开启；Yeoshin 间隔至少 5 秒、Babitalk 至少 3 秒；每域并发 1。
- 不伪装搜索引擎，不做代理/账号轮换，不处理登录或验证码；403/429/验证码触发来源当日停采。
- Yeoshin 不访问 `/api`、`/_next/data`、购物/支付/认证等禁用路径。
- 只保存项目、规格、价格、机构名称地址与来源链接等允许事实；不保存患者评价、昵称、照片或医生个人资料。
- 原始 HTML 仅驻内存，磁盘上的 `raw_snapshots` 实际是事实 JSON，不是完整网页。

## 8. Gemini 与中文化：已实测部分和欠缺

配置只从根目录 `.env` 读取，**本交接不包含密钥值**。
已有分析网关密钥，不要要求用户重复公开粘贴；也不要在调试输出打印整个 Settings 或 `.env`。

- 兼容接口 base URL：在本地 `.env` 的 `PIPELINE_ANALYST_BASE_URL` 配置（示例格式：`https://gateway.example.com/v1`）
- provider：`openai_compatible`
- 请求型号：`gemini-4-hydrogen-xhigh`
- 网关实际返回型号：`gemini-4-hydrogen`；不要声称型号回显证明全部高阶能力已验证。
- 关键配置名：`PIPELINE_ANALYST_PROVIDER`、`PIPELINE_ANALYST_BASE_URL`、`MODEL_ANALYST`、`ANALYST_API_KEY`。
- 原生 Google `GEMINI_API_KEY` 未配置；不要把兼容网关 key 当 Google 原生 key。
- 自动成本费率未配置，自动付费任务应继续 fail closed；网关价格不能套用 Google 零售价格。

### 展示翻译

`scripts/translate_preview.py` 使用兼容网关做真实韩中翻译：319 条唯一文本、10 次调用，总 token 摘要为 105,537；美元费用未知。
缓存表为 `localized_texts`，哈希包含 `zh-CN:v1`，由 `pipeline/localize.py` 在发布投影中附加 `*_zh`。
每次手动调用最多 400 条唯一待译文本、每批 32；明确无工具、无自动重试。
检查 ID/字段/计数、文本长度、禁止链接/HTML、数字 token 多重集合不变；批次任何一条失败不部分写入。
原文改变会换哈希；再生成前端 JSON才显示新增译文。

**译文只是展示层，数字不变并不证明语义、品牌型号或医疗术语完全正确。**
后续重点复核机构音译、设备型号、品牌和套餐条件；中文机构名是参考译名，不是官方认证。
原站宣传标题已收进展开详情并标为原文参考；不要把“根源控油”等源文营销当本站医疗结论。

### 分析草稿与生产分析

- `scripts/analyze_preview.py`：用受限只读视图给 124 条真实结构化样本做有界分析，产出 schema 校验后的草稿；最近摘要 13,746 tokens。
- 草稿没有降价趋势/模型异常证据，因此 `price_drops`、`anomalies` 留空，不补编结论。
- 分析工具只读 SQL、视图白名单、单 SELECT、行数/超时限制；模型无权直接写价格或排名。
- 日报由模型返回 ID 与纯文字，价格/机构原名由代码按 ID 渲染。
- 完整自动分析循环、自动预算与正式发布仍需独立验收；手动草稿不能替代。
- 原生抽取/batch 代码已有离线覆盖，但尚无实际原生密钥和真实批量结果。

## 9. 下一位 AI 建议工作顺序

### P0：先保住当前能用的版本

1. 阅读交接，检查已有备份及数据量，跑 Ruff/pytest/build；不先清数据库或重装覆盖配置。
2. 启动网站检查首页、活动、项目、机构、说明、草稿页；浏览器旧标签不等于后端服务在线。
3. 回归中文搜索、十类快捷筛选、总价排序、原文展开、来源链接和 390px/桌面布局。
4. 保留江南姐姐禁用行为；不要把来源名加上就标成跨平台覆盖。

### P1：数据质量与来源补充

1. 人工或独立核验中文品牌/型号、医院名，保持韩文核对入口。
2. 94 个待复杂抽取项逐类补充；不同套餐、剂量、次数、部位、限制不能强行进入默认比价。
3. 补齐真实 100 条样本的设计方金标，再验收四字段各 ≥95%；`unlabeled.jsonl` 不能直接当 gold。
4. 实页验证 Babitalk 可购买选项，再追加真实样本和回归。
5. 对 Yeoshin 做有界增量，补充当前少样本类别（尤其 InMode），不声称全韩站覆盖。
6. 审核单位价分桶是否需要更细品牌/型号/部位维度；当前“项目 + 档次 + 单位”不是完整医学等价条件。

### P2：生产化

1. 确定兼容网关抽取方案或配置原生 Gemini；确认供应商实际费率及预算口径。
2. 做多日历史、来源下降、失效活动、券价/标价、失败保留旧版的端到端实测。
3. 准备正式域名/联系渠道，Ubuntu ARM64 主机，Caddy、04:00 KST timer、Telegram、healthchecks、对象存储。
4. 实测 Litestream 恢复、Linux 原子发布、失败告警、无人值守连续运行后，才能称生产验收。

## 10. 已做的 UI 验证及已知不足

- 首页、项目、活动在 390px 无页面横向溢出，项目分区标签条允许自身横向滚动。
- 桌面 1440px 首页和活动页无横向溢出。
- 十类快捷筛选已实际点击；全部恢复 218 条，美版超声刀 7、舒立可 8，InMode 0 正确为空。
- 快捷筛选是中韩/品牌别名文本匹配，不是严格结构化分类；套餐可能命中多类，不要把分类计数相加当总数。
- 总价排序只用于原始选项浏览，已明确“非同规格比价”；不是便宜排行。
- 原文/券价/历史展开、机构链接、空结果提示已实点。
- 缺剂量条目放到“规格待确认”；首页有部分总价示例也会明确“规格未齐”。
- 原始选项库还可能包含活动里的加购或非十类辅助选项，不等于 218 个可独立治疗方案；需要进一步标注而不是强行排名。
- 尚无前端自动 E2E 回归；已有浏览器人工工具验证不能代替长期自动测试。
- 尚未所有 37 家机构都生成详情页；原始卡片直接链接来源，避免对未生成页面做错误跳转。
- 样式叠加较多，后续整理时注意不要退回韩文优先或丢掉原文核对/条件标记。

## 11. 最新进度参考

- `docs/chinese-consumer-redesign.md`：中文与 PriceAI 参考改版。
- `docs/expanded-crawl-2026-11-15.md`：扩采数量、失败原因和 parser 修复。
- `docs/real-crawl-2026-11-15.md`：早期实页取证。
- `docs/unni-source-check-2026-11-15.md`：江南姐姐最新复核。
- `deploy/README.md`：未实机验收的部署步骤与边界。

## 12. 可以直接交给下一位 AI 的任务

> 请接手本仓库根目录，先完整阅读 `AI_HANDOFF.md` 和原始 `HANDOFF.md`。
> 不重做项目、不覆盖 `.env`、不清数据库。江南姐姐保留禁用接口，不继续尝试采集。
> 先启动现有中文网站并运行回归，报告真实问题，再按交接中的优先级补数据质量、Babitalk 和生产验收。
> 保留现有真实活动与中文体验，价格和排名由代码计算，密钥不输出，不把开发预览或离线测试说成生产完成。
