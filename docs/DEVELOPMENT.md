# 开发指南

> 版本: 0.2.0 | 更新: 2026-06-24

## 1. 开发环境搭建

### 1.1 前置要求

| 工具 | 版本 | 获取方式 |
|------|------|----------|
| Python | 3.10+ | python.org 或 winget install Python.Python.3.11 |
| Poetry | 1.7+ | `pip install poetry` |
| Git | 2.30+ | git-scm.com |
| MySQL Client | 8.0+ | (可选, 用于备份恢复) |

### 1.2 一键设置

```bash
# Windows
scripts\setup_dev.sh

# 或手动
poetry install
poetry run pytest tests/ -v
```

### 1.3 IDE 推荐配置 (VS Code)

```json
{
  "python.defaultInterpreterPath": ".venv/Scripts/python.exe",
  "python.terminal.activateEnvironment": true,
  "python.testing.pytestArgs": ["tests"],
  "python.testing.unittestEnabled": false,
  "python.testing.pytestEnabled": true,
  "[python]": {
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.organizeImports": true
    }
  }
}
```

## 2. 项目约定

### 2.1 代码风格

- **格式化**: Ruff (兼容 Black 风格), 行宽 100
- **类型注解**: 全部函数使用 `from __future__ import annotations` + 完整类型注解
- **导入排序**: Ruff I (isort 兼容)
- **命名规范**:
  - 类: `PascalCase`
  - 函数/变量: `snake_case`
  - 常量: `UPPER_SNAKE_CASE`
  - 私有: `_prefix`

运行检查:
```bash
poetry run ruff check open_navicat/
poetry run mypy open_navicat/
```

### 2.2 测试规范

```bash
poetry run pytest tests/ -v                       # 全部测试
poetry run pytest tests/unit/ -v                   # 仅单元测试
poetry run pytest tests/ -v --cov=open_navicat    # 带覆盖率
```

测试文件命名: `test_<module>.py`
测试类命名: `Test<Module>`
测试函数命名: `test_<scenario>`

### 2.3 Git 提交规范

```
<type>(<scope>): <description>

<optional body>

Co-Authored-By: AtomCode <noreply@atomgit.com>
```

| Type | 场景 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修复 |
| `docs` | 文档 |
| `refactor` | 重构 |
| `test` | 测试 |
| `chore` | 构建/工具 |

### 2.4 分支策略

```
main          — 稳定版本
  ├── develop  — 开发主线
  │    ├── feat/xxx  — 功能分支
  │    ├── fix/xxx   — 修复分支
  │    └── docs/xxx  — 文档分支
  └── release/x.x — 发布分支
```

## 3. 模块开发流程

### 3.1 添加新服务

1. 在 `open_navicat/services/` 创建 `<name>_service.py`
2. 实现类，单例模式
3. 在 `services/__init__.py` 导出
4. 在 `cli/` 中创建对应的 CLI 命令
5. 编写测试 `tests/unit/test_<name>_service.py`
6. 编写文档 `docs/modules/<name>.md`

### 3.2 添加新 CLI 命令

```python
# examples/cli/example_cmd.py
import typer
from rich.console import Console

example_app = typer.Typer(help="Example commands")
console = Console()

@example_app.command("hello")
def say_hello(
    name: str = typer.Argument(..., help="Your name"),
    uppercase: bool = typer.Option(False, "--uppercase", "-u"),
):
    """Say hello to someone."""
    msg = f"Hello, {name}!"
    if uppercase:
        msg = msg.upper()
    console.print(f"[green]{msg}[/green]")
```

然后在 `cli/app.py` 注册:
```python
from open_navicat.cli.example_cmd import example_app
app.add_typer(example_app, name="example", help="Example commands")
```

### 3.3 添加新数据库支持

1. 在 `dal/` 创建 `xxx_connector.py`，实现 `BaseConnector` 接口
2. 在 `connection_pool.py` 中注册新的连接器工厂
3. 更新 CLI 命令适应新数据库类型

```python
class PostgreSQLConnector(BaseConnector):
    """PostgreSQL connector implementation."""
    async def connect(self) -> bool: ...
    async def list_databases(self) -> list[DatabaseInfo]: ...
    # ... 实现所有抽象方法
```

## 4. 调试指南

### 4.1 本地调试 CLI

```bash
# 直接运行
poetry run opennavicat conn list

# Python 调试
python -m open_navicat.main conn list

# 详细日志
export LOG_LEVEL=DEBUG
poetry run opennavicat query run "SELECT 1"
```

### 4.2 本地调试 GUI

```bash
poetry run opennavicat gui
# 或
export OPENNAVICAT_MODE=gui
poetry run opennavicat
```

### 4.3 AI 模块调试

```bash
# 打印发送给 LLM 的完整 Prompt
export OPENNAVICAT_AI_DEBUG=true

# 测试不通 AI 提供商
export OPENNAVICAT_AI_PROVIDER=openai
export OPENNAVICAT_AI_PROVIDER=ollama
```

## 5. 构建与发布

### 5.1 构建 Python 包

```bash
poetry build                    # 构建 sdist + wheel
poetry publish --dry-run       # 发布测试
```

### 5.2 构建单文件可执行文件

项目提供两个 PyInstaller spec 文件，分别构建 CLI 和 GUI 包：

```bash
pip install pyinstaller

# CLI 包 (~15MB，不含 Qt)
pyinstaller opennavicat-cli.spec

# GUI 包 (~120MB，含 PySide6)
pyinstaller opennavicat-gui.spec
```

产物在 `dist/` 目录：
- `dist/opennavicat-cli` (或 `.exe`) — 纯 CLI
- `dist/opennavicat` (或 `.exe`) — 完整 GUI

## 6. CI/CD

```yaml
# .github/workflows/ci.yml (参考)
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install poetry && poetry install
      - run: poetry run ruff check open_navicat/
      - run: poetry run pytest tests/ -v
```

## 7. 常见问题

### Q: `aiomysql` 在 Windows 上报错？

A: 确保使用 Python 3.10+，安装 `asyncio` 事件循环策略:
```python
import asyncio
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

### Q: mysqldump 命令找不到？

A: 安装 MySQL Client 工具:
- Windows: 下载 MySQL Installer → 勾选 "MySQL Command Line Client"
- 或者使用 `choco install mysql` (需要 MySQL 服务器)

### Q: 如何在无 GPU 机器上使用 AI 功能？

A: 使用远程 API (OpenAI / DeepSeek) 或本地的 ollama (CPU 推理):
```bash
export OPENNAVICAT_AI_PROVIDER=ollama
export OPENNAVICAT_AI_API_BASE=http://localhost:11434
export OPENNAVICAT_AI_MODEL=llama3:8b
```
