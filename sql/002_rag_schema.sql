-- 动漫角色识别 RAG — 数据库 schema
-- 需要 pgvector >= 0.7 (sparsevec 支持)

create extension if not exists vector;

-- 作品
create table if not exists works (
    id      text primary key,
    title   text not null,
    aliases text[] default '{}',
    type    text,                       -- anime / manga / game / novel
    meta    jsonb default '{}'
);

-- 检索文档: 当前原型只写入由 catalog 派生的角色卡。
create table if not exists docs (
    id         bigserial primary key,
    source_key text,
    doc_type   text not null,           -- 当前固定为 'character'
    work_id    text references works(id) on delete cascade,
    name       text,
    aliases    text[] default '{}',
    -- 可过滤结构化标签
    gender     text,
    hair_color text[] default '{}',
    eye_color  text[] default '{}',
    traits     text[] default '{}',     -- 傲娇 / 高冷 / 腹黑 ...
    roles      text[] default '{}',     -- 学生 / 剑士 / 妹妹 ...
    content    text not null,           -- 富文本块 (embedding + 展示)
    source_url text,
    meta       jsonb default '{}',
    embedding  vector,                  -- 远程服务模型维度由响应决定
    sparse     sparsevec(250002)        -- 仅 EMBEDDING_MODE=local 时写入
);

alter table if exists docs add column if not exists source_key text;
drop index if exists docs_embedding_idx;
alter table if exists docs alter column embedding type vector using embedding::vector;

create index if not exists docs_sparse_idx     on docs using hnsw (sparse sparsevec_ip_ops);
create index if not exists docs_traits_idx     on docs using gin (traits);
create index if not exists docs_hair_idx       on docs using gin (hair_color);
create index if not exists docs_type_idx       on docs (doc_type);
create unique index if not exists docs_source_key_idx on docs (source_key) where source_key is not null;
