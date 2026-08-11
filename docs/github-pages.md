# 启用 GitHub Pages

仓库的 `docs/` 已经包含无需构建的静态使用手册。可以直接让 GitHub Pages 从该目录发布。

## 发布步骤

1. 把本次改动推送到 GitHub 默认分支。
2. 打开仓库的 **Settings**。
3. 进入 **Pages**。
4. 在 **Build and deployment** 中选择 **Deploy from a branch**。
5. Branch 选择默认分支（通常是 `main`），目录选择 `/docs`。
6. 点击 **Save**，等待 GitHub 完成首次部署。

发布地址通常是：

```text
https://quantumxiaol.github.io/umamusume-qq-bot/
```

## 页面文件

```text
docs/
├── index.html
├── .nojekyll
├── assets/
│   ├── site.css
│   ├── site.js
│   ├── AdmireVega.png
│   └── og.png
├── commands.md
├── characters.md
├── api.md
├── deployment.md
└── architecture.md
```

`index.html` 是面向 QQ 用户的一页式 Wiki。Markdown 文件保留在仓库中，方便开发者查看和维护。

## 更新

修改 `docs/` 并推送到发布分支后，GitHub Pages 会自动重新部署，不需要在服务器运行任何服务。

角色和场景可能随 Agent 更新。更新静态页面时，应先以当前接口响应为准：

```text
GET /characters
GET /director/templates
GET /capabilities
```

