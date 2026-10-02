# Debian / NAS：从 Docker Hub 运行资源更新器

镜像：`dreamgallery/campus-r2-updater:20261003-masterdb`，架构 `linux/amd64`。

1. 将 `docker-compose.yaml` 放入 NAS 的专用目录。
2. 将已经填写的 `.env.r2.local` 单独复制到同一目录，执行 `chmod 600 .env.r2.local`。不要将它上传 Docker Hub 或 GitHub。
3. 创建私有目录，放入专用游戏账号的 `account.json`（`{"refresh_token":"..."}`），目录权限 700、文件 600。在 `.env` 中设置 `HATSUBOSHI_CREDENTIALS_DIR=/绝对路径/账号目录`。令牌只挂载到容器，不写入镜像。
4. 在该目录运行：

```sh
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose logs -f --tail=100 updater
```

Compose 已包含默认镜像版本；`.env` 用于指定游戏账号目录。如果希望固定 digest 或升级版本，可将 `.env.example` 复制为 `.env` 再修改 `CAMPUS_UPDATER_IMAGE`。

首次下载与解包所需资源并建立增量基线；发布完成后网页自动读取 R2。之后每轮完成后等待六小时再次检查，未变化时跳过构建和上传。部署不需要开放入站端口，只需要出站访问 GitHub、游戏资源服务器和 R2。

`runtime` 卷保存下载缓存、Git 仓库、发布快照和增量基线。普通 `docker compose down` 会保留卷；不要执行 `down -v`。已有旧更新器时先停止旧实例，避免同时写入同一 R2 前缀。

更新器日志出现“更新完成”后，打开已配置的网站检查章节、图片和语音。日志每 10 秒显示上传进度，并在每轮结束时显示下次检查时间。完整的 Workers、R2 与 OAuth 配置见 [混合部署文档](../../docs/cloudflare-deployment.md)。

新版默认从游戏 API 获取 masterdb，不再依赖 gakumasu-diff 的更新速度。所有表完整解析后才用于索引；失败保留上次已发布资源。版本与 schema 哈希参与增量判断。
