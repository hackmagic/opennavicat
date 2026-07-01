<div align="center">

# Contributing to OpenNavicat

Thank you for your interest in contributing!

[English](#english) | [简体中文](#简体中文)

</div>

---

## English

### How to Contribute

1. **Fork** the repository
2. **Clone** your fork: `git clone https://github.com/your-username/OpenNavicat.git`
3. **Create** a feature branch: `git checkout -b feature/my-feature`
4. **Make** your changes
5. **Test** your changes: `poetry run pytest tests/unit/ -v`
6. **Lint** your code: `poetry run ruff check open_navicat/`
7. **Commit** your changes: `git commit -m "feat: add my feature"`
8. **Push** to your fork: `git push origin feature/my-feature`
9. **Open** a Pull Request

### Development Setup

```bash
# Clone the repo
git clone https://github.com/hackmagic/OpenNavicat.git
cd OpenNavicat

# Install dependencies
poetry install

# Run tests
poetry run pytest tests/unit/ -v

# Run linter
poetry run ruff check open_navicat/

# Run the app
poetry run opennavicat          # CLI mode
poetry run opennavicat gui      # GUI mode
```

### Code Standards

- **Python**: 3.10+ with `from __future__ import annotations`
- **Type hints**: Full type annotations required
- **Line length**: 100 characters max
- **Linting**: Ruff (select `E,F,I,N,W`)
- **Testing**: pytest with `asyncio_mode = auto`
- **i18n**: Use `t("key")` for all user-facing strings

### Commit Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat:     New feature
fix:      Bug fix
docs:     Documentation changes
style:    Code style changes (formatting, etc.)
refactor: Code refactoring
test:     Adding or updating tests
chore:    Maintenance tasks
```

### Pull Request Guidelines

- Keep PRs focused on a single change
- Include tests for new features
- Update documentation if needed
- Ensure all tests pass before submitting
- Write a clear PR description

### Reporting Issues

- Use GitHub Issues
- Include steps to reproduce
- Include Python version and OS
- Include error messages/screenshots

### Areas for Contribution

- **PostgreSQL connector** — Multi-database support
- **Integration tests** — Tests with real databases
- **Performance** — Large dataset optimization
- **Documentation** — Translations, tutorials
- **UI/UX** — Accessibility, keyboard shortcuts

---

## 简体中文

### 如何贡献

1. **Fork** 本仓库
2. **克隆** 你的 Fork：`git clone https://github.com/你的用户名/OpenNavicat.git`
3. **创建** 功能分支：`git checkout -b feature/我的功能`
4. **进行** 修改
5. **测试** 修改：`poetry run pytest tests/unit/ -v`
6. **检查** 代码：`poetry run ruff check open_navicat/`
7. **提交** 修改：`git commit -m "feat: 添加我的功能"`
8. **推送** 到你的 Fork：`git push origin feature/我的功能`
9. **发起** Pull Request

### 开发环境

```bash
# 克隆仓库
git clone https://github.com/hackmagic/OpenNavicat.git
cd OpenNavicat

# 安装依赖
poetry install

# 运行测试
poetry run pytest tests/unit/ -v

# 代码检查
poetry run ruff check open_navicat/

# 运行应用
poetry run opennavicat          # CLI 模式
poetry run opennavicat gui      # GUI 模式
```

### 代码规范

- **Python**: 3.10+，使用 `from __future__ import annotations`
- **类型注解**: 完整类型注解
- **行宽**: 最大 100 字符
- **代码检查**: Ruff (select `E,F,I,N,W`)
- **测试**: pytest，`asyncio_mode = auto`
- **国际化**: 所有用户可见字符串使用 `t("key")`

### 提交规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```
feat:     新功能
fix:      修复 Bug
docs:     文档修改
style:    代码格式修改
refactor: 代码重构
test:     测试相关
chore:    构建/工具相关
```

### Pull Request 指南

- 保持 PR 聚焦于单一修改
- 新功能需包含测试
- 必要时更新文档
- 提交前确保所有测试通过
- 清晰描述 PR 内容

### 问题反馈

- 使用 GitHub Issues
- 包含复现步骤
- 包含 Python 版本和操作系统
- 包含错误信息/截图

### 欢迎贡献的方向

- **PostgreSQL 连接器** — 多数据库支持
- **集成测试** — 真实数据库测试
- **性能优化** — 大数据量渲染
- **文档翻译** — 多语言支持
- **UI/UX** — 无障碍、快捷键
