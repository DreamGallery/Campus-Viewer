# 完整 Docker 部署

网页、协作接口与资源更新器一起运行，资源保存在 Docker 持久化卷中。如使用 Cloudflare 托管网页，请参阅[混合部署说明](../docs/cloudflare-deployment.md)。

## 配置与启动

需要 Docker 和 Compose v2。在仓库的 `deploy/` 目录执行：

```sh
cp .env.example .env
chmod 600 .env
```

在 `.env` 中填写：

- `CAMPUS_PUBLIC_ORIGIN`：网站访问地址，默认端口为 `8080`。
- `GITHUB_CLIENT_ID`、`GITHUB_CLIENT_SECRET`：GitHub OAuth 应用配置。
- `HATSUBOSHI_CREDENTIALS_DIR`：游戏账号目录的绝对路径，目录内放置 `account.json`，格式为 `{"refresh_token":"..."}`。目录权限设为 `700`、文件为 `600`，保持可写以保存轮换令牌。

OAuth 回调填写 `<CAMPUS_PUBLIC_ORIGIN>/api/auth/callback`。公网访问需配置 HTTPS 反向代理。

```sh
docker compose config --quiet
docker compose up -d --build
docker compose logs -f --tail=100 updater
```

镜像不包含下载的游戏资源。首次启动自动获取 masterdb、剧情文本、图片、语音和音乐，完成前网页显示初始化进度。运行需要访问 GitHub 和游戏资源服务，并预留足够的磁盘空间。

## 更新与配置

默认每轮完成后等待六小时检查更新，失败后最多十五分钟重试。自动更新针对数据与资源；修改网站代码后需重新构建容器。

```sh
# 手动检查资源更新，与自动更新共用锁
docker compose exec updater python -m campus_story_index.runtime_update --once
# 更新代码后重新构建
docker compose up -d --build
```

`CAMPUS_UPDATE_INTERVAL` 控制间隔秒数；`CAMPUS_DOWNLOAD_WORKERS`、`CAMPUS_EXTRACT_WORKERS` 控制下载和解包并发。首次启动可设置[对话语音编码](../docs/cloudflare-deployment.md#首次初始化选择对话语音编码)，歌曲保持 FLAC。

默认 `CAMPUS_MASTER_SOURCE=api`，从游戏 API 获取完整 masterdb。设置为 `git` 可使用 Git 数据源，此时可移除 `/credentials` 挂载；API 失败不会自动回退。

## 数据保留

- `campus-story_runtime` 卷保存仓库、缓存、发布版本和资源包基线。备份该卷、`.env` 和账号目录；普通升级保留卷，不执行 `down -v`。
- 只有完整处理成功才切换 `current`，失败保留上次发布。历史发布不自动清理；停止更新器后，可删除确认不再需要的本地旧版本，保留 `current` 指向的目录。
- 图片与语音通过硬链接共享。重新解包替换缓存后，历史发布仍保留旧文件，直到相关链接全部删除才释放空间。
- 正式译文和任务保存在 GitHub，未提交的本地草稿保存在浏览器。此部署的登录会话在 API 内存中，重启后需重新登录。

页头提供[最近五份增量资源包](../docs/cloudflare-deployment.md#资源版本下载)。首次只建立下载包基线，网站自身资源仍会初始化。
