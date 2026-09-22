# Debian / NAS：从 Docker Hub 运行资源更新器

镜像：`dreamgallery/campus-r2-updater:20260922-cf1`，架构 `linux/amd64`。

1. 将 `docker-compose.yaml` 放入 NAS 的专用目录。
2. 将已经填写的 `.env.r2.local` 单独复制到同一目录，执行 `chmod 600 .env.r2.local`。不要将它上传 Docker Hub 或 GitHub。
3. 在该目录运行：

```sh
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose logs -f --tail=100 updater
```

Compose 已包含默认镜像版本，不需要 `.env`。如果希望固定 digest 或升级版本，可将 `.env.example` 复制为 `.env` 再修改 `CAMPUS_UPDATER_IMAGE`。

首次下载与解包所需资源并建立增量基线；发布完成后网页自动读取 R2。之后每六小时更新。部署不需要开放入站端口，只需要出站访问 GitHub、游戏资源服务器和 R2。

`runtime` 卷保存下载缓存、Git 仓库、发布快照和增量基线。普通 `docker compose down` 会保留卷；不要执行 `down -v`。已有旧更新器时先停止旧实例，避免同时写入同一 R2 前缀。

更新器日志出现“更新完成”后，打开 https://viewer.hatsuboshi.xyz 检查章节、图片和语音。当前镜像已通过 Linux amd64/Python 3.12 下的 71 项回归测试、真实 ACB 解码、镜像启动检查和容器内 R2 只读连接验证；NAS 首次完整初始化需在该主机上验收。
