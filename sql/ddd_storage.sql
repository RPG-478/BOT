-- DDD 鑑定画像用 Supabase Storage 設定
-- Supabase Dashboard の SQL Editor で、管理者権限を持つユーザーとして1回実行してください。
-- Bot は SUPABASE_SERVICE_ROLE_KEY を使用する前提です。

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

-- 確認用
select id, name, public, file_size_limit, allowed_mime_types
from storage.buckets
where id = 'dot_images';

-- 注意:
-- SUPABASE_SERVICE_ROLE_KEY は storage.objects の RLS をバイパスするため、
-- Bot のアップロード用ポリシーを追加する必要はありません。
-- SUPABASE_ANON_KEY をBotに設定する場合は、無制限の公開アップロードを避け、
-- Bot専用の認証・RLS設計を先に行ってください。
