-- 第一阶段: 来源可追溯的动漫角色结构化数据目录。
-- 这些表是 RAG docs 的上游事实层；向量与检索文档在后续阶段从此处派生。

create table if not exists source_registry (
    source_code text primary key,
    display_name text not null,
    homepage text,
    metadata jsonb not null default '{}',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 一条记录对应一个外部对象的原始、可重放载荷，不对其做语义删减。
create table if not exists source_records (
    id bigserial primary key,
    source_code text not null references source_registry(source_code) on delete cascade,
    record_kind text not null,
    external_key text not null,
    source_url text,
    payload jsonb not null,
    payload_hash text not null,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    unique (source_code, record_kind, external_key)
);
create index if not exists source_records_kind_idx on source_records (source_code, record_kind);

create table if not exists catalog_works (
    id bigserial primary key,
    source_code text not null references source_registry(source_code),
    source_key text not null,
    title text not null,
    source_record_id bigint references source_records(id) on delete set null,
    metadata jsonb not null default '{}',
    unique (source_code, source_key)
);
create index if not exists catalog_works_title_idx on catalog_works (title);

create table if not exists catalog_characters (
    id bigserial primary key,
    source_code text not null references source_registry(source_code),
    source_key text not null,
    display_name text not null,
    gender text,
    is_active boolean not null default true,
    source_record_id bigint references source_records(id) on delete set null,
    source_url text,
    metadata jsonb not null default '{}',
    unique (source_code, source_key)
);
create index if not exists catalog_characters_name_idx on catalog_characters (display_name);
alter table if exists catalog_characters
    add column if not exists is_active boolean not null default true;
create index if not exists catalog_characters_source_active_idx
    on catalog_characters (source_code, is_active);

create table if not exists catalog_character_names (
    character_id bigint not null references catalog_characters(id) on delete cascade,
    name text not null,
    name_kind text not null,
    primary key (character_id, name)
);
create index if not exists catalog_character_names_name_idx on catalog_character_names (name);

create table if not exists catalog_character_profiles (
    character_id bigint primary key references catalog_characters(id) on delete cascade,
    birth_year integer,
    birth_month smallint check (birth_month between 1 and 12),
    birth_day smallint check (birth_day between 1 and 31),
    zodiac text,
    blood_type text,
    age_text text,
    height_text text,
    weight_text text,
    metadata jsonb not null default '{}'
);

create table if not exists catalog_character_images (
    character_id bigint not null references catalog_characters(id) on delete cascade,
    position smallint not null,
    image_ref text not null,
    alt_text text,
    primary key (character_id, position)
);

create table if not exists catalog_attributes (
    id bigserial primary key,
    source_code text not null references source_registry(source_code),
    source_key text not null,
    name text not null,
    source_url text,
    metadata jsonb not null default '{}',
    unique (source_code, source_key)
);
create index if not exists catalog_attributes_name_idx on catalog_attributes (name);

-- 一个属性可以同时属于多个分类，例如基础属性与发色属性。
create table if not exists catalog_attribute_types (
    attribute_id bigint not null references catalog_attributes(id) on delete cascade,
    attribute_type text not null,
    primary key (attribute_id, attribute_type)
);

create table if not exists catalog_character_attributes (
    character_id bigint not null references catalog_characters(id) on delete cascade,
    attribute_id bigint not null references catalog_attributes(id) on delete cascade,
    evidence_source text not null,
    primary key (character_id, attribute_id, evidence_source)
);
create index if not exists catalog_character_attributes_attribute_idx
    on catalog_character_attributes (attribute_id);

-- subject 保留作品、地区和页面分类等所有原始主题；不能预先把它们都当成作品。
create table if not exists catalog_subjects (
    id bigserial primary key,
    source_code text not null references source_registry(source_code),
    source_key text not null,
    title text not null,
    metadata jsonb not null default '{}',
    unique (source_code, source_key)
);
create index if not exists catalog_subjects_title_idx on catalog_subjects (title);

create table if not exists catalog_character_subjects (
    character_id bigint not null references catalog_characters(id) on delete cascade,
    subject_id bigint not null references catalog_subjects(id) on delete cascade,
    primary key (character_id, subject_id)
);
create index if not exists catalog_character_subjects_subject_idx
    on catalog_character_subjects (subject_id);

-- 仅 subject_index 中出现的主题可作为作品目录项，角色可属于多部作品。
create table if not exists catalog_character_works (
    character_id bigint not null references catalog_characters(id) on delete cascade,
    work_id bigint not null references catalog_works(id) on delete cascade,
    membership_source text not null,
    primary key (character_id, work_id, membership_source)
);
create index if not exists catalog_character_works_work_idx on catalog_character_works (work_id);

create table if not exists catalog_people (
    id bigserial primary key,
    source_code text not null references source_registry(source_code),
    source_key text not null,
    display_name text not null,
    metadata jsonb not null default '{}',
    unique (source_code, source_key)
);
create index if not exists catalog_people_name_idx on catalog_people (display_name);

create table if not exists catalog_character_voice_credits (
    character_id bigint not null references catalog_characters(id) on delete cascade,
    person_id bigint not null references catalog_people(id) on delete cascade,
    credit_source text not null,
    primary key (character_id, person_id, credit_source)
);
create index if not exists catalog_character_voice_credits_person_idx
    on catalog_character_voice_credits (person_id);

-- 萌娘与 Bangumi 的角色映射不是实体合并结论，保留为可审计的外部引用。
create table if not exists catalog_character_external_refs (
    character_id bigint not null references catalog_characters(id) on delete cascade,
    external_source text not null,
    external_key text not null,
    metadata jsonb not null default '{}',
    primary key (character_id, external_source, external_key)
);
create index if not exists catalog_character_external_refs_lookup_idx
    on catalog_character_external_refs (external_source, external_key);

create table if not exists catalog_external_redirects (
    external_source text not null,
    from_key text not null,
    to_key text not null,
    primary key (external_source, from_key)
);

-- 由人物信息框直接给出的发色、瞳色不会经过词表归一化，保留原值以备后续标准化。
create table if not exists catalog_character_physical_traits (
    character_id bigint not null references catalog_characters(id) on delete cascade,
    trait_type text not null,
    value text not null,
    primary key (character_id, trait_type, value)
);
create index if not exists catalog_character_physical_traits_lookup_idx
    on catalog_character_physical_traits (trait_type, value);
