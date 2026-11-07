# AGENTS.md — JPJ 工具仓库的硬规则（任何 AI / 脚本 / 人都必须遵守）

> 本仓库由**两个并行会话**同时改（用户的「主任务」与「子任务」两个对话框）。
> 2026-09-15 出过两次真实事故，下面的规则就是从事故里长出来的，不是形式主义：
> 1. **MMF 模块被抹掉** —— 一个脚本只写 `tool.html` 不写母版，另一个脚本紧接着
>    `copy2(template.html, tool.html)` 整体覆盖，改动静默消失，用户报「最新 tool 看不到」。
> 2. **版本号混淆** —— 同一分钟出现 `template.bak_pre_v307h` 与 `template.bak_pre_v309`
>    两个备份；产物里又查不到版本号（`VERSION:"3e00"` 是 SheetJS 的），无法判断当前是哪版。

## 0. 三个产物，一个母版

| 文件 | 角色 |
|---|---|
| `template.html` | **唯一母版**。所有改动都先落到这里 |
| `tool.html` | 产物（`.gitignore` 内） |
| `马来西亚乘用车销量分析工具_2021-2026.html` | 产物（`.gitignore` 内） |

三者内容必须**字节级一致**。

## 1. ⛔ 写产物只有一条路：`jpj_guard.write_products()`

```bash
python jpj_guard.py status        # 当前是哪一版 / 三文件是否一致 / 快照情况
python jpj_guard.py next          # 下一个可用版本号
python jpj_guard.py lint          # 找出仍在裸写产物的活跃脚本
python jpj_guard.py check         # 并发体检（有别人在改会告警）
python jpj_guard.py manifest      # 版本档案索引
python jpj_guard.py snapshot V312 --note "…"
python jpj_guard.py run <老脚本>   # 包壳跑：自动加锁 + 漏写检测
python jpj_guard.py watch --once  # 抓绕过 guard 的裸写并自动补快照
```

**禁止**：`open('tool.html','w')`、`io.open(p,'w')`、`shutil.copy2(template.html, tool.html)`。
一旦检测到，`lint` 会报出来；已经加了互锁的脚本会直接**拒绝启动**。

## 2. 新补丁脚本的标准写法（15 行以内）

```python
# -*- coding: utf-8 -*-
"""V312：一句话说明改了什么。"""
import sys; sys.path.insert(0, '/Users/fsn/工作/QR/DATA/JPJ')
from jpj_patch import run_patch

REPS = [
    (OLD_STR, NEW_STR, 1),      # (原文, 新文, 在母版中期望出现的次数)
]
MARK = '/*V312*/'               # 幂等标记：母版里已有它 → 整体跳过

if __name__ == '__main__':
    run_patch(__file__, REPS, mark=MARK, note='V312：一句话摘要')
```

`run_patch` 自动完成：读母版 → 幂等检查 → 逐条 `assert count == 期望值`（不符就中止，不写盘）
→ `write_products()`（**flock 写锁** + 盖 `window.__BUILD__` 版本戳 + 三文件原子同步
+ 写后 md5 全等断言 + **自动落 `html/V{ver}.html` 快照** + 登记 `.build_manifest.json`）。

临时不想改造的老脚本：`python jpj_guard.py run <脚本>`（不用改一行代码）。

## 3. 版本号规则（2026-09-15 起）

- **每次改动 = 一个新版本号 + 一份快照**。两者由 `write_products()` 一次完成，忘记不了。
- **单调递增、不再用字母后缀**。`V309B…V309G` 那套是历史遗留：两个会话各用一套编号，
  结果 `V310` 与 `V309G` 交叉，档案无法排序。取号用 `python jpj_guard.py next`。
- 版本号重复且内容不同 → 直接报错拒绝覆盖（防止把历史版本冲掉）。
- 打开产物后看控制台第一行 `JPJ BUILD V3xx …`，或 `python jpj_guard.py status`，
  就知道当前是哪一版；不用再靠 md5/mtime 猜。

## 4. 动手前的并发习惯

```bash
find . -mmin -30 -type f -not -path "./backup/*" -not -path "./.git/*"   # 有人刚改过吗
md5 -q template.html                                                     # 记基线
```

- ⛔ **不要用 `find . -newermt "30 minutes ago"`**：macOS BSD `find` 不解析相对时间，
  报 `bad date` 后**静默返回 0 命中**，会让你误判「没人改过」——已连踩两次。
- 验证用私有临时目录，别用共享的 `/tmp/<ver>_test`（另一个会话可能同时在写）。
- 提交前 `python jpj_guard.py status`，看到「⚠ 版本戳过期」就说明有人绕过了 guard。

## 5. 改产物内容的通用坑

- **注入锚点必须先断言 `count == 1`**；严禁 `replace("</body>", …)`（内联 SheetJS 含这个串，
  是 V296 乱码的根因）。`<head>` / `</head>` 各出现 2 次，不可用作锚点。
- **新模块一律注入母版**，不要在产物上打补丁 —— 否则下次 `copy2(母版, 产物)` 就没了。
- 判断模块是否存在要看**唯一 marker 串**（如 `MMF-V308-JS-START`、`id="mmf-root"`），
  不要 `grep -c MMF`（会命中 base64 噪声）。
- 往 JS 对象字面量追加键值，**末尾必须带 `,`**（V307 漏逗号 → 全站图表全灭）。
- i18n 键判重用带冒号形式 `'mkt.xxx':'`（裸键名会被 `T('mkt.xxx')` 误判已注入）。
- 构建后**强制语法闸门**：拆出所有内联 `<script>` 逐个 `node --check`
  （用 `str.find` 线性切块，⛔ 别用 `re.finditer(r'<script[^>]*>(.*?)</script>', re.S)`，
  11MB 单行 HTML 上是 O(L²)）。
- **「幂等」= 连跑 3 次字节级 md5 一致**，不是「能跑第二次」。

## 6. 环境

- Python 一律用 venv：`/Users/fsn/.workbuddy/binaries/python/envs/default/bin/python`
  （managed 3.13 缺 pandas）。
- headless 验证用本机 Chrome + puppeteer-core：
  `NODE_PATH=/Users/fsn/.workbuddy/binaries/node/workspace/node_modules`
  `/Users/fsn/.workbuddy/binaries/node/versions/22.22.2-3/bin/node <脚本>`
- 验证靠**数值探针**（`probe_*.js` / `probe_*.py`，会打印 ✅/❌ 与实测像素），别靠目测。
- 记忆与细节：`.workbuddy/memory/MEMORY.md`（热规则）、`MEMORY-DETAIL.md`（细节）、
  `YYYY-MM-DD.md`（流水）。

## 7. 工程方法论技能（2026-11-06 用户定版）

- **所有工程类任务必须先加载 `real-engineering` 技能，再按其路由点名加载具体技能。**
  `mattpocock/skills` 的 27 个稳定技能已装在用户级 `~/.workbuddy/skills/`；
  上游副本 `~/AI/_thirdparty/mattpocock-skills`，清单 `.mattpocock-install.json`。
  用户级记忆里有同款全局条款，适用于本机所有项目。
- **运维归因、状态排查、数据异常核查同样算工程类任务**；只读查询与纯状态检查不设例外，
  一律先加载 `real-engineering`。
- 本仓库优先：`diagnosing-bugs`（数值探针先建能复现的红灯）、`tdd`（红-绿-重构，
  验证走 `probe_*.js` / `probe_*.py` 的 ✅/❌ 实测值）、`prototype` 的 `LOGIC.md`
  （单文件自包含 HTML、无框架无构建，与本工具同构）、`codebase-design`（deep module）、
  `code-review`（提交前双轴）、`writing-for-agents`（改本文件时）。
- **上游与本仓库冲突时以本文件第 0–6 节为准**：不得自动 commit / push、不得建分支或
  worktree、不得建 GitHub Issue、不得绕过 `jpj_guard.write_products()` 写产物；
  上游 TypeScript / jest 示例只取纪律，不照搬代码；Python 一律用第 6 节的 venv 解释器。
- `setup-matt-pocock-skills` 会改写本文件，**禁止直接运行**。
