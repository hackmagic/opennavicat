# 模块依赖矩阵

> 由 `scripts/build_dependency_matrix.py` 自动生成——不要手改这份表格。
>
> 运行：`python scripts/build_dependency_matrix.py`

## 分层约定

| 层 | 包 | 规则 |
| --- | --- | --- |
| 0 | `models/`, `errors` | 无内部依赖（models / errors） |
| 1 | `drivers/`, `dal/`, `utils/`, `config/`, `i18n` | 基础设施（drivers / dal / utils / config） |
| 2 | `services/`, `plugin/`, `plugins` | 业务服务（services / plugin） |
| 3 | `app/`, `main/`, `cli_main/`, `gui_main` | 入口层（cli / ui） |

允许方向：**只能依赖同层或更低层**。从低层指向高层的边就是违规。

## 依赖矩阵（边数）

| 依赖方 \ 被依赖方 | open_navicat | app | cli | config | dal | drivers | errors | i18n | models | plugin | plugins | services | ui | utils |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| open_navicat | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| app | 1 | · | · | 1 | · | · | · | · | · | · | · | · | 1 | · |
| cli | · | · | 11 | 1 | 1 | 2 | 1 | · | 1 | · | · | 11 | · | 8 |
| config | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| dal | · | · | · | 1 | 1 | 10 | 1 | · | 3 | · | · | · | · | · |
| drivers | · | · | · | · | · | 10 | 9 | · | 10 | · | · | · | · | · |
| errors | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| i18n | · | · | · | 1 | · | · | · | · | · | · | · | · | · | · |
| models | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| plugin | · | · | · | · | · | · | · | · | · | 1 | · | · | · | · |
| plugins | · | · | · | · | · | · | · | · | · | 2 | · | · | · | · |
| services | · | · | · | · | 11 | 1 | 1 | · | 9 | · | · | 1 | · | 2 |
| ui | 1 | · | · | 4 | 23 | 2 | 2 | 30 | 8 | · | · | 18 | 33 | 1 |
| utils | · | · | · | 1 | · | · | · | · | 1 | · | · | · | · | · |

统计：扫描到 **237** 条包内导入边，覆盖 **14** 个顶层模块。

## 违规清单

**无违规**——所有导入都指向同层或更低层。

