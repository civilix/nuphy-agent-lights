# NuPhy Agent Lights

给 NuPhy Air75 V3 做一个 Agent 状态灯。首个目标设备是月虹白特别版，ANSI 布局，官方固件 `2.0.0.7`。

项目处于初始化阶段。第一版计划通过 USB 接收电脑发来的灯光指令，用几个键显示 Codex 正在运行、等待确认或本轮结束。键位、颜色和亮度可针对雾透键帽调整。电脑端计划由 Codex hook 按需启动灯光控制器。

## 参考项目

- [NuPhy Lab](https://github.com/bohu8264/NuPhyLab-next) 的 USB 灯控已适配 Air75 V3 ANSI 官方 `2.0.0.7`。
- [NuPhy Codex Sidelight](https://github.com/joe960913/nuphy-codex-sidelight) 提供由 Codex hook 按需启动控制器的示例。
