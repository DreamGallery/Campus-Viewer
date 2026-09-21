# Docker 部署

## 第一次启动

安装 Docker Engine / Docker Desktop 及 Docker Compose v2。解压部署包后进入 `campus-story/deploy`：

```sh
cp .env.example .env
# 编辑 .env，填入公网访问地址、GitHub Client ID 和 Secret
chmod 600 .env
docker compose up -d --build
docker compose logs -f updater
```

OAuth 应用 Homepage 填 `CAMPUS_PUBLIC_ORIGIN`，回调填 `<CAMPUS_PUBLIC_ORIGIN>/api/auth/callback`。使用实际访问的同一个域名，不要混用 localhost、127.0.0.1 或局域网 IP。公网建议在前方配置 HTTPS 反向代理；示例仅开放网页端口，API 没有宿主机端口。

网页、API 与 Python 更新器均在仓库根目录，Compose 使用同一个构建上下文。通过 Git 克隆时也直接进入 `deploy/` 执行上述命令。

镜像包含代码、依赖与约 600 KB 的固定界面素材（校徽/背景/图标），并编译解码器；不抓取 masterdata、剧情 CSV/TXT、卡面或语音。容器启动后 updater 自动初始化：同步四个上游仓库 → 生成剧情索引 → 下载并校验音频包 → 解码 → 生成语音索引 → 下载图片 → 导出并检查网页目录 → 发布。首次完成之前网页显示初始化阶段，完成后自动加载。

首次语音资源可能占用数十 GB 和较长时间。下载并发默认 4、解码并发默认 2，可在 `.env` 调整。实际空间随游戏更新增加；部署前预留足够磁盘。

## 更新与重试

默认每 6 小时同步一次，失败 15 分钟后重试；间隔以完成本轮后计时。`CAMPUS_UPDATE_INTERVAL` 单位为秒，最低 300 秒。

```sh
# 查看状态与阶段
curl http://127.0.0.1:8080/api/resources/status
# 手动提前执行；与自动更新共用锁，不会并发破坏资源
docker compose exec updater python -m campus_story_index.runtime_update --once
# 更新网站代码或依赖后重建；资源卷不会因此清空
docker compose up -d --build
```

只有完整下载、构建和校验通过后才切换 `current`。失败保留上一版，首次失败则停留初始化页。相同内容复用校验通过的下载和解包缓存。上游移除的资源不自动清理，防止历史剧情失效。

## 数据与备份

命名卷 `campus-story_runtime` 保存 `repos/`、`cache/`、`releases/`、`current`、`status.json`。API 和 Nginx 只读挂载，只有 updater 写入。不要手工修改 updater 管理的 Git checkout；发现本地修改会拒绝更新。

发布版本的图片/音频与缓存使用硬链接节省空间，生产者采用原子替换避免修改旧版本；CSV/TXT 单独复制。旧发布版本暂不自动删除，便于回滚；请监控空间并在停止 updater 后清理确认不需要的旧版本。不要对发布版本文件原地写入。

备份整个资源卷和 `.env`。`docker compose down` 保留卷；`down -v` 会删除资源，不用于普通升级。翻译正式稿仍存放 GitHub，浏览器未提交草稿仅在各自浏览器内。

OAuth 会话仍在 API 内存里；重启 API 后重新登录即可。当前部署为单 API 实例，不适合直接扩容多副本；需要多副本时应先迁移共享会话存储。自动更新只更新文本/游戏资源，不会自动拉取并执行上游网站代码。

## 验证范围

本机无 Docker 引擎，未实际执行镜像构建或完整容器冷启动。前端生产构建、类型检查、lint、API/编辑器/更新器单元测试及本地浏览器验证已执行。首次 Linux 镜像构建需要能访问 npm、PyPI、Debian 和 GitHub；运行初始化还需要能访问游戏资源服务器。


## 资源版本下载

页头“学园剧情档案”下显示游戏资源清单的 `revision`（不是 Git 提交或网页 build_id），点击展开最近五个已成功生成的增量更新包。

首次部署仅为下载包建立资源清单基线，不抓取约 82 GB 的全游戏历史资源。网站自身需要的图片、剧情文本和语音仍正常初始化。后续 revision 改变时，将当前完整清单与上一成功基线按资源名称、大小、MD5 比较，下载所有类型中新增或变化的游戏文件，不局限于网页使用的素材。

处理参考 HatsuboshiToolkit 的 API 分支：校验下载 → AssetBundle 头部解密 → 按前缀分类 → 导出 Texture2D 原比例 PNG → 生成拉伸 PNG。角色卡全图及剧情 still 为 1440×2560、辅助卡全图为 2560×1440、漫画为 1024×768。原文件和原比例图片保留，另放 `stretch/`；无额外 WebP 压缩。资源文件（剧情脚本、ACB/AWB 等）按原文件保留，不放网站的 CSV、索引或 WAV。

包为 `.tar.gz`，包含 `assetbundle/`、`resource/`、`image/Texture2D/`、`stretch/` 中有变化的内容，以及 `package.json`（更新文件与移除清单）。没有变化的目录可能不存在。包只包含变化部分，不是可独立还原整个游戏的全量备份；跨越多个 revision 时提供上次成功基线到本次 revision 的累计差异，不伪造未观测版本。

所有处理与打包成功后才推进基线并发布链接；失败仍从原基线重试。相同 revision 不重复打包。第六个包成功发布后删除最旧下载包；发布快照的保留策略不变。已完成打包的临时处理缓存会清理，失败缓存用于重试。下载支持 HTTP Range。升级前备份原有资源卷；旧部署没有基线时升级首轮仅建立基线。
