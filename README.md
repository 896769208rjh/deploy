# 创作台

AI 工作流创作平台：可视化工作流编辑器、AI 视频生成、博客 RAG 助手、链接书签管理。

---

## 本地开发

```powershell
Copy-Item deploy\.env.example deploy\.env
# 编辑 deploy\.env，至少改 JWT_SECRET 和 INTERNAL_TOKEN
docker compose --env-file deploy\.env -f deploy\compose.yaml up --build
```

浏览器打开 http://localhost:8080，管理员账号来自 `.env` 里的 `ADMIN_EMAIL` / `ADMIN_PASSWORD`。

前端单独热更新：
```powershell
cd apps\web
npm install
npm run dev   # http://localhost:5173
```

模型节点填 `mock` 可以在没有密钥时演练流式输出；视频接口地址填 `mock` 会使用样片。

---

## 生产部署（服务器 + Coolify + GitHub Actions）

整个流程：**推代码 → GitHub Actions 构建镜像并推送到 ghcr.io → Coolify 自动拉取镜像并重启容器**。

### 第一步：在服务器上安装 Coolify

SSH 进入服务器，执行一条命令：

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

安装完成后浏览器打开 `http://124.222.144.7:8000` 完成 Coolify 初始化（设置管理员账号）。

> Coolify 自带的 8000 端口和本项目 gateway 的端口冲突。安装完 Coolify 之后，把本项目 gateway 映射到别的端口，或者让 Coolify 接管反代，见第三步。

### 第二步：把代码推到 GitHub

在本机执行：
```bash
cd F:/Study/ai/ai-study-cursor
git init
git add .
git commit -m "initial commit"
# 去 GitHub 新建一个仓库（比如 your-username/ai-platform），然后：
git remote add origin https://github.com/your-username/ai-platform.git
git push -u origin main
```

推送后 GitHub Actions 会自动构建所有服务的 Docker 镜像并推到 `ghcr.io`。

**让镜像可以被服务器拉取**（ghcr.io 默认私有）：
- GitHub → 仓库 → Settings → Packages → 把每个包改为 Public
- 或者在 Coolify 里配置 ghcr.io 的登录凭证

### 第三步：在 Coolify 里创建部署

1. 打开 `http://124.222.144.7:8000` 登录 Coolify
2. 左侧 → **Servers** → 添加服务器（填 `124.222.144.7` 和 SSH 私钥）
   - 如果 Coolify 就装在这台服务器上，直接选 **localhost**
3. 左侧 → **Projects** → New Project → 起名 `ai-platform`
4. Project 里 → **+ New Resource** → **Docker Compose**
5. Source 选 **GitHub App**（授权你的仓库），或粘贴仓库 HTTPS 地址
6. Compose 文件路径填：`deploy/compose.coolify.yaml`
7. 在 **Environment Variables** 界面填写以下变量（参考 `deploy/.env.example`）：

```
POSTGRES_PASSWORD=（随机强密码）
JWT_SECRET=（随机32位字符串）
INTERNAL_TOKEN=（随机32位字符串）
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=（强密码）
DEEPSEEK_API_KEY=sk-xxxx
GITHUB_REPOSITORY=your-username/ai-platform
CORS_ORIGINS=http://124.222.144.7:8080
```

8. Domains 配置：把 `web` 服务绑定到 `http://124.222.144.7:8080`，`gateway` 绑定到 `http://124.222.144.7:8001`（避开 Coolify 的 8000）
9. 点击 **Deploy** 完成首次部署

### 第四步：配置 GitHub → Coolify 自动触发

在 Coolify 里找到这个 Resource 的 **Webhooks** 页面，复制 **Deploy Webhook URL** 和 **API Token**。

在 GitHub 仓库 → Settings → Secrets and variables → Actions 添加：

| Secret 名称 | 值 |
|---|---|
| `COOLIFY_WEBHOOK_URL` | 从 Coolify 复制的 Webhook URL |
| `COOLIFY_TOKEN` | 从 Coolify 复制的 API Token |

### 日常工作流

```
修改代码
  ↓
git add . && git commit -m "xxx" && git push origin main
  ↓
GitHub Actions 自动构建镜像（约 3-5 分钟）
  ↓
自动调用 Coolify Webhook
  ↓
Coolify 拉取新镜像、重启容器（约 30 秒）
```

在 Coolify Dashboard 也可以随时点 **Redeploy** 按钮手动触发部署。

### 迁移到新服务器

1. 新服务器安装 Coolify（一条命令）
2. Coolify → Servers → 添加新服务器
3. 把 Resource 的 Server 切换到新服务器
4. Deploy 即可（数据卷需要手动迁移：`docker volume` 导出/导入）

---

## 端口说明

| 地址 | 服务 |
|---|---|
| `:8000` | Coolify Dashboard（安装后占用）|
| `:8080` | 前端 web（nginx）|
| `:8001` | API gateway（生产环境建议用域名+80/443）|
| `:5432` | PostgreSQL（仅内网，生产环境不要对外）|
| `:9000` | MinIO（可选）|

---

## 架构概览

```
浏览器
  └─ web (nginx :8080)
       └─ gateway (:8001)
            ├─ identity   ← 注册/登录/JWT
            ├─ workflow   ← LangGraph 工作流引擎
            ├─ media      ← 视频生成 + 广场
            ├─ blog-rag   ← DeepSeek + 向量检索
            └─ bookmark   ← 书签 + favicon
                 └─ postgres (pgvector)
```

