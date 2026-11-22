"use strict";

const $ = (id) => document.getElementById(id);
const states = {
  working: "运行中",
  waiting: "等待回应",
  error: "出错",
  done: "已完成",
  idle: "空闲",
};
const priority = ["idle", "done", "working", "error", "waiting"];
const effortNames = { low: "低 · 短尾", medium: "中 · 追光", high: "高 · 脉冲", xhigh: "极高 · 双彗星" };
const factory = {
  version: 1,
  codex: "working",
  claude: "working",
  efforts: ["medium", "medium"],
  brightness: 38,
  colors: {
    working: "#1466C8",
    waiting: "#FF8C10",
    error: "#EF2842",
    done: "#18AE54",
    idle: "#090909",
  },
};
const storageKey = "air75.signal-studio.v1";
function profile(data) {
  const efforts = data?.efforts === undefined ? factory.efforts : data.efforts;
  if (
    data?.version !== 1 ||
    !priority.includes(data.codex) ||
    !priority.includes(data.claude) ||
    !Array.isArray(efforts) || efforts.length !== 2 ||
    !efforts.every(e => typeof e === "string" && Object.hasOwn(effortNames, e)) ||
    !Number.isInteger(data.brightness) ||
    data.brightness < 0 ||
    data.brightness > 100 ||
    !priority.every(
      (key) =>
        typeof data.colors?.[key] === "string" &&
        /^#[0-9a-f]{6}$/i.test(data.colors[key]),
    )
  ) {
    throw new Error("需要 Signal Studio 导出的有效配置文件。");
  }
  return {
    version: 1,
    codex: data.codex,
    claude: data.claude,
    efforts: [...efforts],
    brightness: data.brightness,
    colors: Object.fromEntries(
      priority.map((k) => [k, data.colors[k].toUpperCase()]),
    ),
  };
}
let config = profile(factory);
try {
  const saved = localStorage.getItem(storageKey);
  if (saved) config = profile(JSON.parse(saved));
} catch {
  $("storage").textContent = "当前使用默认配置";
}

let messageTimer;
function message(text) {
  clearTimeout(messageTimer);
  $("message").textContent = text;
  messageTimer = setTimeout(() => {
    $("message").textContent = "";
  }, 4200);
}
function save() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(config));
    $("storage").textContent = "配置自动保存在此浏览器";
  } catch {
    $("storage").textContent = "浏览器存储不可用，可导出配置";
  }
}
const letters = (line) => [...line].map((c) => ["Key" + c, c]);
const rows = [
  [
    ["Escape", "esc"],
    ...Array.from({ length: 12 }, (_, i) => ["F" + (i + 1), "F" + (i + 1)]),
    ["PrintScreen", "PrtSc"],
    ["Insert", "Ins"],
    ["Delete", "Del"],
  ],
  [
    ["Backquote", "~"],
    ...[..."1234567890"].map((n) => ["Digit" + n, n]),
    ["Minus", "-"],
    ["Equal", "="],
    ["Backspace", "backspace", 8],
    ["PageUp", "PgUp"],
  ],
  [
    ["Tab", "tab", 6],
    ...letters("QWERTYUIOP"),
    ["BracketLeft", "["],
    ["BracketRight", "]"],
    ["Backslash", "\\", 6],
    ["PageDown", "PgDn"],
  ],
  [
    ["CapsLock", "caps", 7],
    ...letters("ASDFGHJKL"),
    ["Semicolon", ";"],
    ["Quote", "'"],
    ["Enter", "enter", 9],
    ["Home", "Home"],
  ],
  [
    ["ShiftLeft", "shift", 9],
    ...letters("ZXCVBNM"),
    ["Comma", ","],
    ["Period", "."],
    ["Slash", "/"],
    ["ShiftRight", "shift", 7],
    ["ArrowUp", "↑"],
    ["End", "End"],
  ],
  [
    ["ControlLeft", "ctrl", 5],
    ["AltLeft", "opt", 5],
    ["MetaLeft", "cmd", 5],
    ["Space", "", 25],
    ["MetaRight", "cmd"],
    ["Fn", "fn"],
    ["ControlRight", "ctrl"],
    ["ArrowLeft", "←"],
    ["ArrowDown", "↓"],
    ["ArrowRight", "→"],
  ],
];
const keys = new Map();
for (const row of rows) {
  const el = document.createElement("div");
  el.className = "keyrow";
  for (const [code, label, span = 4] of row) {
    const key = document.createElement("span");
    key.className = "key" + (label.length > 1 ? " mod" : "");
    key.dataset.code = code;
    key.style.setProperty("--span", span);
    key.textContent = label;
    keys.set(code, key);
    el.append(key);
  }
  $("key-deck").append(el);
}
for (const [i, id] of ["codex", "claude"].entries()) {
  const effort = $(id + "-effort");
  for (const [value, label] of Object.entries(effortNames)) effort.add(new Option(label, value));
  effort.onchange = () => {
    stopDemo();
    config.efforts[i] = effort.value;
    save();
    render();
  };
  for (const [value, label] of Object.entries(states))
    $(id).add(new Option(label, value));
  $(id).onchange = () => {
    stopDemo();
    config[id] = $(id).value;
    save();
    render();
  };
}
for (const [state, name] of Object.entries(states)) {
  const label = document.createElement("label");
  const input = document.createElement("input");
  input.type = "color";
  input.id = "color-" + state;
  input.setAttribute("aria-label", name + "颜色");
  input.oninput = () => {
    config.colors[state] = input.value.toUpperCase();
    save();
    render();
  };
  label.append(input, name);
  $("swatches").append(label);
}
$("brightness").oninput = (e) => {
  config.brightness = Number(e.target.value);
  save();
  render();
};

let testing = false;
let demoTimer = null;
let demoStates = null;
const demoFrames = [
  ["working", "working"],
  ["working", "waiting"],
  ["done", "waiting"],
  ["idle", "error"],
  ["idle", "done"],
  ["idle", "idle"],
];
function stopDemo() {
  clearInterval(demoTimer);
  demoTimer = null;
  demoStates = null;
}
function dot(color) {
  const d = document.createElement("i");
  d.className = "dot";
  d.style.setProperty("--color", color);
  return d;
}
let perimeterTimer;
let perimeterPhase = 0;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
function showPerimeter(active) {
  clearInterval(perimeterTimer);
  const size = perimeter.path.length;
  if (!active.includes("working") || testing || reducedMotion.matches) perimeterPhase = 0;
  function draw() {
    const lit = new Map();
    if (!testing) {
      for (const [i, state] of active.entries()) {
        if (state !== "working") continue;
        const head = perimeterPhase + i * Math.floor(size / 2);
        const patterns = perimeter.patterns[perimeter.modes[config.efforts[i]]];
        const beat = perimeter.beats[perimeterPhase % perimeter.beats.length];
        for (const [distance, ink] of patterns[beat % patterns.length].entries()) {
          if (ink !== null) lit.set(perimeter.path[(head - distance + size) % size], perimeter.ink[i][ink]);
        }
      }
      for (const [i, state] of active.entries()) {
        if (state !== "working" && state !== "idle") lit.set("F" + (i + 1), config.colors[state]);
      }
    }
    for (const [code, key] of keys) {
      key.classList.toggle("indicator", lit.has(code));
      if (lit.has(code)) key.style.setProperty("--key-color", lit.get(code));
    }
  }
  draw();
  if (!testing && !document.hidden && !reducedMotion.matches && active.includes("working")) {
    perimeterTimer = setInterval(() => {
      perimeterPhase = (perimeterPhase + 1) % size;
      draw();
    }, perimeter.frameMs);
  }
}
reducedMotion.addEventListener("change", render);
document.addEventListener("visibilitychange", render);
function render() {
  const active = demoStates || [config.codex, config.claude];
  const overall = priority[Math.max(...active.map((s) => priority.indexOf(s)))];
  const restored = overall === "idle";
  $("codex").value = active[0];
  $("claude").value = active[1];
  for (const [i, id] of ["codex", "claude"].entries()) {
    $(id + "-effort").value = config.efforts[i];
    $(id + "-effort").disabled = active[i] !== "working";
  }
  $("brightness").value = config.brightness;
  $("value").textContent = config.brightness + "%";
  for (const state of priority) {
    const input = $("color-" + state);
    input.value = config.colors[state];
    input.style.setProperty("--color", input.value);
  }
  const board = $("board");
  board.style.setProperty(
    "--led",
    restored || testing ? "transparent" : config.colors.idle,
  );
  const side = restored || testing ? "#c3c7cc" : config.colors[overall];
  board.style.setProperty(
    "--side-color",
    restored || testing
      ? side
      : "color-mix(in srgb, " + side + " " + config.brightness + "%, #c3c7cc)",
  );
  board.classList.toggle("test", testing);
  showPerimeter(active);
  $("side-result").replaceChildren(
    dot(side),
    restored ? "恢复原灯效" : states[overall],
  );
  $("legend").replaceChildren();
  for (const [i, product] of ["Codex", "Claude Code"].entries()) {
    const state = active[i];
    const color = state === "working" ? perimeter.ink[i][0] : config.colors[state];
    const item = document.createElement("span");
    item.className = "legend-item";
    item.append(
      dot(state === "idle" ? "#c3c7cc" : color),
      product + " · " + states[active[i]],
    );
    $("legend").append(item);
  }
  if (testing)
    $("legend").textContent = "绿色描边为已检测键位，亮绿色为正在按下。";
  $("demo").textContent = demoTimer ? "停止演示" : "▷ 播放状态演示";
  $("demo").hidden = testing;
  $("lighting").hidden = testing;
  $("testing").hidden = !testing;
  $("preview").setAttribute("aria-pressed", String(!testing));
  $("test").setAttribute("aria-pressed", String(testing));
  board.setAttribute(
    "aria-label",
    testing
      ? "Air75 V3 月虹白特别版实键输入测试"
      : "Air75 V3 月虹白特别版灯效预览，侧灯" + $("side-result").textContent,
  );
}
$("demo").onclick = () => {
  if (demoTimer) stopDemo();
  else {
    let frame = 0;
    demoStates = demoFrames[frame];
    demoTimer = setInterval(() => {
      if (++frame === demoFrames.length) stopDemo();
      else demoStates = demoFrames[frame];
      render();
    }, 1500);
  }
  render();
};
function switchMode(next) {
  stopDemo();
  testing = next;
  render();
  if (next) $("capture").focus({ preventScroll: true });
}
$("preview").onclick = () => switchMode(false);
$("test").onclick = () => switchMode(true);
$("zoom").onclick = () => {
  const enlarged = $("board").classList.toggle("enlarged");
  $("zoom").setAttribute("aria-pressed", String(enlarged));
  $("zoom").textContent = enlarged ? "适应宽度" : "放大布局";
};
const seen = new Set();
function releaseKeys() {
  for (const key of keys.values()) key.classList.remove("down");
}
$("capture").addEventListener("blur", releaseKeys);
window.addEventListener("blur", releaseKeys);
$("capture").onkeydown = (e) => {
  const key = keys.get(e.code);
  if (!key) return;
  if (e.code !== "Tab") e.preventDefault();
  seen.add(e.code);
  key.classList.add("seen", "down");
  $("last").textContent = e.code;
  $("count").textContent = "已检测 " + seen.size + " 个键位";
};
$("capture").onkeyup = (e) => keys.get(e.code)?.classList.remove("down");
$("clear").onclick = () => {
  seen.clear();
  for (const key of keys.values()) key.classList.remove("seen", "down");
  $("count").textContent = "已检测 0 个键位";
  $("last").textContent = "等待按键";
  $("capture").focus();
};
$("reset").onclick = () => {
  stopDemo();
  config = profile(factory);
  save();
  render();
  message("已恢复默认灯光配置");
};
$("export").onclick = () => {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(config, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "air75-signal-studio.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
};
$("import").onclick = () => $("file").click();
$("file").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    if (file.size > 8192) throw new Error();
    const next = profile(JSON.parse(await file.text()));
    stopDemo();
    config = next;
    save();
    render();
    message("已导入配置");
  } catch {
    message("导入失败，请选择有效的 Signal Studio JSON 配置。");
  }
  e.target.value = "";
};

// Only the loopback launcher supplies this per-session capability in the URL fragment.
const ticket = new URLSearchParams(location.hash.slice(1)).get("session");
const localDevice = location.hostname === "127.0.0.1" && !!ticket;
if (localDevice) $("mode").lastChild.textContent = "本机测试模式";
$("hardware").onclick = () => {
  stopDemo();
  render();
  $("device-help").textContent = localDevice
    ? "请将 Air75 V3 ANSI（固件 2.0.0.7）切到 USB 有线模式并关闭其他灯控软件。测试结束会恢复原灯效。"
    : "真机测试需要本机 HID 桥接器。在已安装 Agent Lights 的 Mac 上，从项目目录运行下方命令，再在打开的页面导入配置。";
  $("launch").hidden = localDevice;
  $("apply").hidden = !localDevice;
  $("device-status").textContent = "";
  $("device").showModal();
};
$("close").onclick = () => $("device").close();
$("apply").onclick = async () => {
  $("apply").disabled = true;
  $("device-status").textContent = "正在测试，请保持 USB 连接…";
  try {
    const reply = await fetch("/test", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Studio-Session": ticket,
      },
      body: JSON.stringify(config),
    });
    const result = await reply.json();
    $("device-status").textContent = result.message;
  } catch {
    $("device-status").textContent =
      "未收到本机服务的结果，请检查终端与 USB 连接。";
  } finally {
    $("apply").disabled = false;
  }
};
render();
