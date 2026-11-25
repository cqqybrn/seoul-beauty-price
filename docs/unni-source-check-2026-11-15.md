# 江南姐姐来源复核

2026-11-15，按用户新增请求重新请求 `https://unni.app/robots.txt`，HTTP 200。
本次只请求 robots 文件，没有请求活动、评价、社区、sitemap 或内部 API。

本站实际 User-Agent：`SeoulBeautyPrice/0.1 (+http://127.0.0.1:4321/about/)`。

robots 对若干具名搜索与用户代理允许访问，但对本站适用的规则仍为：

```text
User-agent: *
Disallow: /
```

Protego 对 `/`、`/events`、`/events/1` 的本站代理判定均为 false。
没有将本站代理改成 Googlebot、ChatGPT-User 或其他被列名代理。
按项目 HANDOFF 的 robots 约束，当前不能启用本站自动采集；Unni 适配器维持禁用。
未增加 Unni 报价，既有 Yeoshin 展示数据保持不变。

本地原始规则及检查时间：`data/verified/unni-robots-check.json`（数据目录不提交 Git）。
