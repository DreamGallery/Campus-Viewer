# 学园偶像大师剧情索引器 v2

离线读取 `gakumasu-diff` 和 `Campus-Story/CSV`，生成统一的剧情目录。五个一级分类为：**主线、角色、辅助卡、活动、其他**。

实现位于仓库根目录 `campus_story_index/`；下列命令均在仓库根目录运行。

## 使用

要求 Python 3.10+，依赖只有 PyYAML。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m campus_story_index \
  --masterdata /path/to/gakumasu-diff \
  --stories /path/to/Campus-Story \
  --output generated/story-index.json \
  --strict
```

输入路径通过参数指定，不在生成器中硬编码。CSV 路径相对于 Campus-Story 根目录；输出不包含本机绝对路径。生成期间不联网、不执行 git pull、不写入输入目录。

生成前后校验输入文件哈希与 Git 版本，完整性校验通过后原子替换 JSON。输入变化、重复源主键、CSV 同名冲突、无效引用或输出失败均不会覆盖上一份成功产物。

`--strict` 额外阻止悬空剧情关系、缺失分组、未适配的脚本来源表和不稳定的后备主键。已知的缺失 CSV、CSV-only 资源和待分类条目会保留并记录在 diagnostics，允许构建成功。

## 分类

| 一级 | 二级 |
|---|---|
| 主线剧情 | 主线；保留部、章、剧情组层级 |
| 角色剧情 | 亲密度、角色卡、培养主剧情、成长、外出、校园、营业、阶段、行动过场、公开课程、周次、生日、Live、角色其他剧情 |
| 辅助卡剧情 | 辅助卡剧情；按卡片和关联角色筛选 |
| 活动剧情 | 剧情活动、巡演、公会战、愚人节、高分活动、限时企划 |
| 其他剧情 | 教程、培养共通剧情、高塔、招募演出、待分类 |

分类 ID 为稳定的英文机器值，中文名称在 `taxonomy.py` 中配置。角色身份、卡牌、培养模式和活动分组作为关系字段，避免形成多份互相不一致的树。某些分类当前没有条目，保留作稳定接口。

主线活动的分组如果是唯一一个主线章节的剧情 ID 子集，会归入该章，标注 `parent_basis=story_id_subset`；原活动入口仍通过 memberships 保留，不根据名称猜章节。

## 统一数据结构

- **entries**：剧情入口。一条源记录的一个脚本字段对应一个入口；保存标题、分类、条件和上下文。
- **scripts**：脚本资源，按 asset ID 去重。CSV 路径、提取状态、原文哈希属于这一层，可供以后共用翻译。
- **groups / memberships**：章节、卡牌、活动、培养模式等分组及有序关系。同一入口可以属于多个组。
- **characters**：角色/说话人资料，包含不可培养角色，以及只出现在 CharacterAdv 的对象。
- **source_records / condition_sets / sources**：源记录、未求值的条件组、输入快照信息，便于排查与增量更新。
- **categories / stats / diagnostics**：分类定义与统计、完整性诊断。

所有公开标准字段统一使用 `snake_case`，只有 `source_records.data`、`condition_sets` 保留原始 masterdata 名称，避免转换时丢失含义。字段细节见 [结构说明](index-v2.md)，机器契约见 [JSON Schema](story-index.schema.json)。

这是服务端完整目录，含来源与运行时变体，当前格式化 JSON 约 33 MB。网页应由后端按分类/角色/卡牌筛选和分页，不应在首页一次下载完整文件。`script_count` 是资源数，`entry_count` 是含上下文变体的入口数；不能把后者当作独立剧情数量。

## 测试

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```

测试覆盖去重、多角色复合键、遗漏源条目、主线层级、CSV 状态、文件名冲突、稳定 ID、条件保留、语音参数、翻译修改与原文哈希隔离、未知来源、输入变化和原子写入失败保护。


## 剧情语音与 CSV 对应索引

已增加独立的资源下载、音频解包和逐句关联流程，沿用上述剧情目录的 `script_id`。从原始 ADV 脚本读取文本、分支、时间轴和语音引用，再核对音频包内部 cue 名称；不依赖 CSV 中重复的 `id` 或音频文件排序。

当前产物入口为 `generated/voice-index/manifest.json`，按剧情加载分片；音频位于 `data/audio/clips/`。台词关联语音与时间段内的伴随语音分开保存，未能确定的对应关系保留诊断。

安装额外依赖 `requirements-audio.txt` 后，按 [语音索引使用说明](voice-index.md) 运行。字段约束见 [分片 JSON Schema](voice-index.schema.json)。大体积音频、下载缓存、编译工具和生成索引均已加入 `.gitignore`。

## 网页接入

`campus_story_index.web_assets` 按需下载、解包网页图片，`campus_story_index.web_export` 将完整索引转换成按分类/角色加载的网页分片。网页和更新器在同一仓库，部署见 [Docker 说明](../deploy/README.md)。
