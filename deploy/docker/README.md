# Docker 资源更新器

使用 Docker Hub 镜像下载、解包游戏资源并上传到 R2，供 Cloudflare 网页读取。需要 Docker 和 Compose v2；当前镜像支持 `linux/amd64`。

## 配置与启动

在 `deploy/docker/` 目录执行；已有配置文件请保留：

```sh
cp .env.example .env
cp ../.env.r2.example .env.r2.local
chmod 600 .env .env.r2.local
```

- `.env`：设置 `HATSUBOSHI_CREDENTIALS_DIR` 为游戏账号目录的绝对路径，`CAMPUS_UPDATER_IMAGE` 为镜像版本。
- `.env.r2.local`：填写 R2 endpoint、桶名、专用前缀、访问密钥和可选资源域名。桶名与前缀必须和 Worker 配置一致。
- 账号目录内放置 `account.json`，格式为 `{"refresh_token":"..."}`。目录权限设为 `700`、文件为 `600`，目录保持可写以保存轮换令牌。

单独部署时复制 `docker-compose.yaml`、`.env.example` 和上级目录的 `.env.r2.example`，将两个示例分别保存为 `.env`、`.env.r2.local` 后填写。实际配置与账号文件不上传仓库或镜像。

```sh
docker compose config --quiet
docker compose pull updater
docker compose up -d updater
docker compose logs -f --tail=100 updater
```

首次启动下载网站所需资源并建立增量包基线，出现 `R2: 发布完成` 后网页可读取新资源。默认每轮完成后等待六小时检查更新，失败后最多十五分钟重试。日志显示处理阶段、上传进度和下次检查时间。

## 更新与数据

修改 `.env` 中的镜像版本后，重新执行 `docker compose pull updater` 和 `docker compose up -d updater`。保留原有挂载、账号目录和配置。

`campus-r2-updater_runtime` 卷保存仓库、缓存、发布版本和增量基线。普通升级不要执行 `down -v`；同一 R2 前缀只运行一个更新器。

默认从游戏 API 获取 masterdb，Toolkit 配置使用 `API` 分支。容器无需开放入站端口，需要访问 GitHub、游戏资源服务和 R2。

R2、OAuth、语音编码与资源保留规则见[Cloudflare 部署说明](../../docs/cloudflare-deployment.md)。
