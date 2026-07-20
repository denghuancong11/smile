# 十阶段门禁字段

所有字段只能来自用户明确输入、工具输出或脚本生成结果。数组和对象必须以JSON写入。

| 阶段 | 必填字段 | 特殊约束 |
|---|---|---|
| 1 对齐 | `surface_request`, `underlying_goal`, `constraints`, `acceptance_criteria`, `environment`, `authorization_boundary`, `alignment_confirmation`, `context_receipt` | 约束与验收为数组；环境含runtime/task_context；授权含allowed/requires_confirmation/forbidden；不得含占位内容；底层目的和验收不得夹带插件、状态文件、提示、脚本或自动检查等解法；AI推断过任何字段时必须等待用户明确确认；`context_receipt`只能由签名项目上下文模块写入 |
| 2 回忆 | `recall_executed`, `recall_queries`, `recall_sources`, `similar_failures`, `prior_decisions`, `recall_result`, `recall_evidence`, `applicability_assessment` | 前七项只能由 `memory-search` 写入 |
| 3 探索 | `discovery_operators`, `operator_outputs`, `overlooked_problem_candidates`, `candidate_evidence_status` | 至少3个不同算子、3个候选 |
| 4 质疑 | `counterexamples`, `conflicts`, `negative_evidence`, `disconfirmed_candidates`, `surviving_candidates`, `remaining_uncertainty`, `evidence_receipt` | 反例、冲突、否定证据和幸存候选各至少1项；`evidence_receipt`只能由通过的签名证据协议写入 |
| 5 决策 | `selected_target`, `selected_solution`, `risk_boundary`, `rejected_options`, `decision_reason`, `decision_source`, `decision_status` | 只能接受用户明确给出的 `user_explicit` 与 `proceed` |
| 6 验证 | `core_hypothesis`, `minimal_experiment_or_mvp`, `control`, `criteria_locked`, `success_criterion`, `failure_criterion`, `stop_condition`, `observed_result`, `evidence_refs` | `criteria_locked`必须为布尔值true |
| 7 复盘 | `error_classification`, `causal_explanation`, `lessons`, `next_action`, `story_receipt` | 分类对象必须含alignment、assumption、execution、data；`story_receipt`只能由通过的签名Story审计写入 |
| 8 沉淀 | `experience_record_id`, `experience_record`, `decision_record`, `applicability_boundary`, `retrieval_keys`, `storage_location`, `write_verification` | 全部只能由 `deposit` 写入 |
| 9 回归 | `key_error`, `automated_checks`, `failure_fixture`, `check_locations`, `check_passed`, `check_evidence`, `coverage_boundary`, `evaluation_receipt` | 至少1项检查且实际运行通过；`evaluation_receipt`只能由通过的签名评测工具写入 |
| 10 循环 | `next_task_query`, `retrieved_record_ids`, `retrieval_result`, `retrieval_first_verified`, `influence_on_next_alignment`, `loop_entry_rule`, `final_status` | 前四项由 `memory-search` 写入，且必须命中 |

## 发现算子

阶段3从下列算子中选择至少三种，避免只是生成三个措辞不同的方案：

- 反转默认假设；
- 极端或边界条件；
- 强基线扰动与噪声；
- 用户任务/角色重新定义；
- 跨领域机制类比；
- 时间演化与中断恢复；
- 资源、权限或Token约束反转；
- 从失败证据反推缺失能力。

每个候选使用：`默认假设 → 观察或扰动 → 被忽略的问题 → 可证伪预测`。

## 人工决策

阶段5必须向用户展示幸存候选的支持证据、反对证据、未知项和风险边界。用户明确选择后才能写入：

```json
{
  "decision_source": "user_explicit",
  "decision_status": "proceed"
}
```

用户要求修改时回退阶段3或4；用户放弃时停止并导出部分结果，不伪造完成状态。

## 模块回执

`context_receipt`、`evidence_receipt`、`story_receipt`、`evaluation_receipt`是系统字段，不能通过 `put` 写入。必须运行对应模块，再调用 `attach-receipt`。守卫验证模块名、阶段、允许状态、输入哈希和回执哈希；失败、跳错阶段或任何字段被修改都会拒绝推进。
