# OCUOC

Clean-room Windows computer-use MCP. Independent implementation — no OpenAI account, no closed-source helper.

Windows 上的干净室 computer-use MCP：给 Cursor / VS Code 等 MCP 宿主提供窗口作用域的截屏、UI Automation 和输入工具。协议是公开的 MCP stdio，实现从零编写。

## 能做什么

- 枚举显示器、可见顶层窗口、可启动应用
- 捕获**窗口客户区**截图（MCP `Image`）；坐标相对该图左上角
- 读 UIA / WebView 元素树，按 `element_index` 或截图像素点击、输入、滚动、拖拽
- `generation` 校验：窗口 ident 变了就拒绝过期操作
- 协作：AI 操作时隐藏系统光标，桌面上显示独立 overlay 指针；物理 **Esc** 中止本轮输入（MCP 进程不退出）
- 不接 ChatGPT / Codex 账号层，不做应用允许名单，不拦截 UAC 安全桌面

可选：若环境里装了 `dxcam`，截屏优先走 DXGI，否则自动回落 mss / PrintWindow / BitBlt。

## 要求

- Windows 10/11
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

工具进程应按**管理员**运行，才能：

- 点高完整性窗口（UIPI）
- 枚举其他用户会话里的进程（`list_windows` 带 `user` / `integrity`）
- 抓/点当前桌面上的提权窗

做不到：屏幕变暗的安全桌面 UAC（`WinSta0\Winlogon`）。检测到会返回 `uac_secure_desktop: true`。MCP 子进程继承宿主完整性：要用管理员跑 MCP，请以管理员启动 Cursor，或用 `scripts/ocuoc-admin.ps1`。

未提升时结果会带 `elevated: false` 和警告，不会静默失败。

## 安装

```powershell
git clone https://github.com/ZUENS2020/OCUOC.git
cd OCUOC
uv sync
```

前台跑 MCP：

```powershell
uv run ocuoc
```

## Cursor / VS Code

把仓库路径换成你的本地目录：

```json
{
  "mcpServers": {
    "ocuoc": {
      "command": "uv",
      "args": ["--directory", "C:/path/to/OCUOC", "run", "ocuoc"]
    }
  }
}
```

或直接用 venv 里的解释器：

```json
{
  "mcpServers": {
    "ocuoc": {
      "command": "C:/path/to/OCUOC/.venv/Scripts/python.exe",
      "args": ["-m", "ocuoc"]
    }
  }
}
```

## 工具约定

| 约定 | 说明 |
|---|---|
| `window_id` | `hwnd:<十进制>` |
| `generation` | 窗口 ident；变了就拒绝写入 |
| 坐标 | `get_window_state` / `screenshot_desktop` 返回图的像素；客户区点击必须带该窗最新 `screenshot_id` |
| Esc | 物理 Esc 中止本轮输入；AI 的 `SendInput` 带注入标记，不会误中止 |
| 人为接管 | 人在目标窗上的物理点击会中断 AI；下次 `get_window_state` 带 `human_takeover` |

工具一览：`list_apps`、`list_windows`、`list_displays`、`get_window`、`get_window_state`、`screenshot_desktop`、`activate_window`、`launch_app`、`wait_for_window`、`close_window`、`click`、`type_text`、`press_key`、`hold_key`、`scroll`、`drag`、`mouse_down`、`mouse_up`、`set_value`、`move_pointer`、`perform_secondary_action`。

## 测试

```powershell
uv run pytest tests -q
uv run pytest tests -m live -q
```

`-m live` 会驱动真实 GUI（记事本等）。

## 项目结构

```
src/ocuoc/          MCP server、引擎、Win32 / UIA / 截屏 / 输入
tests/              单元测试与可选 live 测试
scripts/            管理员启动包装
```

这是独立的干净室学习实现，不是任何闭源 computer-use 组件的再分发或包装。
