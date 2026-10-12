-- Bot の小さな設定・状態（ミュートの期限、サーバーごとの設定など）を保存するキー・バリューのテーブル。
-- core/storage.py が使います。何度実行しても大丈夫です。
-- このテーブルが無いあいだは、Bot はローカルの JSON ファイル（bot_kv.json）に保存します。
create table if not exists public.bot_kv (
  namespace text not null,
  key text not null,
  value jsonb,
  updated_at timestamptz not null default now(),
  primary key (namespace, key)
);
