-- /fujo（生存確認）で使う列。何度実行しても大丈夫です。
create table if not exists public.fujo_users (
  user_id bigint primary key,
  registered_at timestamptz not null default now()
);
alter table public.fujo_users
  add column if not exists streak_count integer not null default 0,
  add column if not exists last_streak_date date,
  add column if not exists is_frozen boolean not null default false,
  add column if not exists last_pester_level integer not null default 0,
  add column if not exists panic_days integer,
  add column if not exists panic_message text,
  add column if not exists panic_channel_id bigint,
  add column if not exists last_panic_at timestamptz;

create table if not exists public.fujo_activities (
  id bigserial primary key,
  user_id bigint not null references public.fujo_users (user_id) on delete cascade,
  detected_at timestamptz not null default now(),
  signal_type text,
  status text
);
create index if not exists idx_fujo_activities_user_detected
  on public.fujo_activities (user_id, detected_at desc);
create index if not exists fujo_activities_detected_idx
  on public.fujo_activities (detected_at);

-- Bot は anon キーでつなぐので、検知ログの id を採番する権限が必要です。
grant usage, select on sequence public.fujo_activities_id_seq to anon, authenticated;
