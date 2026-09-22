# Campus Viewer · 初星学园剧情档案

学园偶像大师剧情目录与翻译协作网站。角色、主线、辅助卡、活动及其他剧情使用统一索引，支持筛选、文本更新记录、逐句语音、翻译编辑、GitHub 协作任务和 CSV/TXT 批量导出。

## Docker 部署

要求 Docker Engine / Desktop 和 Compose v2：

```sh
git clone https://github.com/DreamGallery/campus-viewer.git
cd campus-viewer/deploy
cp .env.example .env
# 编辑 .env，填写访问地址与 GitHub OAuth Client ID、Client Secret
chmod 600 .env
docker compose up -d --build
docker compose logs -f updater
```

默认网页端口为 8080。OAuth 回调填写 `<CAMPUS_PUBLIC_ORIGIN>/api/auth/callback`；公网部署使用 HTTPS 反向代理。

镜像只包含代码、依赖和固定界面素材。首次启动后自动下载网站所需文本、图片和语音；初始化完成前显示进度。默认每 6 小时更新一次，失败重试，完整校验成功后才切换资源版本。数据在持久化卷中，普通升级不要执行 `down -v`。

页头显示游戏清单 revision，提供最近五个增量游戏资源包。首次仅建立下载包基线，后续按 HatsuboshiToolkit API 流程解密、分类、导出 PNG 并生成拉伸图片。网站资源初始化与全游戏增量打包是两个不同范围。

详细设置、更新、备份与验证限制见 [部署说明](deploy/README.md)。

## 本地开发

使用 Node.js 22.12+、Python 3.12+。索引器及数据流水线见 [索引器使用说明](docs/indexer.md) 和 [语音索引说明](docs/voice-index.md)。

```sh
npm ci
cp .env.oauth.example .env.oauth.local
# 填写 OAuth 配置和本地数据路径
node scripts/link-data.mjs /path/to/data/web
npm run dev:api
# 在另一个终端执行
npm run dev -- --host 127.0.0.1
```

OAuth 回调为 `http://127.0.0.1:5173/api/auth/callback`，地址不要混用 localhost 和 127.0.0.1。Vite 的本地资源路径可在 `.env.local` 中设置 `CAMPUS_WEB_DATA`、`CAMPUS_AUDIO_CLIPS`。不要将 Secret 放入 `VITE_` 环境变量。

任务列表要求登录且拥有工作仓库写权限；匿名用户仍可浏览剧情、本地编辑及导出。会话保存在 API 内存，重启后需要重新登录，当前采用单 API 实例。

编辑器回车自动序列化为 CSV 的字面 `\n`，每行超过 21 字会提示。TXT 回填按原文和说话人逐条匹配，保留脚本控制指令；批量导出读取远端正式稿，不包含浏览器未提交草稿。校对提交保留上游姓名词典处理，普通 TXT 下载保留原姓名。

正式稿按文件 SHA 和工序 revision 检查冲突，用单次 Git commit 提交多个文件。Issue 更新不支持跨接口事务；正式稿提交后状态同步失败会另行提示。

## 检查与打包

```sh
npm run lint
npm run build
npm run test:api
npm run test:workbench
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
python3 scripts/package_deploy.py
```

最后一个命令生成 `release/campus-story-deploy.tar.gz`，不包含环境配置、缓存和游戏资源。数据契约见 [剧情索引](docs/index-v2.md) 与 [语音索引](docs/voice-index.md)。

## 素材与来源

固定界面素材来源见 [官网素材说明](public/images/official/SOURCES.md) 和 [筛选图标说明](public/images/filters/SOURCES.md)。其余游戏资源在部署后获取。

字体使用 IBM Plex Sans、Plex Sans SC、Plex Sans JP，由 npm 包提供并本地打包。许可证在 `public/fonts/`；更换字体版本后运行 `python3 scripts/build-font-css.py` 更新 CSS。

翻译工序逻辑基于 [gakumas-viewer](https://github.com/chihya72/gakumas-viewer)，保留 [上游 MIT 许可证](src/workbench/upstream/LICENSE)。默认工作仓库为 [gakumas-translation-work](https://github.com/chihya72/gakumas-translation-work)。游戏资源及素材权利归各权利人所有，本项目为非官方网站。

## Cloudflare 混合部署

Workers + D1 托管网页和协作接口，R2 保存资源，Docker 更新器负责解包上传。详细配置、旧桶隔离、初始化、回滚边界与测试步骤见 [Cloudflare 部署文档](docs/cloudflare-deployment.md)。
