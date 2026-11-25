# M0 交付说明

日期：2026-11-15（项目统一 Asia/Seoul）。

## 完成范围

1. 初始化 Git 仓库，保留原交接文档，忽略密钥、虚拟环境、数据库和运行快照。
2. 安装项目专用 Python 3.12.16，不改动主机已有 Python 3.11。
3. 建立 pyproject、可安装 CLI、uv.lock 和独立 dev / browser 依赖组。
4. 初始 SQL 迁移包含交接数据表、分析只读视图及发现记录、来源停采状态、告警 outbox。
5. 迁移使用事务及 SHA256 校验；SQLite 开启 WAL、外键和忙等待；只读连接禁止写入。
6. 建立严格校验的十项目 YAML 词典：别名、品牌分档、单位、剂量边界。剂量界限只是工程预筛参数，不是医疗建议。
7. 配置从环境变量 / 本地 .env 读取；密钥类型隐藏 repr，不输出配置原值；KST 时区固定。
8. 八阶段空流程与独立 step 命令均落 run_log；失败后不继续后续阶段。
9. `unni.app` 仅保留接口并抛 NotImplementedError。Yeoshin 保留 M4 未就绪接口。

## 验证

测试完全离线，socket 连接被测试 fixture 禁止。
覆盖迁移重复运行、修改检测、事务回滚、外键、WAL、只读连接、视图字段、词典范围、配置、
CLI 空流程、每一阶段独立执行与失败短路。

最终验证：`pytest -q` **56 passed**；`ruff check .` **All checks passed**；
`uv sync --frozen --extra dev` 成功；`uv build` 成功生成 sdist 和 wheel，
并检查 wheel 确实包含词典与迁移资源。已实际运行完整空流程与独立 discover，
检查 SQLite run_log 中存在成功记录；`run --live` 按预期失败并留下失败记录。

空管线完成后 `run_log` 每次新增八行，均明确标记 scaffold / implemented=false；不写假活动、假排名、假日报。

## 尚未完成

M1–M6 的 live 业务验收不在 M0 完成范围内。没有创建虚假的 AI 金标、部署文件或前端成品来冒充后续里程碑。
