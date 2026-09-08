# Agent V2 Memory 架构

本文档介绍新增的 `agent_v2/` memory 架构。它是独立新版本，不修改现有 `zhihuishu_exam_automation.py` 和 `zhihuishu_video_downloader.py` 的运行逻辑。

## 设计目标

- 记住历史题目、选项、答案、证据和人工反馈。
- 再次遇到同题或高度相似题时，提高答案稳定性和准确率。
- 默认只保存文本证据，不保存账号密码、截图、完整 prompt 或完整 reasoning。
- 使用 Python 标准库 `sqlite3`，不引入向量库或额外服务。

## 模块结构

```text
agent_v2/
├── __init__.py
├── main.py              # V2 memory 层 smoke demo
├── memory_cli.py        # memory 查询、统计、反馈 CLI
├── models.py            # dataclass 数据模型
├── normalizer.py        # 题干/选项归一化与相似度
├── pipeline.py          # 后续接入答题流程的 memory 门面
├── policy.py            # reuse / reference / ignore 决策策略
└── storage.py           # SQLite schema 与读写逻辑
```

## 核心流程

1. OCR 和页面解析拿到题型、题干、选项。
2. `QuestionNormalizer` 清洗题干和选项，生成稳定指纹。
3. `MemoryManager.search_question()` 先查精确指纹，再查同课程同题型下的相似题。
4. `MemoryPolicy` 做三类决策：
   - `reuse`：高相似且高可信，直接复用历史答案。
   - `reference`：相似但不够直接复用，作为历史参考注入 prompt。
   - `ignore`：低相似或无命中，不使用 memory。
5. 作答完成后，`MemoryManager.upsert_question_memory()` 保存题目、答案和证据摘要。
6. 用户可通过 CLI 反馈正确答案，确认后的题目可信度提升到可直接复用。

## SQLite 数据

默认数据库路径：

```bash
./memory/zhihuishu_memory.sqlite3
```

主要表：

- `courses`：课程名称。
- `exams`：考试名称、URL hash、截止时间文本。
- `question_memories`：题干、选项、答案、可信度、验证状态。
- `answer_attempts`：每次作答记录。
- `evidence_sources`：RAG 或人工证据摘要。
- `user_feedback`：人工确认、纠错或备注。

## 配置项

可在 `.env` 中加入：

```bash
MEMORY_ENABLED=true
MEMORY_DB_PATH=./memory/zhihuishu_memory.sqlite3
MEMORY_REUSE_THRESHOLD=0.92
MEMORY_REFERENCE_THRESHOLD=0.70
MEMORY_SAVE_TEXT_EVIDENCE=true
MEMORY_SAVE_RAW_PROMPT=false
MEMORY_SAVE_REASONING=false
```

当前实现默认不保存完整 prompt、完整 reasoning 和截图。`MEMORY_SAVE_*` 预留给后续接入层使用。

## CLI 用法

查看统计：

```bash
python -m agent_v2.memory_cli stats
```

搜索历史题：

```bash
python -m agent_v2.memory_cli search "马克思主义中国化"
```

记录人工反馈：

```bash
python -m agent_v2.memory_cli feedback --id 1 --type confirmed --answer '[2]' --note "人工确认"
```

运行 memory 层 smoke demo：

```bash
python -m agent_v2.main
```

## 后续接入建议

后续如果要把 V2 memory 接入真实浏览器作答流程，建议在单题处理函数中加入两个接入点：

- 模型调用前：调用 `MemoryAwareAnswerPipeline.prepare()`，根据 decision 决定直接复用、注入历史参考或走原流程。
- 点击/填空后：调用 `MemoryAwareAnswerPipeline.commit()`，保存题目、答案、RAG 分数和证据摘要。

这样 memory 逻辑会集中在 `agent_v2/`，不会污染 Playwright 页面操作代码。
