# 韩站真实采集接通记录

## 实际结果

2026-11-15 手动开发验证，不是凌晨自动生产任务。

Scrapy 抓取女神门票韩文活动页，robots 开启，串行，固定间隔 5.1 秒，
无登录、无 API/`_next/data` 请求、无代理、无 JS 执行。
User-Agent 是本站开发名，联系页指向当前实际运行的本机预览页；未伪造公网域名。
正式定时采集仍保持真实公网联系 URL 门禁，开发小样本验证不受此上线门禁阻止。

成功解析：

- 29421：플래티넘의원，首尔，3 选项。
- 37013：본라인한의원(을지로점)，首尔，5 选项。
- 30145：다미온의원，非首尔，3 选项；按首尔规则未入活动库。

合计入库 **2 个活动、2 家机构、8 个可购买选项**。
对字段冲突的其他页不猜测，保留跳过；首个 sitemap 的旧活动样本多数已非公开有效活动，不强行收录。
原 sitemap 仍包含下线活动，因此“出现在 sitemap”并不足以证明活动可售。

## 页面数据来源

HTTP HTML 内嵌 `self.__next_f.push` 的 JSON 字符串，使用 json.loads 解码，不执行脚本。
匹配当前 salesEvent / hospital / salesProducts 的 ID，拒绝同页推荐活动误归属。
过滤失活选项；base `price` 与 `discountPrice` 分列；`oneTimeRegularPrice` 不是划线总价，不误填。
重复 UI 投影的优惠价可能等于原价；在基础字段完全一致时优先保留 explicit discountable 投影。
医院 `kahf` 的确切含义尚未验证，foreign_patient_registered 保持 null，不擅自判真。

300 发样本：option 415238，标价 ₩890,000，券后 ₩853,000。
600 发样本：option 415237，标价 ₩1,690,000，券后 ₩1,653,000。
100 发样本：option 415239，标价 ₩320,000，券后 ₩297,000。

HTML 只留内存；磁盘只保存允许的事实 JSON 快照。一个最小事实投影 fixture 已纳入离线回归，
不保存评价、用户昵称、前后照或医生个人资料。

## 本地展示

`scripts/import_verified.py` 幂等入库，严格规则仅解析明确的单品牌/剂量/次数/含税事实。
provenance 为 `rule:explicit-dose-v1`，未伪称 Gemini 抽取，不代表 M2 金标 95% 验收。
本批 8 个选项均满足窄规则，已生成单位价。样本不足十条，全部 unranked，仅排序不评便宜/贵。
跨项目不混比；3 次卡用总价除次数与每次剂量。
本地前端读 allowlisted generated.json，新增两个真实机构静态页，共 15 页。
肉毒素暂时仍无数据，没有将超声刀活动塞进肉毒素分类。

## 来源规则与条款实际核实

- 女神门票 robots：允许公开页，Crawl-delay=5，api / _next/data 禁止。
- `sales_event_0.xml.gz`：5,000 条 URL，5,000 条 lastmod；样本为 2026-11-14。
- 江南姐姐 `https://unni.app/robots.txt`：普通本站爬虫仍 `Disallow: /`，没有抓活动页。
- 真实条款链接：https://www.yeoshin.co.kr/policy/termsOfService
- 条款第 24 条含未经事先同意不得为营利目的复制/传送其知识产权信息的条文；
  第 9 条禁止自动程序等非正常用法造成服务负载/干扰。
- 详情页底部另有针对未经许可复制、分发、传输、scraping 的禁止声明。
  将这些事实交站长处理；此次验证不等于平台对商业比价再发布的授权。

## 实网发现并修复的依赖问题

Scrapy 2.13.3 与自动解析到的 Twisted 26.10.0 不兼容：TLS 下载器导入缺失
`_setAcceptableProtocols`。此前纯离线业务测试没有覆盖下载器导入。
已固定 Twisted 25.5.0，增加 HTTP11 下载器导入回归；实际 Scrapy HTTPS 抓取成功。
此故障在网络请求前触发，仅清除了该次本机 import failure 产生的 robots_download_error 状态；
未清除 403/429/验证码停采状态，未进行反爬绕过。
