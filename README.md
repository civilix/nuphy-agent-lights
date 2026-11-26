# NuPhy Agent Lights

Codex 运行时，蓝光沿 Air75 V3 最外圈顺时针移动。Claude Code 用珊瑚橙走同一条路线。两个工具同时运行时，两束光相隔约半圈。路线经过 F 键行、右侧导航键、方向键、空格和左侧修饰键，字母区保持低亮背景。等待、完成或出错时，对应光束停转，由 F1（Codex）或 F2（Claude Code）显示状态色。全部空闲时恢复原灯效。

外圈形状反映客户端为本轮报告的推理档位。低档（none、minimal、low）是两格短尾，中档（medium）是四格追光，高档（high）是带亮芯和流动光纹的七格长尾。极高档（xhigh、max、ultra）会多出一颗同色彗星，和前面的光束交替拉开、靠近。同一工具有多轮正在运行时显示其中最高档。等待等提示继续按状态优先级显示。

Claude Code 从 hook 提供的 `effort.level` 或 `CLAUDE_EFFORT` 取得档位。Codex 从 hook 指向的本地会话文件末尾最多 1 MiB 查找与本轮 ID 匹配的 `turn_context.effort`。这个文件格式可能随客户端更新。缺少匹配记录时先用四格追光，运行期间取得有效档位后自动切换。`lights status` 的 `effort` 显示当前运行档位，未知或非运行状态显示 `null`。这些信号反映配置档位，实时算力和思考内容不在数据中。[OpenAI Docs](https://learn.chatgpt.com/docs/hooks) · [Claude Code Hooks](https://code.claude.com/docs/en/hooks)

运行时，两侧蓝灯一起显示上下文窗口占用率。占用 0%、50%、100% 时，亮度分别为 15%、58%、100%。有多个运行中的会话时取已知占用率的最大值；尚无读数时使用 38% 亮度。等待审批、出错和完成仍按原有优先级显示状态色，全部空闲后恢复原灯效。可运行 `lights status` 查看 `context_percent` 中每个工具的最高运行占用率，`null` 表示没有读数。

Codex 约每秒检查当前会话记录末尾 1 MiB，取最近一次请求的 `last_token_usage.total_tokens / model_context_window` 估算占用率。上下文压缩后，亮度可随新读数降低。Claude Code CLI 直接读取状态栏的 `context_window.used_percentage`。安装器会接入用户级状态栏，已有的命令会继续收到原始输入并显示自己的输出，卸载时还原。项目级设置覆盖状态栏、或客户端未发送状态栏数据时（包括部分 Desktop 会话），该会话没有可用读数。新设备仍需本机灯控程序。[Claude Code 状态栏文档](https://code.claude.com/docs/en/statusline#context-window-fields)

设备范围为 **Apple Silicon Mac、macOS 13 或更高版本、USB 有线模式、Air75 V3 ANSI 官方固件 2.0.0.7**。开发与实机验证使用月虹白特别版。

## 从源码部署到 Mac

如果这台 Mac 已经装好灯控程序，只需重新启用 hook 和 Claude 状态栏，可直接运行：

```sh
"$HOME/Library/Application Support/NuPhy Agent Lights/current/lights" install
```

hook 将客户端事件交给灯控程序，HIDBridge 负责通过 USB 写入键盘灯效。首次从源码部署或更新源码版本时会调用 Swift 编译器；平时触发 hook 会直接运行已编译的 HIDBridge。

在新 Mac 上部署源码时，准备 Apple Silicon Mac、macOS 13 或更高版本、网络和 Apple Command Line Tools（含 Swift、Git 和 Python 3.9+）。如果尚未安装开发工具，先运行 `xcode-select --install` 并等待安装完成。以日常使用键盘的 macOS 用户执行以下命令。

```sh
git clone https://github.com/civilix/nuphy-agent-lights.git
cd nuphy-agent-lights
./scripts/install-source.sh
```

已有源码仓库时，直接在仓库根目录运行最后一条命令。更新时检出需要的版本，然后再次运行该脚本。原先用归档安装的用户也可直接执行，完成后既有 hook 路径会指向源码构建的版本，旧版本保留供运行中的控制器收尾。

- **下载和编译**　[构建脚本](scripts/build-bridge.sh) 从固定的 NuPhy Lab 提交下载 `HIDBridge.swift` 和许可证，校验 Swift 源码的 SHA-256，随后在本机编译、进行 ad-hoc 签名并运行桥接器自检。
- **安装内容**　[源码部署脚本](scripts/install-source.sh) 使用 `/usr/bin/python3` 和标准库，将项目 Python 文件、启动脚本、工作台静态文件、本机编译的桥接器及其许可证放入当前用户的 `~/Library/Application Support/NuPhy Agent Lights/versions/`。构建成功并配置完成后切换 `current`。部署后可以移动源码目录，运行时仍需保留本机开发工具。
- **客户端配置**　[配置代码](hook_config.py) 将灯控命令合并到 Codex 的 `~/.codex/hooks.json`、Claude Code 的 `~/.claude/settings.json`，并接入 Claude 状态栏。改动前已有的配置会备份到灯控目录的 `hook-backups/`。若设置了 `CODEX_HOME` 或 `CLAUDE_CONFIG_DIR`，请从带有这些变量的终端部署。

键盘连 USB 数据线并切到有线档位，关闭占用键盘的 NuPhyIO 或 NuPhy Lab。在 Codex CLI 输入 `/hooks`，或在桌面端 Settings → Hooks 审阅指向 `NuPhy Agent Lights/current/lights` 的命令，再打开新的本地会话。Claude Desktop 使用 Code 标签页的本地会话。

### 验证与日常操作

```sh
lights="$HOME/Library/Application Support/NuPhy Agent Lights/current/lights"
"$lights" demo       # 演示推理档位、上下文亮度及状态切换，回读后恢复原灯效
"$lights" status     # 查看各产品状态、最近收到的 hook、硬件回读及恢复记录
"$lights" recover    # 清除当前指示状态，要求控制器恢复原灯效
"$lights" uninstall  # 移除本项目的 hook，清除指示状态并启动恢复
```

若键盘曾拔线，将它接回原 Mac/Win 档位后检查 `status`。恢复完成时 `recovery_records` 为空。卸载后程序、配置备份和恢复记录留在用户目录，便于重新启用或恢复。确认恢复后可自行删除该目录。

## 图形化配置与测试

双击 [灯光工作台](studio/dist/index.html) 即可离线预览 Air75 V3 月虹白特别版的 84 键 ANSI 布局。预览按 318.9 × 128.9 mm 的机身比例绘制，采用白色机身、雾透键帽和白色字符，用整颗键帽的漫射光表现状态色。[Air75 V3 规格](https://pay.nuphy.com/products/nuphy-air75-v3) · [NuPhy 月虹特别版设计说明](https://pay.nuphy.com/blogs/journal/air75-v3-moonbow-edition-design)

将两个工具都选为「运行中」，分别选择思考强度，即可比较两种拖尾。浏览器启用「减少动态效果」时显示静态光束。点击色块可调整背景和状态指示色，拖动滑块调整侧灯亮度。在「按键测试」的检测区按下实体键，可查看浏览器收到的键位。Fn、媒体键和系统快捷键的结果取决于系统是否转发事件。

工作台在本地运行，真机测试服务仅监听 `127.0.0.1`。浏览器会保存当前测试配置，也支持 JSON 导入与导出。工作台的状态色和亮度用于预览和手动试灯。日常 hook 使用相同的外圈动画及默认状态色。

在安装本版本后，运行下方命令打开带真机测试功能的本机页面。已有旧版安装的开发机也可以在本仓库运行 `python3 -B studio_server.py`，复用已安装的 HIDBridge。

```sh
"$HOME/Library/Application Support/NuPhy Agent Lights/current/lights" studio
```

打开「在键盘上测试」并点击「测试 6 秒」。需要上文所列固件与 USB 有线连接。控制器占用设备时，请等当前会话结束再试。按键接管受限时仅试亮侧灯；试灯结束后，页面显示恢复验证结果。按 Ctrl+C 关闭本机服务。

## 状态和四个入口

| 指示 | 含义 |
| --- | --- |
| 外圈蓝光、橙光 | 分别代表 Codex、Claude Code 正在运行，包括 Desktop 和 CLI 的本地会话 |
| F1、F2 | 分别显示 Codex、Claude Code 的等待、出错和完成提示 |
| 蓝色侧灯 | 运行中，亮度随上下文窗口占用率升高 |
| 琥珀色 | 有会话等待审批或同步提问的答复 |
| 红色 | 收到 Claude Code 的 `StopFailure`，提示 5 秒 |
| 绿色 | 主会话本轮结束，提示 5 秒 |
| 两侧灯条 | 共同显示等待、错误、运行、结束中优先级最高的一项。全部空闲后恢复原灯效 |

Codex Desktop 和 CLI 使用同一份用户级 `hooks.json`。Claude Code CLI 和 Claude Desktop 的本地 Code 会话共享用户级 `settings.json`。云端或 SSH 远端执行不在首版范围内。[OpenAI Hooks](https://learn.chatgpt.com/docs/hooks) · [Claude Code Hooks](https://code.claude.com/docs/en/hooks) · [Claude Desktop 配置共享](https://code.claude.com/docs/en/desktop#shared-configuration)

hook 从标准输入提取生命周期信息，用本机 SQLite 事务按产品、会话和可用的轮次 ID 汇总，并按需唤起单一控制器。共享状态记录会话标识、状态、事件、工具名、时间、推理档位、上下文占用率，以及查找 Codex 本轮档位所需的本地会话文件路径。聊天内容和工具参数不写入数据库。控制器合并重复状态，全部空闲时释放 USB 并退出。客户端异常退出时会清理能识别到进程的活动指示，其他缺失终止事件的会话在最后事件的 4 小时后过期。`recover` 可立即清除指示。

## 灯控协议与验收

有线接口为 `19f5:1028`，usage page 1、usage 0。已读回 22 字节灯效状态和 104 个 RGB 值。84 个键盘灯位采用自定义灯效 21 和 `D8` 更新，用 `D2` 验证；左右共 20 个侧灯灯位作为单一区，通过 `D6` 写偏移 9 的 8 字节设置，并用 `D5` 回读。按键模式接管整块背光，其他键使用低亮背景。若当前主灯设置无法可靠恢复，控制器可只接管侧灯。[NuPhy Lab 固件说明](https://github.com/bohu8264/NuPhyLab-next/blob/1f1ae72dad5e61e363860fb34a2df00407b483bb/docs/RELEASE_1.2.50.md) · [原生 HID 实现](https://github.com/bohu8264/NuPhyLab-next/blob/1f1ae72dad5e61e363860fb34a2df00407b483bb/native/HIDBridge.swift)

已通过 NuPhy IO 保存到键盘的原生宏，预期在接管灯光期间仍可触发。控制器通过非独占 HID 连接更新 RGB，F1 和 F2 只作为灯光位置使用。实机在试灯前、试灯中和恢复后读回的当前层 98 个键位条目一致，宏动作本身尚未按键验证。需要编辑或绑定宏时，等灯光恢复后打开 NuPhy IO。[NuPhy 宏设置说明](https://helpcenter.nuphy.com/?lang=en&variant=standard)

状态变化时控制器回读完整画面。运行中每步间隔约 120 毫秒，另计 USB 通信时间。驱动只写入有变化的灯位并核对回执。外圈动画使用 33 个已映射的灯位。空格作为一整格点亮。按键接管受限时，侧灯仍可显示状态。[Air75 V3 灯位表](https://github.com/bohu8264/NuPhyLab-next/blob/1f1ae72dad5e61e363860fb34a2df00407b483bb/shared/air75-v3-ansi.json)

本机实测已验证逐键和侧灯配置写入、等待优先级及原灯效恢复。向侧灯依次输入 0%、50%、100%、10% 的上下文占用率时，已回读确认亮度为 15%、58%、100%、24%，再切到等待状态时回到 38% 琥珀色。可通过 `demo` 检查具体键位和亮度。在另一台 Mac 验收四个入口时，分别运行一轮「提交 → 等待审批 → 继续 → 结束」，用 `status` 核对事件及硬件状态，再让一个会话等待、另一个会话结束，观察侧灯是否保持琥珀色。

## 维护者测试与可选离线归档

在仓库根目录运行单元测试。需要单独生成离线归档时，可以再运行后两条命令。

```sh
/usr/bin/python3 -B -m unittest -v
./scripts/build-package.sh
./scripts/test-package.sh dist/NuPhy-Agent-Lights-macOS-arm64.tar.gz
```

归档和 SHA-256 校验文件输出到 `dist/`。已有离线归档的用户可解压并运行其中的 `install.command`。构建脚本固定 NuPhy Lab 提交和 Python 独立运行时版本，校验 SHA-256、本地编译 HID 驱动并运行桥接器自检。包内保留 NuPhy Lab 的 MIT 许可和 Python 运行时随附的第三方许可。[NuPhy Lab](https://github.com/bohu8264/NuPhyLab-next) · [Python Build Standalone](https://github.com/astral-sh/python-build-standalone)
