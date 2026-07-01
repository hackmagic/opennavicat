# 部署与打包指南

> 版本: 0.2.0 | 更新: 2026-06-24

## 1. 快速安装 (终端用户)

### 1.1 通过 pip (推荐)

```bash
# 从 PyPI 安装
pip install open-navicat

# 验证
opennavicat --version

# 配置 AI (可选)
export OPENNAVICAT_AI_PROVIDER=openai
export OPENNAVICAT_AI_API_KEY=sk-xxxx
```

### 1.2 通过 Poetry (开发版)

```bash
git clone https://github.com/opennavicat/opennavicat.git
cd opennavicat
pip install poetry
poetry install

# CLI 模式
poetry run opennavicat conn list

# GUI 模式
poetry run opennavicat gui
```

### 1.3 直接下载可执行文件

从 GitHub Releases 下载最新版:

| 平台 | 文件 | CLI/GUI |
|------|------|---------|
| Windows x64 | `opennavicat-win64.exe` | 默认 CLI, `opennavicat-gui.exe` 为 GUI |
| macOS x64 | `opennavicat-macos-x64` | 同上 |
| macOS arm64 | `opennavicat-macos-arm64` | 同上 |
| Linux x64 | `opennavicat-linux-x64` | 同上 |

```bash
# 下载后
chmod +x opennavicat-linux-x64
./opennavicat-linux-x64 --version
```

## 2. 构建指南

### 2.1 构建 Python Wheel

```bash
poetry build
ls dist/
# open_navicat-0.1.0-py3-none-any.whl
# open-navicat-0.1.0.tar.gz
```

### 2.2 构建 CLI 单文件可执行文件

#### Windows (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --onefile --name opennavicat open_navicat/main.py
# dist/opennavicat.exe (约 30-50MB)
```

#### Windows (Nuitka — 更小更快)

```bash
pip install nuitka
nuitka --standalone --onefile --output-dir=dist --enable-plugin=pyside6 open_navicat/main.py
# dist/opennavicat.exe (约 15-25MB)
```

#### macOS

```bash
pyinstaller --onefile --name opennavicat open_navicat/main.py
# 或使用 nuitka (同上)
# 签名:
codesign --sign "Developer ID Application: YourName" dist/opennavicat
```

#### Linux

```bash
pyinstaller --onefile --name opennavicat open_navicat/main.py
# AppImage 方式:
# 使用 python-appimage 或 linuxdeploy
```

### 2.3 构建 GUI 可执行文件

```bash
pyinstaller --onefile --windowed --name "OpenNavicat-GUI" open_navicat/main.py

# macOS 需要额外处理 .app 包
pyinstaller --onefile --windowed --name "OpenNavicat" --icon=icon.icns open_navicat/main.py
```

### 2.4 Docker 镜像

```dockerfile
FROM python:3.11-slim

RUN pip install open-navicat

# CLI 模式 (无头服务器)
ENTRYPOINT ["opennavicat"]

# 或带 AI 支持
ENV OPENNAVICAT_AI_PROVIDER=ollama
ENV OPENNAVICAT_AI_API_BASE=http://ollama:11434
```

构建和运行:
```bash
docker build -t opennavicat .
docker run --rm opennavicat conn list
docker run --rm opennavicat ai ask "What databases do I have?"
```

## 3. CI/CD 流水线

### GitHub Actions

```yaml
name: Build and Release
on:
  push:
    tags: ["v*"]

jobs:
  build:
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install poetry pyinstaller
      - run: poetry install
      - run: pyinstaller --onefile --name opennavicat open_navicat/main.py
      - uses: actions/upload-artifact@v4
        with:
          name: opennavicat-${{ matrix.os }}
          path: dist/opennavicat*

  release:
    needs: [build]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
      - name: Create Release
        uses: softprops/action-gh-release@v1
        with:
          files: opennavicat-*/
```

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
