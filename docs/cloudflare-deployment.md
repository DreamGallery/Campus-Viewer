# Cloudflare Workers + R2 + Docker 更新器部署

本文对应分支 `codex/cloudflare-r2`。原有 `deploy/compose.yaml` 完整 Docker 部署仍然有效。不要同时向同一 R2 前缀运行多个更新器。

## 1. 结构与数据流

- Workers Static Assets：React 网页、字体、固定 UI 图片，不包含下载的游戏资源。
- Workers API：复用 `server/app.mjs` 的 OAuth、仓库权限检查、协作读写、冲突检查逻辑。
- D1：保存 OAuth 临时状态和会话。cookie 标识取 SHA-256 后入库，GitHub token 等数据使用 AES-GCM 加密；密钥在 Workers Secret 中。OAuth 状态通过 SQL 原子消费，防止重复回调。
- R2：剧情索引、CSV、TXT、图片、语音和最近五个增量资源包。
- Docker 更新器：同步 GitHub → 下载/解包 → 生成索引 → 完整上传 → 更新 `current.json`。
- GitHub 工作仓库仍是翻译、校对、任务和操作记录的权威来源，D1 不存储这些业务数据。

更新器必须运行在有足够磁盘、能访问 GitHub 和游戏资源服务器的电脑、NAS 或服务器上；不是运行在普通 Workers 中。首次初始化仍会下载网站所需的图片和语音；“首次只建立基线”仅指全游戏增量包，不代表初始化无需下载。

## 2. 已知配置与需要准备的信息

本文以桶名 `your-bucket`、资源域名 `https://assets.example.com` 为例，部署时请替换为自己的配置。实际账号及桶配置应写入被 Git 忽略的 `wrangler.local.jsonc` 和 `deploy/.env.r2.local`，不要提交到仓库。

需要准备：

1. Cloudflare 账号的 Workers、R2 和 D1 使用权限。
2. R2 的 Access Key ID / Secret Access Key，权限为指定桶的 Object Read & Write。它们只放更新器环境文件，不放前端或 Worker。
3. 网站域名；可以先使用 Cloudflare 分配的 `workers.dev` 地址。
4. 一个 GitHub OAuth App 的 Client ID 和 Client Secret。
5. Node.js 22、npm；更新器主机安装 Docker Engine/Desktop 和 Docker Compose 插件。

`assets.example.com` 是资源域名，不是默认的网站域名。两者可以独立。不要把网站 Worker 路由覆盖到现有 R2 域名。

## 3. 本地文件与保密范围

| 文件 | 用途 | 提交 Git |
| --- | --- | --- |
| `wrangler.jsonc` | 可复用 Worker 配置模板 | 是 |
| `wrangler.local.jsonc` | 实际账号、桶名、D1 ID、站点域名 | 否 |
| `.dev.vars` | 本地 OAuth 和会话密钥 | 否 |
| `.dev.vars.example` | 空白示例 | 是 |
| `deploy/.env.r2.local` | 更新器真实 R2 配置 | 否 |
| `deploy/.env.r2.example` | 更新器配置示例 | 是 |
| `.wrangler/` | 本地模拟数据库、R2 和开发缓存 | 否 |
| `.cloudflare-dist/` | 仅用于 Workers 的构建输出 | 否 |

不要将 S3 Secret、OAuth Secret、SESSION_SECRET 发到聊天或提交到 Git。Cloudflare 登录凭证也不需要写进项目代码。

## 4. 安装与本地测试

以下命令在仓库根目录运行：

```sh
npm ci
npm run build:cloudflare
npm run test:api
npm run test:workbench
npm run test:cloudflare
```

`build:cloudflare` 先从固定素材白名单构建 `.cloudflare-dist`，再执行 Wrangler dry-run，**不会部署到远端**。不要直接把本机普通 `dist` 上传到 Workers：旧的 `public` 资源链接可能使它包含大量游戏数据。

若本地配置不存在，先复制：

```sh
cp wrangler.jsonc wrangler.local.jsonc
cp .dev.vars.example .dev.vars
cp deploy/.env.r2.example deploy/.env.r2.local
```

已有文件不要覆盖。`.dev.vars` 中填写：

```dotenv
GITHUB_CLIENT_ID=你的客户端ID
GITHUB_CLIENT_SECRET=你的客户端密钥
SESSION_SECRET=至少32字符的随机密钥
```

可以使用 `openssl rand -hex 32` 生成 SESSION_SECRET。不要使用示例字符串作为正式密钥。

```sh
npx wrangler d1 migrations apply campus-auth --local --config wrangler.local.jsonc
npx wrangler dev --config wrangler.local.jsonc --port 8788
```

访问 `http://127.0.0.1:8788`。本地默认使用模拟 R2/D1，不读取真实桶；没有模拟资源时显示等待初始化是正常行为。不要添加 `remote: true`，除非明确准备测试真实资源。

本地 OAuth App 设置：Homepage 为 `http://127.0.0.1:8788`，回调为 `http://127.0.0.1:8788/api/auth/callback`。原来的 5173 开发环境仍可单独运行。

## 5. 准备 Cloudflare 资源

```sh
npx wrangler login
npx wrangler whoami
npx wrangler d1 create campus-auth
```

D1 创建成功后，将返回的数据库 ID 填入 `wrangler.local.jsonc` 的 `d1_databases[0].database_id`。确认：

- `account_id` 是桶所在账号。
- `r2_buckets[0].bucket_name` 是 `your-bucket`，binding 为 `RESOURCES`。
- D1 binding 为 `DB`。
- `CAMPUS_R2_PREFIX` 是专用前缀 `campus-v1`，与更新器完全一致。
- `CAMPUS_PUBLIC_ORIGIN` 改为最终网站 origin，例如 `https://story.example.com`，不带子路径。
- `CAMPUS_R2_PUBLIC_BASE_URL` 可设为 `https://assets.example.com`，不包含 `campus-v1`。

本地配置中设置公开资源域名时，下载包接口会在检查最近五版白名单后跳转至该域名。未配置公开域名时，Worker 会通过 R2 binding 流式返回文件，支持 HEAD 和单段 Range。

创建正式 D1 表：

```sh
npx wrangler d1 migrations apply campus-auth --remote --config wrangler.local.jsonc
```

这是实际远端写操作。D1 只用于会话，不要共用已有其他业务的同名表。

## 6. GitHub OAuth 与正式密钥

在 GitHub OAuth App 中设置最终站点地址与回调：

```text
Homepage URL: https://你的站点域名
Callback URL: https://你的站点域名/api/auth/callback
```

通过交互命令填写正式密钥：

```sh
npx wrangler secret put GITHUB_CLIENT_ID --config wrangler.local.jsonc
npx wrangler secret put GITHUB_CLIENT_SECRET --config wrangler.local.jsonc
npx wrangler secret put SESSION_SECRET --config wrangler.local.jsonc
```

本地 `.dev.vars` 不会自动成为正式 Secret。修改 SESSION_SECRET 会使已有会话无法解密，需要重新登录；正常重启/重新部署不会丢失 D1 中的会话。会话最长八小时，失效后重新登录；目前不自动刷新 GitHub token。

`CAMPUS_WORK_OWNER` / `CAMPUS_WORK_REPO` / `CAMPUS_WORK_BRANCH` 控制协作仓库，默认仍为 `chihya72/gakumas-translation-work` 的 `main`。没有写权限的账号不能查看协作任务或提交。

## 7. R2 域名与缓存

确认桶的设置中已把 `assets.example.com` 绑定为公开自定义域名，并且 Cloudflare DNS 正常。

新对象布局：

```text
campus-v1/
  current.json                         # 最后切换的发布指针，no-store
  media/<sha256>/<filename>             # 去重图片、语音，长期缓存
  releases/<release>/web/catalog/...    # 不可变目录和章节索引
  releases/<release>/story/CSV/...      # 原文 CSV
  releases/<release>/adv/...            # 原始 TXT
  releases/<release>/resource-snapshot.json
  releases/<release>/resource-versions.json
  downloads/campus-resources-r....tar.gz
```

图片/语音链接在上传时改写为内容地址；本机 Docker 的原始索引不受影响。索引按发布版本寻址，更新后已经打开的页面仍能读取原版本目录。

静态媒体可以对 `campus-v1/media/` 设置缓存规则。**不要给整个桶设置忽略源站缓存头的永久缓存**：`current.json` 和下载包不应缓存。不要给 `campus-v1/` 整个前缀添加短期自动删除规则。

网页索引和 API 通过同源 Worker 读取，普通图片和 audio 标签可以直接使用资源域名；如果将来添加浏览器 `fetch` 音频或画布读取图片，可在 R2 CORS 中允许站点 origin 的 GET/HEAD，允许 Range 并暴露 Content-Length、Content-Range、ETag。不要为上传开放浏览器写权限。

## 8. Docker 更新器

编辑 `deploy/.env.r2.local`：

| 变量 | 含义 |
| --- | --- |
| `CAMPUS_R2_ENDPOINT` | 桶设置中的 S3 API endpoint，一般为 `https://<account>.r2.cloudflarestorage.com`；特殊 jurisdiction 使用控制台实际地址 |
| `CAMPUS_R2_BUCKET` | `your-bucket` |
| `CAMPUS_R2_PREFIX` | `campus-v1` |
| `AWS_ACCESS_KEY_ID` | R2 S3 Access Key ID |
| `AWS_SECRET_ACCESS_KEY` | R2 S3 Secret Access Key |
| `CAMPUS_R2_PUBLIC_BASE_URL` | `https://assets.example.com`；空白则媒体通过 Worker |
| `CAMPUS_UPDATE_INTERVAL` | 成功后检查间隔，默认 21600 秒（六小时） |
| `CAMPUS_DOWNLOAD_WORKERS` | 下载并行度，默认 4 |
| `CAMPUS_EXTRACT_WORKERS` | 解包并行度，默认 2 |
| `CAMPUS_UPLOAD_WORKERS` | 上传并行度，默认 4 |

先单次初始化，检查日志再启用循环：

```sh
docker compose -f deploy/compose.r2.yaml build updater
docker compose -f deploy/compose.r2.yaml run --rm updater python -m campus_story_index.runtime_update --once
docker compose -f deploy/compose.r2.yaml up -d
docker compose -f deploy/compose.r2.yaml logs -f --tail=100 updater
```

容器首次运行会克隆必要仓库、下载网站所需资源并解包。全游戏资源包首次只保存 baseline；之后 revision 改变才打包新增/变化资源，包含既有图片拉伸处理，保留最近五包。

更新器的 `/runtime` 使用持久卷，保存 Git 仓库、缓存、baseline、发布快照。**不要执行 `down -v`**，它会删除基线和下载缓存。定期备份该卷。

已初始化本地 Docker 资源但还没上传时，也可以只执行上传：

```sh
docker compose -f deploy/compose.r2.yaml run --rm updater python -m campus_story_index.r2_publish
```

该命令要求同一持久卷已有 `current` 发布。原完整 Docker compose 与新 compose 默认项目名不同，卷不会自动共享；迁移已有卷应显式配置 `external` 卷及真实卷名。

## 9. 发布一致性、失败与保留策略

1. 上传媒体，按 SHA-256 和对象元数据跳过已存在的同内容文件。
2. 上传独立版本的索引、CSV/TXT、快照和增量包。
3. 使用 ETag 条件更新 `current.json`，拒绝并发覆盖。
4. 切换本地 `current`，更新本地状态。
5. 删除上一版本列表中已超出最近五版的包，只处理本项目前缀内明确记录的文件。

上传中断时远端指针不变，旧站点继续可用。失败每至多十五分钟重试。远端状态接口显示的是**最后成功发布状态**，不会展示尚未上传成功的本地错误，失败详情看 Docker 日志。

旧桶其他前缀不会读取、覆盖或删除。媒体和章节快照暂不自动垃圾回收，以支持已打开的页面和回滚；历史文本版本会占用存储，应根据实际用量安排维护。失败上传也可能留下未引用的对象，不会被网站展示。

如果远端已发布但本地卷丢失，更新器会拒绝重新建立 baseline。应恢复卷备份；确实要全新开始时，使用新的专用前缀并同步修改 Worker 配置。若远端指针切换成功后本机异常退出，先核对远端 release 与本地 `releases/`，恢复本地 `current` 至同一 release，再继续更新。不要直接删除远端指针绕过保护。

## 10. 正式部署与验收

本地检查全部通过、账号配置确认后：

```sh
npm run build:cloudflare
npx wrangler deploy --config wrangler.local.jsonc
```

Wrangler 部署只上传本地构建到 Cloudflare，**不需要先推送 GitHub，也不会推送 Git 分支**。如启用 Git 自动部署，请明确选择混合部署分支。

若使用自定义域名，可在 Cloudflare Worker 的 Settings → Domains & Routes 添加，并同步更新 OAuth App 和 `CAMPUS_PUBLIC_ORIGIN`。可以使用独立测试站点与测试前缀，避免测试污染正式发布。

上线验收：

- `/api/health` 返回 `ok: true`。
- 初始化前目录显示等待资源；发布后角色、辅助卡、活动和更新页面正常。
- `catalog/manifest.json` 的 base_path 带 release，图片和语音指向预期资源域名。
- 语音播放、拖动、暂停正常；下载包的 HEAD/Range 可用。
- 登录后刷新和重新部署仍保持会话；退出后旧 cookie 无效。
- 无权限账号看不到任务，有权限账号能读取任务；提交测试需选用专门测试工作仓库。
- 章节 CSV/TXT 导出、格式校验及语音匹配正常。
- 新版上传失败时旧版仍可访问；成功后资源版本更新，只有最近五包显示。
- 检查 Workers CPU、D1 操作量、R2 存储和请求用量，再决定是否升级套餐。

## 11. 故障定位

| 现象 | 排查方向 |
| --- | --- |
| 一直等待初始化 | Docker 是否成功、桶名/前缀是否一致、R2 是否存在 current.json |
| OAuth 回调失败 | origin 与 GitHub callback 是否精确一致，是否混用 localhost/127.0.0.1，D1 迁移和 Secret 是否已配置 |
| 登录后 API 500 | SESSION_SECRET 是否一致、是否更换密钥、D1 表是否存在 |
| 图片或语音 404 | 自定义域名是否绑定正确桶、链接是否包含 prefix、是否误删 media |
| 网页更新但索引未变 | 检查 current.json、缓存规则、更新器日志；网页部署与资源发布是两条独立流程 |
| R2 返回 403 | S3 endpoint、Access Key、指定桶读写权限 |
| 上传出现条件冲突 | 是否有第二个更新器或人工修改发布指针，不要强制覆盖 |
| Workers CPU 超限 | 查看日志/指标，评估付费 CPU 配额；解包始终留在 Docker |

官方参考：[Workers Node HTTP](https://developers.cloudflare.com/workers/runtime-apis/nodejs/http/)、[Workers SPA](https://developers.cloudflare.com/workers/static-assets/routing/single-page-application/)、[R2 绑定](https://developers.cloudflare.com/r2/api/workers/workers-api-usage/)、[R2 S3 兼容性](https://developers.cloudflare.com/r2/api/s3/api/)、[D1 预编译语句](https://developers.cloudflare.com/d1/worker-api/prepared-statements/)。

## 12. Mac 构建并推送 Docker Hub，Debian/NAS 只拉取镜像

Mac 需要已启动的 Docker Engine（Docker Desktop 或 Colima），以及 Buildx。Apple Silicon 为 ARM64，如果 NAS 为 x86_64，必须构建 linux/amd64；也可发布包含 amd64、arm64 的多架构镜像。Docker 会自动选取匹配 NAS 的架构。

Mac 仓库根目录执行，使用自己的 Docker Hub 仓库及唯一版本号：

```sh
docker login
sh scripts/publish_updater_image.sh dreamgallery/campus-r2-updater 20260925-cf9 linux/amd64
```

构建过程不需要 R2 密钥。`.dockerignore` 的白名单与 Dockerfile 的显式 COPY 会排除实际环境文件和下载资源。脚本逐架构验证 Python 依赖、解码器和入口后，只推送指定版本标签，不覆盖 latest，不改变当前 Docker context。跨架构仿真编译首次可能较慢。

NAS 需要 Compose 和 R2 配置，另可用 `.env` 覆盖镜像版本，放在同一目录：

- `deploy/nas/docker-compose.yaml` → `docker-compose.yaml`
- 可选：`deploy/nas/.env.example` → `.env`，覆盖镜像版本或固定 digest；默认使用 `dreamgallery/campus-r2-updater:20260925-cf9`。
- 已填好的 `deploy/.env.r2.local` → `.env.r2.local`，单独传输，不要放到 Docker Hub。

在 NAS 上执行：

```sh
chmod 600 .env.r2.local
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose logs -f --tail=100 updater
```

旧版 `docker-compose` 可使用相应命令，但建议安装 Docker Compose v2 插件。私有 Docker Hub 仓库需要在 NAS 上先 `docker login`。此部署不需要监听端口、特权模式或挂载 Docker socket。

升级时先修改 `.env` 中的镜像版本，再执行 `docker compose pull && docker compose up -d`。游戏资源由容器内部每六小时更新，不依赖镜像重建；只有更新器代码变化才需发布新镜像。

Compose 使用 `campus-r2-updater_runtime` 命名卷，与默认的源码构建版本项目/卷名称一致。在同一 Docker 主机迁移时，先停止旧容器再启动新配置，勿删除数据卷、勿同时启动两个更新器。命名卷实际名称可用 `docker volume ls` 核对。

本地构建不等于已验证 NAS 的完整冷启动。首次部署请观察日志，确认下载、解包和 R2 发布完整成功后，再进行网站资源验收。

构建时如果默认 Debian 线路较慢，可设置 `CAMPUS_DEBIAN_MIRROR=https://mirrors.ustc.edu.cn` 再运行发布脚本，软件包签名校验保持启用。该参数只影响镜像构建，不需要放入 NAS 的 R2 环境文件。

Python 包下载也可通过 `CAMPUS_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` 指定镜像；默认仍使用 PyPI 官方源。当前 NAS 镜像为 `dreamgallery/campus-r2-updater:20260925-cf9`（linux/amd64）。


### R2 上传进度

通过 `docker compose logs -f updater` 查看。图片与语音、文本与索引、增量资源包、版本信息分别统计；每个阶段开始、结束以及运行期间每 10 秒输出一次进度。日志包含已处理文件数、比例、已上传数、校验一致而跳过的文件数、失败数、本轮传输 MiB 和耗时。大文件上传或请求重试期间也会持续输出。

百分比按文件数计算（包含跳过和失败），不是字节比例；100% 不代表发布成功，应以最后的 `R2: 发布完成` 为准。传输量来自 SDK 回调，不含跳过的资源。发布前扫描和计算媒体校验值会先显示提示。

升级 NAS 时，将现有 Compose 的镜像或 `.env` 中 `CAMPUS_UPDATER_IMAGE` 改为 `dreamgallery/campus-r2-updater:20260925-cf9`，然后执行 `docker compose pull updater` 和 `docker compose up -d updater`。保留原有挂载路径、内存限制和环境配置。

更新器还会输出每轮检查开始、各处理阶段及下次检查时间（UTC）；成功后默认等待 6 小时，失败后最多等待 15 分钟重试。


### 远端媒体批量检查

远端媒体检查使用分页列举专用 `campus-v1/media/` 前缀，每页最多 1000 项。已有媒体按路径中的 SHA-256 和文件大小匹配后跳过；大小冲突会停止发布。依赖该前缀由更新器管理且对象不被外部覆盖，不将 S3 ETag 当作内容哈希。未列出的媒体仍执行 HEAD 校验再上传；文本与索引的增量处理见下一节，资源包保持原有校验。需要 R2 列举对象权限（标准桶对象读写令牌包含）。本地媒体 SHA-256 扫描仍保留，因此首次扫描时间取决于磁盘速度。


### 文本增量发布与无变化跳过

每轮仍先拉取四个源仓库并获取游戏资源清单。根据仓库 HEAD、完整资源清单、更新器 Python 代码及 CAMPUS 配置生成摘要；仅在上次成功发布的摘要一致时跳过索引构建、解包和 R2 发布。CSV/ADV 仓库单独更新也会触发处理，不依赖游戏 revision 改变。首次升级没有摘要会正常运行一次。可临时设置 `CAMPUS_FORCE_UPDATE=1` 强制运行，完成后移除。

文本与索引采用 `text/<SHA-256>/<文件名>` 保存，发布目录中的 `file-map.json` 映射逻辑路径。未变化的 CSV/TXT 复用上一成功版本（也支持旧版直接路径），其他文件根据内容批量比对后跳过。索引包含版本链接时仍需上传相应变更；失败不会切换 current.json。不要手动删除仍被映射引用的旧发布目录或 text 对象。

必须先部署本版兼容映射读取的 Workers，再升级镜像 `dreamgallery/campus-r2-updater:20260925-cf9`；Workers 同时支持 cf4 及更早的目录布局。NAS 继续保留现有挂载、限制与密钥配置，修改镜像后 pull/up 即可。

## 资源包解压权限

从 `20260925-cf9` 起，新生成的资源包统一使用目录 `755`、文件 `644` 权限，不继承 NAS 的所有者名称或额外 ACL。已发布的旧资源包不会自动重新生成；旧包解压后若无权限，需要在解压目录中修复权限。
