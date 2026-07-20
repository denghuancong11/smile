# 经验库协议

## 记录格式

阶段8向 `deposit` 提交一个JSON对象：

```json
{
  "task_signature": "可用于识别相似任务的稳定描述",
  "surface_request": "用户原始表面需求",
  "underlying_goal": "底层目的",
  "decision": {"target": "...", "solution": "...", "risk_boundary": "..."},
  "outcome": "验证结果及结论边界",
  "error_classes": {
    "alignment": "检查结果",
    "assumption": "检查结果",
    "execution": "检查结果",
    "data": "检查结果"
  },
  "lessons": ["可复用经验"],
  "applicability_boundary": "适用与不适用条件",
  "retrieval_keys": ["稳定关键词", "错误类型", "任务类型"],
  "evidence_refs": ["测试、日志或文件引用"],
  "regression_checks": ["检查名称或位置"]
}
```

脚本为记录生成ID、时间和哈希，以JSONL写入经验库并重新读取验证。不要存储隐藏思维过程、密钥或大段原始日志；保存结论、证据定位和边界。

经验库使用schema 2、追加写入和逐条完整性哈希。路径必须显式指定为跨任务稳定位置，不能依赖操作系统临时目录。目标项目只是经验的研究对象，不是经验库的默认存放位置。

## 检索规则

- 阶段2使用当前任务类型、关键约束和可观察失效构造检索词；可用 `task_type`、`error_class` 和 `environment` 做结构化过滤。
- 命中记录后只作为证据候选，必须填写 `applicability_assessment`。
- 没有命中时保留扫描数量和查询词，继续探索，不虚构历史经验。
- 阶段10使用下一次相似任务可能出现的自然关键词检索；没有命中则不能完成循环。
- 重复的有效记录会被拒绝。记录被新证据推翻或扩展时，追加 `correction` 或 `extension` 记录并用 `supersedes` 指向旧记录；检索只返回当前有效记录，旧记录仍保留审计轨迹。

可独立执行 `memory_store.py verify --store <memory.jsonl>` 检查全库哈希、schema、总记录数和有效记录数。任何一行损坏时停止检索与推进，不静默跳过。
