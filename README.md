# Campus Viewer · 初星学园剧情档案

学园偶像大师剧情目录与翻译协作网站，支持角色、主线、辅助卡、活动及其他剧情的分类、筛选和文本更新记录。

## 主要功能

- 剧情阅读与逐句语音，角色资料、卡面预览和浅色 / 深色主题。
- GitHub 登录、翻译 / 校对任务认领、远端草稿、提交与完成统计；协作任务仅对工作仓库有写权限的用户开放。
- CSV 导入、编辑与批量导出，译文回填原始 TXT 脚本；回车自动转换换行标记，每行超过 21 字提醒。
- 可展开的音乐播放器，支持封面、同步歌词、搜索、随机播放和单曲循环。
- Docker 自动更新 masterdb、剧情文本及游戏资源，提供最近五份增量资源包下载。

## 部署

| 方式 | 说明 |
| --- | --- |
| [Cloudflare Workers + R2](docs/cloudflare-deployment.md) | Workers 托管网页与协作接口，D1 保存登录会话，R2 保存资源，Docker 负责更新。 |
| [完整 Docker 部署](deploy/README.md) | 网页、协作接口和更新器均运行在 Docker 中，资源保存在持久化卷。 |
| [Docker 更新器](deploy/docker/README.md) | 拉取 Docker Hub 镜像，为 Cloudflare 部署下载、解包并上传资源。 |

镜像只包含代码、依赖与固定界面素材，游戏资源在部署后初始化。对话语音支持 FLAC、MP3、AAC，歌曲使用 FLAC；资源包首次只建立基线，之后收录新增或变化的游戏资源。

## 本地开发

需要 Node.js 22.12+、Python 3.12+，并准备本地资源目录。索引和资源获取见[索引器说明](docs/indexer.md)与[语音索引说明](docs/voice-index.md)。

```sh
npm ci
cp .env.oauth.example .env.oauth.local
# 填写 OAuth 配置和本地数据路径
node scripts/link-data.mjs /path/to/data/web
npm run dev:api
# 在另一个终端执行
npm run dev -- --host 127.0.0.1
```

OAuth 回调为 `http://127.0.0.1:5173/api/auth/callback`。Secret 只放服务端配置，不使用 `VITE_` 前缀。页脚显示 Git 提交号和构建时间；构建时可用 `CAMPUS_BUILD_REVISION` 指定版本号。

## 素材与来源

固定素材见[官网素材说明](public/images/official/SOURCES.md)和[筛选图标说明](public/images/filters/SOURCES.md)。字体使用 IBM Plex Sans、Plex Sans SC、Plex Sans JP，许可证在 `public/fonts/`。

翻译工序基于 [gakumas-viewer](https://github.com/chihya72/gakumas-viewer)，保留[上游 MIT 许可证](src/workbench/upstream/LICENSE)。默认工作仓库为 [gakumas-translation-work](https://github.com/chihya72/gakumas-translation-work)。游戏资源及素材权利归各权利人所有。
