# Sophon

Sophon 是一个动漫角色 RAG 初版。它先将萌娘 DB 的结构化 JSON 写入 PostgreSQL
事实层，再从角色资料生成可检索文档和向量，最后通过 LLM 服务回答角色问题。

pg内会创建catalog_* 的多个表，用于存放抓取到的结构化后的数据，实际rag调用的只有pg中的work和docs表，这两个表使用catalog各表构建，ask命令只会读work和docs这两个表。

## 数据边界

感谢 [**moegirl-dataset**](https://github.com/Zzzzzzyt/moegirl-dataset) 的数据支持，当前抓取功能使用该项目。

`data/` 是私有输入数据目录。运行前需要由部署者自行将数据放置为以下结构：

```text
data/
  moegirl/
    char_index.json
    char2attr.json
    char2cv.json
    char2gender.json
    char2subject.json
    extra_processed.json
    ...
  bangumi/
    moegirl2bgm.json
    bgm_info.json
    ...
```

Sophon 不负责抓取或公开分发这些数据。

## 前置条件

- Python 3.12
- PostgreSQL 与 `pgvector >= 0.7`
- Anthropic Messages 兼容的 LLM 接口，用于问题特征抽取和最终回答
- OpenAI Embeddings 兼容接口，用于生成与查询角色向量

LLM 与 Embedding 接口可以使用同一 CCSwitch 地址和密钥，但必须分别填写可用的模型名。

## 快速开始

1. 安装依赖并配置环境变量：

   ```bash
   uv sync
   cp .env.example .env
   ```
2. 编辑 `.env`，填写实际连接信息。`EMBEDDING_MODEL` 必须是 CCSwitch 已开通的
   embedding 模型，不能保留示例占位值：

   ```env
   DATABASE_URL=postgresql://user:password@host:5432/sophon

   LLM_API_KEY=your-ccswitch-key
   LLM_BASE_URL=https://your-ccswitch-host/v1
   LLM_MODEL=your-anthropic-compatible-model

   EMBEDDING_MODE=remote
   EMBEDDING_MODEL=your-embedding-model
   # 当 Embedding 服务与 LLM 不同地址或密钥时才需要填写：
   # EMBEDDING_BASE_URL=https://your-embedding-host/v1
   # EMBEDDING_API_KEY=your-embedding-key
   ```
3. 将私有数据放入 `data/moegirl/` 与 `data/bangumi/`，然后建立角色的
   catalog 和 RAG 索引：

   ```bash
   uv run sophon init-catalog-db
   uv run sophon init-rag-db
   ```
4. 执行数据导入，并重建RAG（1000条试操作）

   ```ba
   uv run sophon ingest-moegirl --limit 1000 --reset
   uv run sophon build-rag --reset
   ```
5. 提问或只查看候选角色：

```bash
   uv run sophon ask "银色头发、性格高冷的角色是谁？"
   uv run sophon retrieve "银色头发、性格高冷的角色"
```

`ask` 会依次显示特征抽取、向量检索和回答生成阶段，并且只允许模型依据召回资料作答。
`retrieve` 不调用 LLM，但会调用远程 Embedding 服务编码查询。

## 数据更新

首次导入完整数据：

```bash
uv run sophon ingest-moegirl --reset
```

私有数据更新后，只写入新增或变化的角色：

```bash
uv run sophon ingest-moegirl --changed-only
```

差异判断依据是 `source_records.payload_hash`。当前 RAG 初版为保持逻辑简单，会在
catalog 同步后完整重建 RAG 文档和向量：

```bash
uv run sophon build-rag --reset
```

可以由外部定时器在私有数据完成原子更新后调用：

```bash
bash scripts/sync_catalog.sh
```

脚本默认同步完整私有目录；原型期需要保持 1,000 条时，通过环境变量限制：

```bash
SOPHON_LIMIT=1000 bash scripts/sync_catalog.sh
```

它不会下载数据。生产定时任务应将数据下载/替换与该脚本分开，避免同步到半更新的数据目录。

## Embedding 模式

默认 `EMBEDDING_MODE=remote`，不会下载本地 BGE-M3 模型。远程响应只使用 dense 向量，
同时结合角色的性别、发色、瞳色、萌点和身份进行召回。

只有显式设置 `EMBEDDING_MODE=local` 时才会下载并启用本地 BGE-M3，以及 sparse 向量检索。
切换 embedding 模型或模式后，必须重新执行：

```bash
uv run sophon init-rag-db
uv run sophon build-rag --reset
```

## 命令

| 命令                                     | 作用                                     |
| ---------------------------------------- | ---------------------------------------- |
| `sophon init-catalog-db`               | 创建`source_*` 与 `catalog_*` 事实表 |
| `sophon ingest-moegirl`                | 将本地私有 JSON 写入 catalog             |
| `sophon ingest-moegirl --changed-only` | 仅同步新增或变化角色                     |
| `sophon init-rag-db`                   | 创建`docs`、`works` 向量检索表       |
| `sophon build-rag --reset`             | 从有效角色重建 RAG 文档和向量            |
| `sophon retrieve <query>`              | 检索角色候选，不调用 LLM                 |
| `sophon ask <query>`                   | 检索并生成带引用的角色回答               |

## 项目结构

| 路径                                | 作用                            |
| ----------------------------------- | ------------------------------- |
| `data/`                           | 私有输入数据，不提交、不打包    |
| `sql/001_catalog_schema.sql`      | 来源追溯与角色事实层            |
| `sql/002_rag_schema.sql`          | 角色 RAG 检索层                 |
| `src/sophon/importers/moegirl.py` | JSON 到目录模型的解析           |
| `src/sophon/loaders/moegirl.py`   | catalog 批量落库与差异同步      |
| `src/sophon/rag_projection.py`    | catalog 到 RAG 文档、向量的投影 |
| `scripts/sync_catalog.sh`         | 数据更新后的定时同步入口        |

## 题外话

使用cherry studio，在知识库中导入抓取到的json文件，就是“导入文档 -> 切块 -> 向量化 -> 检索问答”，而且数据是本地存储的；把 data 里的 JSON 先转成可读文本/Markdown，再导入知识库，一样可以实现一个静态的动漫知识问答。

当前项目是个二次元脸书的雏形项目，是一个可维护、可增量、可结构化检索，可定制检索的rag知识问答系统
