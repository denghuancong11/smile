# 模块协议

四个模块产生签名JSON回执，守卫只接受当前阶段绑定的真实回执。输入JSON建议放在状态目录，避免把运行证据写入目标仓库。

## 阶段1：项目上下文

仓库任务：

```text
python scripts/project_context.py build --root <project-root> --manifest <context.json> --receipt <context-receipt.json>
python scripts/workflow_guard.py attach-receipt --state <state.json> --token <TOKEN> --kind context --receipt <context-receipt.json>
```

纯概念任务：

```text
python scripts/project_context.py skip --reason "无本地项目，上下文只来自用户输入" --receipt <context-receipt.json>
```

`skip`不能用于规避已经明确存在的仓库。`build`是只读扫描；清单必须继续由权威文件和运行证据补充。

## 阶段4：证据协议

```text
python scripts/evidence_protocol.py --manifest @<evidence.json> --receipt <evidence-receipt.json>
python scripts/workflow_guard.py attach-receipt --state <state.json> --token <TOKEN> --kind evidence --receipt <evidence-receipt.json>
```

输入包含非空 `claims` 和 `evidence`。每项证据包含 `id`、`source_type`、`locator`、`observed_at`、`authority`、`summary`、`direction`。每个主张包含 `id`、`text`、`claim_type`、`support_ids`、`negative_ids`、`boundary`；时间敏感或比较性主张还需要 `search_scope`，且支持证据至少覆盖两种来源类型。负向证据可以是已发现反例，也可以是记录过范围的否定性检索。

## 阶段7：Story审计

```text
python scripts/story_audit.py --story @<story.json> --receipt <story-receipt.json>
python scripts/workflow_guard.py attach-receipt --state <state.json> --token <TOKEN> --kind story --receipt <story-receipt.json>
```

输入包含 `problem`、`importance_evidence`、`counterintuitive_entry`、`mechanism`、`solution_boundary`、`claims` 和 `problem_claim_mapping`。每个主张必须有 `id`、`text`、`method`、`evidence`、`negative_evidence`、`boundary`。出现“首次、最佳、绝对、永不、保证”等扩大性表述时，必须另有 `inflation_evidence`，否则失败。

## 阶段9：评测回归

```text
python scripts/evaluation_harness.py --suite @<suite.json> --baseline @<baseline.json> --candidate @<candidate.json> --receipt <evaluation-receipt.json>
python scripts/workflow_guard.py attach-receipt --state <state.json> --token <TOKEN> --kind evaluation --receipt <evaluation-receipt.json>
```

任务集必须覆盖 `normal`、`known_failure`、`holdout`、`perturbation` 四类。阈值由用户给出，至少包括 `min_success_rate`、`max_constraint_violations`、`min_recovery_rate`、`max_task_regressions`、`max_token_increase_ratio`。基线与候选必须对每个任务提供成功、约束、首次通过、修复轮次、重复工作、上下文命中/噪声、恢复、Token和耗时指标。

## 回执规则

- 模块返回码0表示通过；3表示完成审计但未通过；2表示输入或运行错误。
- 不得手工编辑回执。守卫校验模块名、允许状态、输入哈希和回执哈希。
- `context`允许 `pass` 或有原因的 `skip`；其余三类只允许 `pass`。
- 失败回执保留为诊断证据，修正输入后生成新回执，不覆盖审计历史。
