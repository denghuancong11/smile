---
name: engineer-agent-workflows
description: 以十阶段严格交互式状态机诊断、发现、决策、验证并持续改进Agent工作流，覆盖系统提示与垂类Skill、项目上下文和插件/本地工具链、大型工程任务拆分、编码—报错—修复循环、状态保持、中断恢复和Token效率。用于设计或评审Agent工作流、处理断片或跑偏、选择上下文工具、拆解大型任务、减少返工和Token、建立持久经验记忆、证据闭环、Story审计与自动回归。必须依次执行对齐、回忆、探索、质疑、人工决策、验证、复盘、沉淀、回归、循环；当前阶段未通过机器门禁和签名模块回执时不得进入下一阶段。
---

# Agent工作流工程

## 强制流程

严格执行：

> 对齐 → 回忆 → 探索 → 质疑 → 人工决策 → 验证 → 复盘 → 沉淀 → 回归 → 循环

开始任何任务前，完整读取 [methodology-map.md](references/methodology-map.md)、[stage-gates.md](references/stage-gates.md) 和 [module-protocols.md](references/module-protocols.md)。在阶段8或10读取 [experience-memory.md](references/experience-memory.md)。

使用 `scripts/workflow_guard.py` 保存状态并执行门禁。状态JSON带完整性校验；不得手工编辑。阶段2的历史检索、阶段8的经验写入和阶段10的循环检索必须由脚本完成，不接受手填结果。

## 每个回复的固定协议

1. 读取状态；新任务以新状态文件初始化，并显式传入跨任务稳定的经验库路径。状态可放在目标仓库之外的临时目录；经验库不得使用会被系统清理的临时路径，也不得默认写入目标仓库。
2. 调用 `open-turn`，整个回复只使用返回的同一token。
3. 只处理当前阶段，只记录用户明确提供或工具验证过的内容。
4. 调用 `check`；门禁未通过时停留当前阶段，只问一个最能补齐缺口的问题。
5. 门禁通过后调用 `advance`；每个回复最多推进一个阶段。
6. 推进后不得在同一回复处理新阶段的字段或产物。
7. 当前阶段要求模块回执时，先运行模块，再用 `attach-receipt` 附加签名回执；回执失败、缺失、错阶段或被篡改时不得推进。
8. 调用 `close-turn`，再输出阶段卡片。

脚本失败、状态缺失、经验库损坏或状态与外部事实冲突时，停止推进并先恢复。不得凭记忆绕过守卫。

## 不可绕过的规则

- 用户要求跳步、直接给方案或提前宣布成功时，仍不得跨过门禁。
- 阶段2前不得声称已经吸取历史经验；阶段3前不得生成候选方向；阶段4前不得筛掉候选；阶段5取得明确人工选择前不得实验或实施。
- 阶段6前冻结验收和停止条件；实验后不得修改标准迁就结果。
- 阶段7必须区分对齐、假设、执行和数据错误，不能用“模型不够聪明”代替分类。
- 阶段8必须产生可检索的持久经验记录；阶段9必须把关键错误变成机器可执行检查；阶段10必须用一个下一任务查询实际找回记录。
- AI负责检索、提出候选、找反例、执行实验、分类和实现检查；人负责选择目标、方案和风险边界。AI不得伪造 `user_explicit` 决策。
- 不得承诺永不跑偏或跨任务通用有效。结论只覆盖验证过的任务、环境和扰动。

## 状态守卫

使用可用的Python运行时执行：

```text
python scripts/workflow_guard.py init --state <state.json> --memory <memory.jsonl> --objective "<目标>"
python scripts/workflow_guard.py status --state <state.json>
python scripts/workflow_guard.py open-turn --state <state.json>
python scripts/workflow_guard.py put --state <state.json> --token <TOKEN> --stage <N> --field <字段> --value '<JSON值或文本>'
python scripts/workflow_guard.py memory-search --state <state.json> --token <TOKEN> --queries '["关键词1","关键词2"]' [--task-type <类型>] [--error-class <分类>] [--environment <环境>]
python scripts/workflow_guard.py attach-receipt --state <state.json> --token <TOKEN> --kind <context|evidence|story|evaluation> --receipt <receipt.json>
python scripts/workflow_guard.py deposit --state <state.json> --token <TOKEN> --record '@<record.json>'
python scripts/workflow_guard.py check --state <state.json> --token <TOKEN>
python scripts/workflow_guard.py advance --state <state.json> --token <TOKEN>
python scripts/workflow_guard.py close-turn --state <state.json> --token <TOKEN>
```

回退时使用 `rollback --to <N>`；回退会清除目标阶段之后的状态，但不会删除已经写入的经验记录。若沉淀内容被后续证据推翻，新增一条纠正记录，不得静默改写历史。

schema 1、2状态不能直接续跑；重新开始时创建schema 3状态。状态和模块回执都带完整性哈希，禁止手工补字段。

## 十阶段职责

### 1. 对齐

确认表面需求、底层目的、约束、环境、授权和可验收完成定义。底层目的和验收只描述结果，不得夹带插件、提示、状态文件、脚本或自动检查等实现手段。若任何字段由AI推断或改写，先展示对齐卡并等待用户确认；只有用户明确确认后才能写入 `alignment_confirmation=user_explicit`。对仓库任务运行项目上下文扫描；对纯概念任务生成带原因的跳过回执；用 `attach-receipt --kind context` 附加。只输出目标契约，不给方案。

### 2. 回忆

先调用 `memory-search` 检索相似错误和已有决策；没有命中也必须记录查询、来源和扫描结果。判断历史记录是否适用于当前任务，不得机械套用。

### 3. 探索

至少使用三种不同发现算子，提出至少三个可能被忽略的问题。优先使用反转默认假设、极端条件、基线扰动、角色/任务重构、跨领域类比、资源约束反转和时间演化。

### 4. 质疑

主动寻找反例、冲突和否定证据。为关键主张建立证据清单，当前能力、市场空白、最佳插件、SOTA或新颖性主张必须记录检索范围并使用至少两种来源类型。运行证据协议并用 `attach-receipt --kind evidence` 附加通过回执。淘汰或缩小不成立的候选，保留至少一个仍值得决策的方向，并写明不确定性。

### 5. 决策

让用户明确选择目标、方案和风险边界，同时记录被放弃选项与理由。没有 `user_explicit + proceed` 不得进入验证。用户要修改时回退阶段3或4；用户停止时导出部分状态。

### 6. 验证

冻结成功、失败和停止标准，执行最小实验或MVP，记录对照、观察结果和证据。不要先完善再验证核心机制。

### 7. 复盘

把结果分别归类为对齐、假设、执行和数据错误；任何类别没有发现问题时也要写明检查依据。把问题、重要性、反直觉切入点、机制、方法、正反证据和结论边界组成可审计Story，运行Story审计并用 `attach-receipt --kind story` 附加通过回执。形成因果解释、经验和下一行动。

### 8. 沉淀

读取经验记录格式，调用 `deposit` 写入任务特征、决策、结果、四类错误、经验、适用边界、检索词、证据和回归检查。只有写后校验成功才能推进。

### 9. 回归

把关键错误变成至少一个机器可执行检查或结构化门禁，建立包含常规、已知失败、保留和扰动任务的评测集，比较基线与候选。阈值必须来自用户。运行评测工具并用 `attach-receipt --kind evaluation` 附加通过回执。未通过时修复或回退，不得把手工提醒冒充自动检查。

### 10. 循环

构造下一次相似任务的检索词，再次调用 `memory-search`。必须实际命中阶段8记录，并说明它如何影响下一次对齐以及以后“先对齐、再检索”的固定入口规则。

## 模块路由

- 提示、AGENTS.md、Skill和状态协议：阶段5、8或9读取 [skill-prompt-protocol.md](references/skill-prompt-protocol.md)。
- 插件、知识库和上下文路由：阶段2、3或5读取 [context-routing.md](references/context-routing.md)。
- 大型任务拆分和编码循环：阶段1、6或9读取 [task-execution-loop.md](references/task-execution-loop.md)。
- 断片、漂移和修复震荡：阶段2、4或7读取 [failure-taxonomy.md](references/failure-taxonomy.md)。
- 实验、指标和回归：阶段4、6、7或9读取 [evaluation-suite.md](references/evaluation-suite.md)。
- 各模块的输入、输出、运行位置和回执绑定：读取 [module-protocols.md](references/module-protocols.md)。

## 每轮输出

```text
阶段 N/10：<名称>
门禁状态：未通过 / 本轮刚通过 / 全流程完成
已确认：<证据支持的内容>
历史命中：<仅阶段2或10填写；其他阶段写不适用>
待验证：<假设或未知项>
缺失门禁：<字段；通过则写无>
本轮未做：<被门禁禁止的后续动作>
下一问题：<至多一个>
状态文件：<路径>
经验库：<路径>
```

只有schema 3状态标记为 `complete`，且四类签名模块回执均通过后，才能交付完整闭环：对齐结果、项目上下文、历史经验、探索候选、否定证据、人工决策、验证结果、Story闭环、四类复盘、经验记录ID、自动回归和循环检索证据。
