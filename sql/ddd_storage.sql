-- DDD 鑑定画像用 Supabase Storage 設定
-- Supabase Dashboard の SQL Editor で、管理者権限を持つユーザーとして1回実行してください。
-- Botは既存の SUPABASE_URL と SUPABASE_KEY を使用します。

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'dot_images',
    'dot_images',
    true,
    5242880,
    array['image/png', 'image/jpeg', 'image/webp', 'image/gif']::text[]
)
on conflict (id) do update set
    name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

-- SUPABASE_KEYがanon keyの場合、storage.objectsのRLSでINSERTを許可する。
-- 保存先はDDDの鑑定画像用 monsters/ 配下だけに限定する。
drop policy if exists "ddd_upload_dot_images" on storage.objects;
create policy "ddd_upload_dot_images"
on storage.objects
for insert
to anon, authenticated
with check (
    bucket_id = 'dot_images'
    and name like 'monsters/%'
);

-- 確認用
select id, name, public, file_size_limit, allowed_mime_types
from storage.buckets
where id = 'dot_images';

select policyname, cmd, roles, qual, with_check
from pg_policies
where schemaname = 'storage'
  and tablename = 'objects'
  and policyname = 'ddd_upload_dot_images';

-- 注意:
-- 公開バケットのため、保存済み画像はget_public_urlで閲覧できます。
-- SUPABASE_SERVICE_ROLE_KEYを使う場合は上記ポリシーをバイパスできますが、
-- 現行BotはSUPABASE_KEYで動かす前提のため、この限定INSERTポリシーを使用します。
