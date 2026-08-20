# 马来西亚乘用车销量分析工具 · 部署说明

本仓库用于通过 **Cloudflare Pages** 将工具部署到自有域名 `playsfunny.com`。

## 文件
- `index.html` — 工具主文件（单文件、零外部依赖、完全自包含）。打开即用，无需后端。

## Cloudflare Pages 部署设置（路线 A：直连 GitHub）
1. 登录 Cloudflare 控制台 → **Workers & Pages** → **Create** → **Pages** → 连接 Git 仓库 `playsfunny/Malaysia-Passenger-Car-Sales-Analysis`。
2. 构建设置：
   - **Framework preset**：`None`
   - **Build command**：留空
   - **Build output directory**：`/`（仓库根目录）
   - **Root directory**：`/`（默认）
3. 首次部署完成后，进入 **Custom domains** 添加 `playsfunny.com`，按提示在域名注册商处把 NS 或 CNAME 指向 Cloudflare，完成验证即可。
4. 之后每次 `git push` 到 `main` 分支会自动重新部署。

## 本地更新流程
1. 在 `template.html` 修改工具 → 运行 `python3 build_v275.py` 生成新 V275 文件。
2. 复制为新 `index.html`：
   ```bash
   cp "马来西亚乘用车销量分析工具_2021-2026V275.html" index.html
   ```
3. 提交并推送：
   ```bash
   git add index.html && git commit -m "update tool" && git push
   ```

## 说明
- 工具内的「重新计算」按钮仅在 `file://` 或 `localhost` 下显示；部署到域名后自动隐藏，不会尝试连接本地服务。
- 数据已内嵌于 `index.html`，无需数据库或 API。
- 节日月历功能已随工具内置（国家概况 → 风土人情 卡片底部）。
