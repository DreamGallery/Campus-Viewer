# 剧情语音与 CSV 对应索引 v1

这一步生成可供翻译网站使用的离线数据，不修改原 CSV。剧情分类继续使用 v2 目录：主线、角色、辅助卡、活动、其他。

## 数据链路

`story-index.json → script_id → 原始 ADV + CSV → voice_events → 音频包内部 cue → WAV`

CSV 的 `id` 大量重复，不能用作逐句关联键。原始 ADV 来自 Campus-adv-txts 的 `Resource/adv_*.txt`。音频获取复用了用户 HatsuboshiWebsite 中的 Octo 请求/解密及 vgmstream 解包思路，重新实现了下载、校验、缓存和关联逻辑。`vendor/octodb.proto` 与生成的 Python 协议代码来自用户提供的 HatsuboshiToolkit；不是重新设计的协议。

## 运行

在项目根目录执行。Python 环境实际验证版本为 3.14；本地编译解码器需要 Git、CMake 和 C/C++ 编译器。

```bash
.venv/bin/pip install -r requirements-audio.txt
sh scripts/build_vgmstream.sh

.venv/bin/python -m campus_story_index.audio_download \
  --adv /path/to/Campus-adv-txts/Resource \
  --catalog generated/story-index.json \
  --config-repo /path/to/HatsuboshiToolkit \
  --config-ref resource \
  --refresh-manifest --workers 8

.venv/bin/python -m campus_story_index.audio_extract \
  --decoder tools/vgmstream-build/cli/vgmstream-cli --workers 6

.venv/bin/python -m campus_story_index.voice_index \
  --stories /path/to/Campus-Story \
  --adv /path/to/Campus-adv-txts/Resource
```

初次使用先按 README 生成剧情目录。更新 CSV/masterdata 后也需要先重建该目录，再刷新下载计划、解包并构建语音索引；构建器拒绝混用不同输入快照。可用 `--plan-only` 只生成下载计划；已有清单时可省略 `--refresh-manifest` 和配置参数。也可通过 `--config` 指定兼容的配置文件。

配置仅用于资源请求，不写入索引或日志。执行范围只有本地资源获取和处理，不执行原网站的上传步骤。同步源 Git 仓库需单独执行，生成器不会自行 pull。

解码器脚本固定 vgmstream 源码提交 `764c84c5048932054356f2ea67a71ea7673abc83`，本地编译 HCA 所需功能，不安装全局程序。命令参数可参考 [vgmstream 官方使用说明](https://github.com/vgmstream/vgmstream/blob/master/doc/USAGE.md)。当前构建关闭了多种外部编解码器；以后遇到其他音频编码应重新评估编译配置。

## 产物与路径

| 路径 | 内容 |
|---|---|
| `data/audio/OctoManifest.json` | 资源清单缓存 |
| `data/audio/download-plan.json` | 需要的资源、cue 和输入快照 |
| `data/audio/banks/` | 校验过的 ACB/AWB 原文件 |
| `data/audio/clips/<bank>/<stream_index>.wav` | 拆分音频，使用数字流序号避免重名覆盖 |
| `data/audio/bank-manifests/` | 每包的 cue、SHA-256、采样率、时长与完成记录 |
| `data/audio/audio-files.json` | 汇总音频目录 |
| `generated/voice-index/manifest.json` | 当前索引入口、统计、快照及分片路径 |
| `generated/voice-index/builds/<build_id>/scripts/` | 每个剧情一个 JSON 分片 |
| `generated/voice-index/builds/<build_id>/diagnostics.json` | 待核对项目 |

分片路径相对于 `generated/voice-index/`；`audio_path` 相对于 `data/audio/`；CSV 路径相对于 Campus-Story 根目录；ADV 路径相对于 Resource。前端通过 `script_id` 查找分片，后端为 `audio_path` 提供媒体 URL，不应在每次打开页面时加载全部索引。

索引按输入和代码哈希创建不可变构建目录，成功后原子切换 manifest。音频缓存路径仍按包名组织，未来更新同名资源时可能替换文件；部署时应让索引与音频目录作为同一批快照发布，不能把旧索引任意指向新缓存。

## 逐句与语音字段

完整分片契约见 [JSON Schema](voice-index.schema.json)，真实数据节选见 [示例](voice-example.json)。

- `lines`：CSV 原文、译文、说话人、记录序号和物理行号，以及对应 ADV 的位置、分支和时间信息。
- `voice_events`：脚本中的语音播放事件，保留原始引用、动画 actor、音轨、时序与参数。
- `lines[].voice_event_ids`：按时间与说话人证据推定的台词关联语音。
- `lines[].context_voice_event_ids`：同一文本时段内、说话人证据冲突的伴随语音，必须与台词朗读区分展示。
- `voice_events[].text_match`：匹配状态、方法、候选文本、说话人证据与时间差。
- `voice_events[].audio_variants`：内部 cue 精确验证的音频文件，或缺失/未解析状态；动态变体保留 `entry_ids`、`character_ids`。
- `source_texts_without_csv`、`embedded_timelines`、`diagnostics`：未覆盖文本、嵌入时间轴及诊断信息，避免静默丢弃。

`lines[].id` 由脚本、文本类型、说话人、原文摘要及重复出现序号组成。修改翻译不改变 ID；修改原文会改变 ID，在相同重复文本前插入另一条重复文本也可能改变后续序号。语音事件 ID 使用脚本内序号，只在当前脚本快照内稳定。翻译数据库迁移不能仅凭这些 ID 永久判断同一句话。

## 匹配规则与边界

1. 优先完整比对 CSV 与 ADV 的有序说话人/文本序列，重复句也按顺序对应。仅允许明确的旁白标记归一化。序列变化时只接受唯一的相同文本/说话人，歧义保留候选，不模糊猜测。
2. 解析递归分支和时间轴，语音不跨作用域匹配。候选文本时间窗口允许提前 150 ms、末尾 30 ms 容差，优先采用 250 ms 内唯一接近起点的事件，否则仅接受唯一兼容候选。
3. `actorId` 可能只是动画目标，优先采用 cue 中的角色线索；说话人冲突保留上下文关联，不写入主要台词关系。此步骤是时序推断，没有进行语音识别或人工逐条听辨。
4. 包名最长前缀只用于定位候选资源；最终必须核对内部 cue 名称，绝不以第一个流或文件排序补配。
5. `{voice_asset_id}`、`{voice_asset_id_01}`、`{voice_asset_id_02}` 分别由 masterdata 的 `voiceAssetId`、`voiceAssetId1`、`voiceAssetId2` 按入口上下文解析。同一脚本可有多种角色语音，网站应先选择剧情入口上下文，再展示适用变体。
6. 同时索引专用剧情音频、通用角色反应音及动态语音。选项没有自动语音关联；`no_explicit_voice` 只表示当前解析范围内没有直接关联，不表示游戏中一定无声。嵌入时间轴内容尚未展开。

## 下载与解包改进

- 按实际语音引用生成计划，包含通用反应音和动态变体。
- 下载流式写临时文件，大小和 MD5 通过后发布；有超时、有限重试和并发上限。重复执行复用完整且校验通过的文件，不支持单文件 HTTP 分段续传。
- 解包使用参数数组而非 shell 拼接；逐包暂存、校验音频头和解码器元数据、记录 SHA-256 后发布完成清单。
- 源文件成功或失败都保留；失败单独记录。再次执行校验缓存，可以重试失败包。
- 译文与原始脚本不改写；发布索引前校验输入未变化，保存源哈希用于追溯。
