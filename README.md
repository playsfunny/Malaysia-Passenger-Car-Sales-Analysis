# 马来西亚乘用车销量分析工具 · 部署说明

本仓库用于通过 **Cloudflare Pages** 将工具部署到自有域名 `playsfunny.com`。

## 文件结构
- `index.html` — SEO 落地首页（轻量、文字密集、含 FAQ 与结构化数据），入口页
- `tool.html` — 工具主文件（单文件、零外部依赖、完全自包含，打开即用）
- `sitemap.xml` — 站点地图（供 Google Search Console 提交）
- `robots.txt` — 爬虫规则，指向 sitemap

## Cloudflare Pages 部署设置（路线 A：直连 GitHub）
1. 登录 Cloudflare 控制台 → **Workers & Pages** → **Create** → **Pages** → 连接 Git 仓库 `playsfunny/Malaysia-Passenger-Car-Sales-Analysis`。
2. 构建设置：
   - **Framework preset**：`None`
   - **Build command**：留空
   - **Build output directory**：`/`（仓库根目录）
   - **Root directory**：`/`（默认）
3. 首次部署完成后，进入 **Custom domains** 添加 `playsfunny.com`，按提示在域名注册商处把 NS 或 CNAME 指向 Cloudflare，完成验证即可。
4. 之后每次 `git push` 到 `main` 分支会自动重新部署。

## 本地更新流程（工具改版时）
1. 在 `template.html` 修改工具 → 运行对应 `build_v*.py` 生成新版本文件。
2. 更新工具页 `tool.html`（保持首页不变）：
   ```bash
   cp "马来西亚乘用车销量分析工具_2021-2026V275.html" tool.html
   ```
   （仅在工具内容变化时执行；SEO 首页 `index.html` 通常无需改动）
3. 提交并推送：
   ```bash
   git add tool.html && git commit -m "update tool" && git push
   ```

## SEO 上线后建议
1. Google Search Console（`search.google.com/search-console`）添加资源 `playsfunny.com`，DNS 验证。
2. 提交 `https://playsfunny.com/sitemap.xml`，请求编制索引。
3. 首页已内置：meta 描述、canonical、Open Graph、WebApplication / Dataset / FAQPage 三种 JSON-LD 结构化数据。

## 说明
- 工具内的「重新计算」按钮仅在 `file://` 或 `localhost` 下显示；部署到域名后自动隐藏，不会尝试连接本地服务。
- 数据已内嵌于 `tool.html`，无需数据库或 API。
- 节日月历功能已随工具内置（国家概况 → 风土人情 卡片底部）。
