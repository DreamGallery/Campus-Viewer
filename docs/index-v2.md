# 索引 v2 数据契约

`schema_version=2.0.0`。公共字段统一 snake_case，数组顺序确定，相同输入快照重复构建产生相同字节。生成器不保存当前时间或绝对路径。上游内容变化会改变 sources 中的内容指纹。

## 字段调整

| 旧字段/结构 | 新位置 | 含义 |
|---|---|---|
| 各处重复的 advAssetId / assetId | entries.script_id → scripts.id | 统一脚本引用；卡图 assetId 不参与此映射 |
| csvPath | scripts.csv_path | 相对 Campus-Story 根目录的实际文件路径；不存在时 null |
| mainStories / eventStories / idolCardStories 等 | entries + memberships | 统一入口与关系，避免七套不兼容字段 |
| characterId / characterIds | character_ids | 统一数组，明确关联角色；不代表已经识别对白中的全部发言者 |
| viewConditionSetId | conditions.visible_if | 条件组 ID，并非计算后的布尔值 |
| unlockConditionSetId | conditions.unlocked_if | 解锁条件组 ID |
| forceUnlockConditionSetId | conditions.force_unlocked_if | 强制解锁条件组 ID |
| itemUnlockConditionSetId | conditions.item_unlocked_if | 道具解锁条件组 ID |
| previousStoryId | previous_entry_id | 带来源命名空间的入口 ID |
| produceEventHintProduceConditionDescriptions | hints | 保留日文条件说明 |
| dearnessLevel | context.dearness_level | 亲密度等级，不通过字符串拆分强转 |
| voiceAssetId / voiceAssetId1 / voiceAssetId2 | voice_bindings | 保留所有明确语音参数及其原字段名 |
| 原 type | source_type + category_id | 原始枚举与面向网站的分类分离 |

## entries：统一入口

每条入口都有同一组字段。`source_type`、`previous_entry_id` 等不存在时为 null；多值字段为空数组；conditions/context 为空对象。

- `id`：`源记录ID/脚本字段路径`。Story 和 ProduceStory 使用 `表名:原始id/advAssetId`。无单一 ID 的表使用明确复合键的 SHA-256 前 24 位，**不使用物理行号**。
- `script_id`：scripts.id。脚本内容或 CSV 行序变化不改变 asset ID；脚本版本通过 `source_text_sha256` 辨别。
- `title`、`title_language`、`title_source`：保留日文源标题；亲密度无标题时生成话数；无可用标题则显示 asset ID，绝不伪造正式标题。
- `category_id`：二级分类。一级取 categories.parent_id。
- `classification_basis`：`source_type`、`explicit_relation`、`shared_script`、`filename_hint` 或 `fallback`，用于区分来源与推断。
- `character_ids`：源表字段或明确关系得到的角色。
- `inferred_character_ids`：仅依据资源/源 ID 中完整角色代码分段推断；不并入明确角色列表。
- `idol_card_ids`、`support_card_ids`、`produce_mode_ids`：分别指向 groups 中对应 kind 的 **完整分组 ID**，例如 `IdolCard:i_card-amao-3-000`。
- `group_ids`：全部所属分组 ID，包括角色、剧情组、卡牌、培养模式和育成剧情家族。
- `order`：源 order 的整数形式，缺省为 0。分组内应优先使用 memberships.position，再用 order 和 id 作稳定次序。
- `conditions`、`hints`、`context`：显示/解锁条件、说明与运行上下文。
- `voice_bindings`：已知的参数映射，不是句子级音频对齐结果。
- `source_record_id`、`source_field`：回查原始行与字段。CSV-only 入口没有源记录，值为 null。

分组关系优先用于补充未知类别。脚本别名如果只有一个已知分类，则继承该分类。若共用资源同时存在“亲密度”和“培养阶段”入口，未知别名归亲密度，但已知入口各自的原分类保持不变。仍无明确信息时仅对有限、可解释的文件名前缀作带标记的分类建议，其余进入待分类。

当前没有从脚本正文抽取角色；卡片关联角色不等于每条对白的发言角色。

## scripts：资源去重与文本状态

- `id` / `asset_id`：当前两者相同，例如 `adv_dear_amao_001`；保留 asset_id 明确外部资源标识的含义。
- `entry_ids`：全部入口，包括角色变体和不同剧情 ID 的别名。
- `category_ids`、`character_ids`、`inferred_character_ids`：用于资源级筛选的汇总关系。
- `source_record_ids`：直接引用该脚本的源记录。间接分类关系见 memberships。
- `csv_path`：实际路径或 null；`.txt` 下载项先移除扩展名，与 CSV stem 精确匹配。
- `text_status`：`present`（有非空 text）、`empty`（有 CSV 但无非空 text）、`missing`（无 CSV）。present 不保证提取完整。
- `metadata_status`：`referenced` 或 `unlinked_masterdata`。unlinked_masterdata 表示“未关联 masterdata”；这些脚本不会丢弃，也不会自动认定已废弃。
- `file_sha256`：整个 CSV 文件的字节哈希。
- `source_text_sha256`：按 CSV 顺序对非空 text 行的 `[id,name,text]` 规范化后计算。改 trans 不影响它；它不覆盖 ADV 控制指令、音频或其他非文本元数据。
- `text_row_count`、`translated_row_count`：非空原文行数、其中 trans 非空的行数；并非审核状态。

协作系统未来应将翻译、认领和审核记录存入独立持久层。本生成器只读取已有 trans 的数量，不修改翻译，不生成可编辑句子 ID。

## groups / memberships

groups.kind 包括 `character`、`main_part`、`main_chapter`、`story_group`、`event`、`idol_card`、`support_card`、`produce_mode`、`produce_story_family`。

- `parent_id` 定义展示层级；`parent_basis` 说明为直接关系或由主线剧情集合推断。其他多重归属由 memberships 表达。
- `metadata` 保留适用于该类组的规范化信息，如 rarity、is_limited、description、available_from、source_type 和亲密度等级范围。枚举值仍为上游原值。
- memberships 包含 `entry_id`、`group_id`、`position`、`source_record_id`、`source_field`。源列表下标从 0 开始；亲密度范围关系的 position 使用等级；无源顺序时为 null。
- `ProduceStoryGroup` 源记录采用 `(id,characterId)`，展示 family 只按原 id 合并；每个角色关系仍单独保存。

主线活动分组可同时在主线章节和活动实体关系中出现，entries 的分类依据剧情类型，不会仅因来源表名叫 StoryEvent 就归为活动剧情。

## 来源与完整性

source_records 保留被使用的原始行。condition_sets 按 ID 保存**行数组**，不把有多个子条件的组覆盖成单行；本阶段不求值。sources 同时保存 Git 提交、所有读取文件的 SHA-256，以及文件哈希映射的整体指纹，能识别未提交数据变化。

资源底册扫描 masterdata 中全部 `adv_` 字面引用，排除 PhotoBackground，规范化 AssetDownload 的 `.txt`。这不能覆盖客户端动态拼接或未提取的资源；CSV 反查用于补充当前能观察到的文件。新来源表会保留为后备入口并诊断；strict 模式要求补充适配器。

已知表的主键稳定；未来无明确键的表采用内容哈希后备键，并报 `unstable_source_key`。未来上游表的主键结构变化需要迁移，不能承诺任意上游修改都保持同一个入口 ID。


## 网页目录去重与培养事件分支

索引保留所有原始入口及来源，网页角色目录按 script_id 选择一个入口。亲密度入口优先，STEP 分组优先于无分组入口；其他同脚本入口优先保留有明确培养模式的记录。章节仍保存全部来源。角色卡、亲密度 STEP、培养主剧情维持原分组；其他角色剧情按类别合并。

外出、营业和校园事件通过 ProduceStepEventDetail 的选项列表及 ProduceStepEventSuggestion 的 stepId/successStepId/failStepId 连接到后续事件，继承明确父事件的培养模式；不依据文件名后缀猜测关联。多模式引用全部保留，循环跳转不会无限遍历。


多人共用的培养脚本归入 `other.training_shared`：同一 script_id 的培养入口有两个或以上明确关联角色即可，不要求覆盖完整偶像名单，也不按标题相同判定。角色卡与亲密度不应用此规则。原分类写入 `context.original_category_id`，适用角色集合写入 `context.shared_character_ids`，原始来源和角色关联保留。其他剧情目录也按脚本去重；有明确培养模式的共通主剧情保留模式分组，共用校园脚本合并为“培养校园剧情”。

H.I.F 的角色开场说明（`ProduceSplitAdv`、`ProduceType_HatsuboshiIdolFestival`、`ProduceAdvType_Opening` 且有目标角色）归入培养主剧情，保留 H.I.F 模式分组，包括选拔试验和本战说明。未指定角色的共通开场仍归培养共通剧情。
