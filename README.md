# DownKyi 批量下载脚本

把 Python 端已提取的 BV 号列表逐个送入 [DownKyi 1.6.1](https://github.com/1049451037/DownKyi) 首页输入框，自动走完"解析 → 选清晰度 → 加入下载队列"全流程。

> ⚠️ 重要前提：
> - DownKyi 1.6.1 **不支持命令行参数**，必须由 UI 自动化驱动。
> - 脚本**不会**自动启动 DownKyi；需要先手动启动并登录 B 站。
> - 脚本以管理员权限运行可避免一些焦点切换问题（非必需）。

---

## 快速开始

### 1. 安装依赖

```bash
# 方式 A：uv（推荐）
uv sync

# 方式 B：pip
pip install pywinauto>=0.6.8 pyperclip>=1.8.2
```

### 2. 准备 BV 号列表

编辑 `bv_list.txt`，每行一个 BV 号或完整 URL（也支持 `#` 注释与空行）：

```text
# 单 P 视频
BV1xx411c7mD

# 完整 URL
https://www.bilibili.com/video/BV1yy522d8nE?p=1

# 分 P 视频（脚本会自动选"全部解析"，下载所有分 P）
BV1zz1111aa1
```

### 3. 启动 DownKyi 并登录

打开 `DownKyi.exe`，登录你的 B 站账号（部分视频需要登录才能下载）。

### 4. 运行脚本

```bash
# dry-run：只打印计划，不操作 UI（推荐先跑一次）
uv run python bulk_download.py --dry-run

# 真正运行：默认处理 bv_list.txt 中所有 BV
uv run python bulk_download.py

# 指定文件 + 限制前 N 个（用于测试）
uv run python bulk_download.py my_bvs.txt --limit 3
```

### 5. 验证

- DownKyi 主窗口：打开"下载管理"页，能看到脚本加入的任务
- 控制台日志：每个 BV 一行 ✓ 或 ✗
- `download_log.txt`：每条 `OK` 或 `FAIL` 记录，便于重跑时跳过已成功的

---

## CLI 参数

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `bv_file` | BV 号文件路径 | `bv_list.txt` |
| `--limit N` | 最多处理前 N 个 BV | 全部 |
| `--dry-run` | 仅打印计划，不操作 UI | 关 |
| `--log PATH` | 日志文件路径 | `download_log.txt` |

退出码：

| 退出码 | 含义 |
| --- | --- |
| 0 | 全部成功 |
| 1 | 有失败（部分 BV 解析/下载失败，但流程跑完） |
| 2 | BV 号文件加载失败（文件不存在/为空/无有效 BV） |
| 3 | 连接 DownKyi 失败（未启动/启动中） |
| 4 | 等待首页失败（网络/登录态异常） |

---

## 工作流程

对每个 BV：

```
首页输入框
  ↓ type_keys + Enter
视频详情页
  ↓ 点击"下载选中"
清晰度选择对话框（ViewParsingSelector）
  ↓ 勾选"设为默认" + 点"全部解析"
下载设置对话框（ViewDownloadSetter）
  ↓ 沿用默认设置，点"下载"
  ↓ 任务加入下载队列
回到首页（等返回按钮生效或解析失败超时）
```

对分 P 视频：脚本会在清晰度对话框自动选"全部解析"，下载所有分 P。

---

## 故障排查

### 找不到 DownKyi 窗口
- 确认 DownKyi.exe 正在运行
- 窗口标题是否包含 "DownKyi"（见 `config.WINDOW_TITLE_RE`）
- 用 `pywinauto.findwindows.find_windows(title_re="DownKyi")` 调试

### 等待详情页超时
- 检查 B 站登录态（未登录会触发风控）
- 网络是否可达
- 在 DownKyi 主窗口手动输入一次该 BV 看是否成功

### 控件 ID 失效（升级后）
所有控件 ID 集中在 `config.py`，修改一处即可。

### 中文路径 / 含空格路径
脚本已使用 `pathlib.Path` 处理，不会出现引号转义问题。

### 中文日志乱码（仅 Windows cmd）
在执行前设置 `PYTHONIOENCODING=utf-8`：
```bash
set PYTHONIOENCODING=utf-8
uv run python bulk_download.py
```
或直接用 Windows Terminal / VSCode 终端。

---

## 开发

### 运行单元测试

```bash
uv run pytest tests/ -v
```

### 项目结构

```
scripts/
├── bulk_download.py      # CLI 入口
├── downkyi_client.py     # DownKyi UI 自动化封装
├── bv_loader.py          # BV 号文件解析
├── config.py             # 常量与控件 ID
├── pyproject.toml        # uv 项目配置
├── bv_list.txt           # 用户填入的 BV 列表
├── download_log.txt      # 自动生成的成功/失败日志
├── tests/
│   ├── test_bv_loader.py
│   ├── test_bulk_download.py
│   └── fixtures/         # 测试用临时文件
└── README.md
```

### TDD 流程

1. 先在 `tests/` 写失败测试（红）
2. 在对应模块写最小实现（绿）
3. 重构，保持测试通过

---

## 已知限制

- 不支持自定义下载目录/清晰度/分辨率/编码——一律沿用 DownKyi 上次保存的默认设置
- 不支持"按需选分 P"——分 P 视频默认下载所有分 P
- 不支持自定义登录/扫码——依赖用户提前登录
- 多个 DownKyi 实例时只连第一个（z-order 顶端）
