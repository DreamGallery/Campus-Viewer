# Cloudflare Workers + R2 + Docker 更新器

Workers 托管网页和协作接口，D1 保存登录会话，R2 保存游戏资源；Docker 更新器负责下载、解包、生成索引和上传。译文、草稿与协作任务保存在 GitHub 工作仓库。

## 准备配置

需要 Cloudflare 的 Workers、R2、D1 权限，GitHub OAuth App，以及 Node.js 22.12+、Docker 和 Compose v2。

以下命令在仓库根目录运行，已有配置文件请保留：

```sh
npm ci
cp wrangler.jsonc wrangler.local.jsonc
npx wrangler login
npx wrangler d1 create campus-auth
```

在 `wrangler.local.jsonc` 中填写：

| 配置 | 内容 |
| --- | --- |
| `account_id` | R2 所在 Cloudflare 账号 |
| `r2_buckets[0].bucket_name` | 现有桶名，绑定名保留 `RESOURCES` |
| `d1_databases[0].database_id` | 创建 D1 时返回的 ID，绑定名保留 `DB` |
| `vars.CAMPUS_PUBLIC_ORIGIN` | 网站地址，例如 `https://story.example.com` |
| `vars.CAMPUS_R2_PREFIX` | 专用资源前缀，默认 `campus-v1` |
| `vars.CAMPUS_R2_PUBLIC_BASE_URL` | 可选资源域名，例如 `https://assets.example.com`，不含前缀 |
| `vars.CAMPUS_WORK_OWNER`、`vars.CAMPUS_WORK_REPO`、`vars.CAMPUS_WORK_BRANCH` | 默认工作仓库为 `chihya72/gakumas-translation-work` 的 `main` |

网站与资源使用各自的域名；资源域名需绑定到 R2 桶。未配置公开资源域名时，文件通过 Worker 读取。实际配置、账号和密钥文件已由 Git 忽略，不提交仓库。

## 登录与网页部署

GitHub OAuth App 的 Homepage 填网站地址，Callback 填 `<网站地址>/api/auth/callback`。

```sh
npx wrangler d1 migrations apply campus-auth --remote --config wrangler.local.jsonc
npx wrangler secret put GITHUB_CLIENT_ID --config wrangler.local.jsonc
npx wrangler secret put GITHUB_CLIENT_SECRET --config wrangler.local.jsonc
npx wrangler secret put SESSION_SECRET --config wrangler.local.jsonc
npm run build:cloudflare
npx wrangler deploy --config wrangler.local.jsonc
```

`SESSION_SECRET` 使用至少 32 字符的随机值，可用 `openssl rand -hex 32` 生成。更换它会使已有会话失效；正常重新部署保留 D1 会话。游客可阅读原文、本地编辑及导入导出；工作仓库中的任务、译文、草稿和用户资料均要求登录并具有仓库写权限。协作请求在解析正文前验证会话、CSRF 和权限。

`build:cloudflare` 只打包代码、字体与固定界面素材，并进行部署预检查；随后执行 `wrangler deploy` 才会上线。自定义网站域名在 Worker 的 Domains & Routes 中配置，并与 OAuth 回调和 `CAMPUS_PUBLIC_ORIGIN` 保持一致。

本地预览可复制 `.dev.vars.example` 为 `.dev.vars` 并填写密钥，然后运行：

```sh
npx wrangler d1 migrations apply campus-auth --local --config wrangler.local.jsonc
npx wrangler dev --config wrangler.local.jsonc --port 8788
```

本地默认使用模拟 R2 / D1，无资源时显示等待初始化；OAuth 回调使用 `http://127.0.0.1:8788/api/auth/callback`。`.dev.vars` 不会自动同步为正式 Secret。

## 限流与缓存

`wrangler.local.jsonc` 使用模板中的两个 `ratelimits` 绑定，设置 `workers_dev: false`、`preview_urls: false`，通过自定义域名提供服务。限流命名空间 ID 在同一账号内应与其他应用区分。

- `LOGIN_RATE_LIMITER`：每 IP 每分钟 10 次登录，超过后返回 429，不写入 D1。
- `RESOURCE_MISS_LIMITER`：公开目录、原文 CSV / TXT、资源状态、媒体、歌单与下载接口每 IP 每分钟允许 300 次需要读取 R2 的请求；同一请求只计一次，全部命中缓存时不计数。

这些限制使用 Workers 原生绑定，按 Cloudflare 节点近似计数；不是全局硬上限，共享出口的用户共用额度。阈值可在 `ratelimits[].simple` 中调整。可另外为 `/api/auth/login` 配置 Cloudflare 限流规则，在进入 Worker 前拦截请求；部署代码不会创建该规则。

Worker 缓存带版本或内容哈希的完整资源（单个不超过 8 MiB），版本指针缓存 30 秒，不存在的资源缓存 15 秒。资源状态接口共享版本指针缓存，缓存失效后先检查限流，再读取 R2。普通 GET 直接读取 R2；覆盖全文件的音频请求可建立完整缓存，供后续分段播放复用。登录、会话和 GitHub 协作响应不进入公共缓存，较大的媒体和下载包使用流式传输。

使用 R2 自定义域名直连的媒体不经过上述 Worker 缓存和限流，需在该域名单独设置缓存规则，覆盖带哈希的图片及音频路径（包括 FLAC），并忽略这些不可变资源的查询参数。不要将此规则扩展到版本指针、登录或协作接口。

## Docker 更新器

按 [Docker 更新器说明](../deploy/docker/README.md)准备 `docker-compose.yaml`、`.env`、`.env.r2.local` 和游戏账号目录，然后拉取镜像启动。默认使用游戏 API masterdb 和 Toolkit 的 `API` 分支；设置 `CAMPUS_MASTER_SOURCE=git` 可改用 Git masterdata。

`.env.r2.local` 的主要设置：

| 变量 | 内容 |
| --- | --- |
| `CAMPUS_R2_ENDPOINT` | R2 控制台提供的 S3 API endpoint |
| `CAMPUS_R2_BUCKET` | 桶名，与 Worker 相同 |
| `CAMPUS_R2_PREFIX` | 专用前缀，与 Worker 相同 |
| `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY` | 限定该桶的 Object Read & Write 密钥，需能列举对象 |
| `CAMPUS_R2_PUBLIC_BASE_URL` | 可选资源域名，不含前缀，与 Worker 相同 |
| `CAMPUS_UPDATE_INTERVAL` | 每轮完成后的检查间隔，默认 `21600` 秒 |
| `CAMPUS_DOWNLOAD_WORKERS` | 下载并发，默认 `4` |
| `CAMPUS_EXTRACT_WORKERS` | 解包并发，默认 `2` |
| `CAMPUS_UPLOAD_WORKERS` | 上传并发，默认 `4` |

游戏账号目录通过 `.env` 中的 `HATSUBOSHI_CREDENTIALS_DIR` 挂载为 `/credentials`，不要仅写在服务的 `.env.r2.local` 中。账号目录保持可写，以保存轮换后的令牌。

首次运行会下载网站所需的文本、图片、语音和音乐。后续同时检查游戏资源、masterdb、CSV / TXT 仓库以及更新器代码和配置；文本仓库单独更新也会触发处理。无变化时跳过构建和上传。

```sh
# 在 docker-compose.yaml 所在目录执行
docker compose logs -f --tail=100 updater
# 手动检查更新，与自动更新共用锁
docker compose exec updater python -m campus_story_index.runtime_update --once
```

日志显示每个阶段和下次检查时间。R2 上传每十秒报告上传、跳过、失败数量与传输量；百分比按文件数计算，以 `R2: 发布完成` 为成功标志。失败后最多十五分钟重试。

### 首次初始化选择对话语音编码

首次启动前在 `.env.r2.local` 中设置；完整 Docker 部署使用 `deploy/.env`：

```dotenv
CAMPUS_VOICE_FORMAT=aac
CAMPUS_VOICE_BITRATE=128
```

| 格式 | 后缀 | 码率 |
| --- | --- | --- |
| `flac`（默认） | `.flac` | 留空，8 级无损压缩 |
| `mp3` | `.mp3` | 默认 128 kbps；支持 32/40/48/56/64/80/96/112/128/160/192/224/256/320 |
| `aac` | `.m4a` | 默认 128 kbps；支持 32–320 的整数值 |

码率可填 `128` 或 `128k`。设置保存在 `/runtime/voice-encoding.json`，重启沿用；显式指定不同设置会停止更新。尝试其他格式需使用独立 runtime，不能直接修改现有记录。歌曲始终使用 FLAC。

### 音乐资源

默认收录全部演唱版本，排除伴奏和 BGM，包含游戏封面和时间轴歌词；无匹配时间轴时显示暂无同步歌词。

- `CAMPUS_MUSIC_SCOPE=vocal`：默认范围；`all` 包含伴奏和 BGM。
- `CAMPUS_MUSIC_IDS`：可选，空格分隔的 Music ID；留空则自动跟随游戏更新。

音乐使用独立的 `music/current.json` 指针，全部文件上传成功后才切换歌单。缓存位于 `/runtime/cache/music-source`，可播放资源位于 `/runtime/cache/music`。

## 资源版本下载

页头显示游戏资源清单的 `revision`，提供最近五份已成功生成的增量资源包。首次仅建立打包基线；后续比较完整游戏资源清单，下载新增或变化的资源，不限于网页所需素材。跨版本更新包包含上次成功基线以来的累计差异。

包保留原始 AssetBundle、脚本与 ACB/AWB 等文件，并导出原比例 PNG 和拉伸图片。角色卡全图及剧情 still 为 1440×2560，辅助卡全图为 2560×1440，漫画为 1024×768；不包含网站 CSV、索引和拆分语音。

`.tar.gz` 按内容包含 `assetbundle/`、`resource/`、`image/Texture2D/`、`stretch/` 和变更清单 `package.json`。目录权限为 `755`、文件为 `644`。全部处理成功才推进基线；第六份发布成功后删除最旧下载包。

## 发布与数据保留

R2 对象使用以下布局，前缀可自行配置：

```text
campus-v1/
  current.json                         # 当前剧情资源版本
  media/<sha256>/<filename>             # 图片、语音、歌曲
  text/<sha256>/<filename>              # CSV、TXT、索引和歌词
  releases/<release>/file-map.json      # 逻辑路径与内容对象的映射
  releases/<release>/resource-snapshot.json
  releases/<release>/resource-versions.json
  music/current.json                   # 当前歌单
  downloads/campus-resources-r....tar.gz
```

媒体与文本按文件内容去重。剧情资源上传完整后，通过条件写入切换 `current.json`，然后切换本地 `current`。上传中断不会切换对应发布指针，重试可复用已上传对象；同一前缀只运行一个更新器。

`/runtime` 保存仓库、缓存、发布版本和增量基线，需定期备份；升级保留现有挂载，不执行 `down -v`。若远端已有发布而本地卷丢失，应恢复备份，不能直接删除远端指针重新初始化。

本地历史发布通过硬链接共享图片与语音，缓存被新文件替换后，历史版本仍占用旧文件的空间。停止更新器后可清理不需要的本地旧版本，保留 `current` 指向的目录。R2 媒体、文本和发布映射不自动清理，删除前需核对全部引用，不能按本地目录的规则直接删除。

资源域名可缓存不可变的 `media/` 和 `text/` 对象；`current.json` 与下载包遵循源站缓存头。不要对整个前缀设置永久缓存或自动删除规则。网页部署与游戏资源发布分别进行，更新网页不会自动更新 R2 数据。

## 常见问题

| 现象 | 检查项 |
| --- | --- |
| 一直等待初始化 | Docker 日志、桶名和前缀是否一致、是否存在 `current.json` |
| OAuth 回调失败 | 网站地址与回调是否一致、D1 迁移和 Secret 是否配置 |
| 登录后 API 报错 | D1 表、`SESSION_SECRET`，以及 Worker 日志 |
| 图片或语音 404 | 资源域名绑定、前缀、是否误删资源 |
| R2 返回 403 | endpoint、密钥和桶读写权限 |
| 发布条件冲突 | 是否有多个更新器，或手动改过发布指针 |
| 网页显示旧资源 | Docker 是否完成发布、指针和缓存规则；远端状态只显示最后成功发布 |
