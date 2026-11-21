# NuPhy Agent Lights

给 NuPhy Air75 V3 做一个 Agent 状态灯。首个目标设备是月虹白特别版，ANSI 布局，官方固件 `2.0.0.7`。

第一版面向这台 Mac 上运行的 Codex 和 Claude Code，各覆盖 Desktop 和 CLI。设计上用按键背光区分来源，用两侧灯条提醒用户是否需要回来处理。当前已完成 USB 只读探测和客户端接口调研，控制器与四个入口的端到端验证待实现。

## 键盘实测与灯区分工

2026-11-21，用 NuPhy Lab 的 Swift HID 桥对连接中的键盘执行 `connect`、`readColors` 和 `quit`。实机报告 USB `19f5:1028`、Air75 V3 ANSI、固件 `2.0.0.7`、Mac 灯光配置、22 字节灯效状态，并成功读出 104 个 RGB 值。该版本桥接器识别出 84 个逐键灯位和 20 个侧灯灯位；原厂协议给左右灯条提供一套共同的颜色和效果。本次实测只读取设备，写灯和恢复仍需验证。[NuPhy Lab 对该固件的适配说明](https://github.com/bohu8264/NuPhyLab-next/blob/1f1ae72dad5e61e363860fb34a2df00407b483bb/docs/RELEASE_1.2.50.md)

建议初始键位用 F1 表示 Codex、F2 表示 Claude Code。同一产品的多个会话在对应键上汇总，Desktop 和 CLI 可同时使用。运行中亮低亮蓝灯，等人操作亮琥珀色，本轮结束短亮绿灯。两侧灯条一同显示全局最高优先级，等待高于运行，运行高于结束提示。这样一个会话结束时，另一会话的等待提示仍然可见。全部空闲后恢复接管前的键盘灯效。亮度需在月虹白的雾透键帽上目视校准。

## Desktop 和 CLI 怎样接入

| 本地入口 | 事件来源 | 接入细节 |
| --- | --- | --- |
| Codex Desktop、Codex CLI | 用户级 `$CODEX_HOME/hooks.json`，默认 `~/.codex/hooks.json` | 两个入口共用配置。Desktop 可从 Settings → Hooks 审阅，CLI 使用 `/hooks`。本机 CLI `0.153.0` 已启用 hooks，且其协议包含下述事件。[OpenAI 官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks) |
| Claude Desktop 的 Code 标签页、Claude Code CLI | 用户级 `~/.claude/settings.json` 内的 `hooks` | 本地 Code 会话和 CLI 共享 hook 配置。本机 CLI 版本为 `2.1.259`。SSH 或云端执行需另外把远端事件送回这台 Mac。[Desktop 与 CLI 的配置共享](https://code.claude.com/docs/en/desktop#shared-configuration) · [Claude Code Hooks](https://code.claude.com/docs/en/hooks) |

两份配置各调用一个轻量命令，显式传入产品名。命令从标准输入的 JSON 提取事件名、会话 ID 和可用的轮次、工具调用标识，通过本机 Unix socket 交给单一控制器后返回。控制器按需启动并独占灯光写入。安装时合并已有 hook。灯控命令只报告状态，审批仍由客户端处理。首版按本地执行设计，Codex 云端编排不能运行这个本地命令。[OpenAI 官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)

- **开始与结束**：`UserPromptSubmit` 开始一轮，主会话 `Stop` 触发短暂结束提示。绿色只表示本轮结束。Claude 的 `StopFailure` 可单独提示 API 错误。Codex 的 `Interrupt` 清除被中断轮次，`SessionEnd` 移除对应会话。
- **等人操作**：`PermissionRequest` 标记待审批；同步提问可通过 `PreToolUse` 匹配客户端实际暴露的提问工具，例如 Claude 的 `AskUserQuestion`。匹配的工具返回时清掉该等待项；Claude 同时处理 `PostToolUseFailure`。异步提问仍允许任务继续运行。未收到终止事件的会话需要过期清理。
- **并行会话**：按产品和 `session_id` 隔离状态。Codex 再按 `turn_id` 归并；Claude 可用每次提交建立本地轮次。Codex 的审批事件未提供工具调用 ID，同一轮内重叠的同名请求需保守归并，无法唯一配对时保留等待至轮次结束或过期。可区分的待处理请求分别计数，普通工具返回、子代理结束和上一轮迟到的事件都不能清掉另一项等待。

## macOS 灯控实现

1. 通过用户态 `IOHIDManager` 打开有线设备的 64 字节配置接口（usage page 1、usage 0）。按当前 Mac/Win 配置读取固件、灯位数量、灯效和 RGB。切换模式前保存原灯效，首次改色前备份自定义调色板。
2. 按键背光使用自定义灯效 21，通过 `D8` 分包更新 0–83 号灯位，首帧用 `D2` 回读。此模式接管整块背光，需要给其他键确定背景色。首版用低亮静态背景，按状态变化写入。
3. 两侧灯条使用 `D6` 从偏移 9 写入 8 字节侧灯设置，通过 `D5` 回读。这样可以单独改变侧灯并保留主灯设置。硬件层以适配 22 字节状态的 NuPhy Lab 为依据；NuPhy Codex Sidelight 的按需启动和会话汇总可参考，其灯效驱动按旧的 17 字节状态编写。[NuPhy Lab HID 实现](https://github.com/bohu8264/NuPhyLab-next/blob/1f1ae72dad5e61e363860fb34a2df00407b483bb/native/HIDBridge.swift) · [Sidelight 驱动](https://github.com/joe960913/nuphy-codex-sidelight/blob/5c0980b192545cefccf35711ac23f4d97c968c1a/nuphy.py)
4. 全部空闲或正常退出时恢复并回读；拔线或进程异常退出时保留恢复记录，重连后按设备、固件和 Mac/Win 配置核对。若某个原始自定义灯效或主色在 `2.0.0.7` 无法可靠还原，可单独启用侧灯。[NuPhy Lab 兼容说明](https://github.com/bohu8264/NuPhyLab-next/blob/1f1ae72dad5e61e363860fb34a2df00407b483bb/docs/RELEASE_1.2.50.md)

首轮验收分两步。先验证 F1、F2 的物理位置、侧灯独立于背光变色，以及退出后原灯效恢复；再分别从四个入口跑一轮“提交 → 等待审批 → 继续 → 结束”。最后同时运行两个客户端，让一个等待、另一个结束，检查侧灯仍保留等待提示。
