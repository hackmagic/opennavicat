# 部署与打包指南

> 更新: 2026-07-03

## 1. 快速安装 (终端用户)

### 1.1 通过 pip (推荐 — 包含 CLI 和 GUI)

```bash
pip install open-navicat

# CLI 模式
opennavicat conn list

# GUI 模式
opennavicat gui
```

### 1.2 通过 Poetry (开发版)

```bash
git clone https://github.com/hackmagic/OpenNavicat.git
cd OpenNavicat
pip install poetry
poetry install

# CLI 模式
poetry run opennavicat conn list

# GUI 模式
poetry run opennavicat gui
```

### 1.3 直接下载可执行文件

从 [GitHub Releases](https://github.com/hackmagic/OpenNavicat/releases) 下载最新版。每个平台提供两个包：

| 包 | 说明 | 体积 |
|----|------|------|
| `opennavicat-cli-*` | 纯 CLI，不含 Qt | ~15 MB |
| `opennavicat-*` | 完整 GUI，含 PySide6 | ~120 MB |

```bash
# 下载 CLI 版
curl -LO https://github.com/hackmagic/OpenNavicat/releases/download/v0.7.0/opennavicat-cli-linux-x64
chmod +x opennavicat-cli-linux-x64
./opennavicat-cli-linux-x64 --version
```

## 2. 构建指南

### 2.1 构建 Python Wheel

```bash
poetry build
ls dist/
# open_navicat-0.7.0-py3-none-any.whl
# open-navicat-0.7.0.tar.gz
```

### 2.2 构建单文件可执行文件

使用 PyInstaller spec 文件构建：

```bash
pip install pyinstaller

# CLI 包 (不含 Qt，~15MB)
pyinstaller opennavicat-cli.spec

# GUI 包 (含 PySide6，~120MB)
pyinstaller opennavicat-gui.spec
```

产物在 `dist/` 目录：
- `dist/opennavicat-cli` (或 `.exe`)
- `dist/opennavicat` (或 `.exe`)

### 2.3 Docker 镜像

项目管理一个 [Dockerfile](../Dockerfile) 用于构建轻量级 CLI 镜像。

```bash
# 从 GitHub Packages 拉取
docker pull ghcr.io/hackmagic/opennavicat:latest

# 运行 CLI
docker run --rm ghcr.io/hackmagic/opennavicat conn list

# 带 AI 支持 (配合 Ollama)
docker run --rm \
  -e OPENNAVICAT_AI_PROVIDER=ollama \
  -e OPENNAVICAT_AI_API_BASE=http://host.docker.internal:11434 \
  ghcr.io/hackmagic/opennavicat ai ask "show me all databases"
```

本地构建:
```bash
docker build -t opennavicat .
docker run --rm opennavicat conn list
```

## 3. CI/CD 流水线

### GitHub Actions

项目使用两个 workflow 文件：

- **`release.yml`** — 打 tag 时触发，构建 CLI + GUI 双包，上传到 GitHub Release
- **`publish.yml`** — Release 发布后触发，自动发布到 PyPI

详见 [`.github/workflows/`](https://github.com/hackmagic/OpenNavicat/tree/master/.github/workflows)。

## 4. 配置指南

### 4.1 配置文件位置

| 平台 | 配置目录 |
|------|----------|
| Windows | `%APPDATA%/OpenNavicat/` |
| macOS | `~/Library/Application Support/OpenNavicat/` |
| Linux | `~/.config/OpenNavicat/` |

结构:
```
OpenNavicat/
├── settings.json           # 应用设置
├── data/
│   ├── connections.sqlite  # 连接配置 (密码加密)
│   └── .machine_key        # 加密密钥 (自动生成)
└── logs/                   # 日志文件
```

### 4.2 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENNAVICAT_AI_PROVIDER` | AI 提供商 | openai |
| `OPENNAVICAT_AI_API_KEY` | API 密钥 | — |
| `OPENNAVICAT_AI_API_BASE` | API 地址 | 按提供商 |
| `OPENNAVICAT_AI_MODEL` | 模型名 | gpt-4o-mini |
| `OPENNAVICAT_MODE` | 启动模式: cli/gui | cli |
| `OPENNAVICAT_CONFIG_DIR` | 配置目录 | 按平台默认 |
| `OPENNAVICAT_AI_DEBUG` | AI 调试日志 | false |

## 5. 系统要求

| 要求 | 最小 | 推荐 |
|------|------|------|
| Python | 3.10 | 3.11+ |
| 内存 (CLI) | 128MB | 512MB |
| 内存 (GUI) | 512MB | 1GB+ |
| 内存 (AI 本地) | — | 8GB+ (Ollama) |
| 磁盘空间 | 200MB | 500MB |
| MySQL Client | 8.0 (可选) | 8.0+ |

## 6. 升级指南

```bash
# pip 安装
pip install --upgrade open-navicat

# Poetry 开发版
git pull
poetry install

# 可执行文件
# 下载新版本替换旧文件即可
# 配置和数据自动保留在 %APPDATA%/OpenNavicat/
```

## 7. 卸载

```bash
# pip 安装
pip uninstall open-navicat

# Poetry
poetry env remove

# 清理数据 (可选)
rm -rf ~/.config/OpenNavicat/   # Linux
rm -rf ~/Library/Application\ Support/OpenNavicat/  # macOS
rm -rf %APPDATA%/OpenNavicat/   # Windows

# 可执行文件
# 直接删除文件即可
```
