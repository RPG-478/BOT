-- パーティーゲームのサーバーごとの勝利数ランキング
-- - 表 party_game_wins: (guild_id, user_id, game) ごとの勝利数。anon からは直接読み書きできない。
-- - 関数 party_game_record_win: 入力を確かめてから、勝利数を 1 つ増やす（upsert なので同時に呼ばれても安全）。
--   security definer なので、anon は関数経由でだけ書き込める。
-- - ビュー party_game_ranking: 順位付きの読み取り用。security_invoker = false なので、
--   anon は元の表を読めなくてもビューだけ読める。
-- 適用は TYPETA のレビュー後に Luna が行う。本番では試さないこと。

begin;

create table if not exists public.party_game_wins (
  guild_id   bigint      not null check (guild_id > 0),
  user_id    bigint      not null check (user_id > 0),
  game       text        not null check (game in ('ngword', 'shiritori', 'wordwolf', 'jinrou', 'uno', 'doubt', 'janken', 'wordle', 'shinkei', 'babanuki', 'daifugo')),
  wins       integer     not null default 0 check (wins >= 0),
  updated_at timestamptz not null default now(),
  primary key (guild_id, user_id, game)
);

alter table public.party_game_wins enable row level security;
revoke all on public.party_game_wins from public, anon, authenticated;

create or replace function public.party_game_record_win(p_guild_id bigint, p_user_id bigint, p_game text)
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_wins integer;
begin
  if p_guild_id is null or p_guild_id <= 0 then
    raise exception 'invalid guild_id' using errcode = '22023';
  end if;
  if p_user_id is null or p_user_id <= 0 then
    raise exception 'invalid user_id' using errcode = '22023';
  end if;
  if p_game is null or p_game not in ('ngword', 'shiritori', 'wordwolf', 'jinrou', 'uno', 'doubt', 'janken', 'wordle', 'shinkei', 'babanuki', 'daifugo') then
    raise exception 'unknown game: %', p_game using errcode = '22023';
  end if;

  insert into public.party_game_wins as w (guild_id, user_id, game, wins)
  values (p_guild_id, p_user_id, p_game, 1)
  on conflict (guild_id, user_id, game)
  do update set wins = w.wins + 1, updated_at = now()
  returning w.wins into v_wins;

  return v_wins;
end;
$$;

revoke all on function public.party_game_record_win(bigint, bigint, text) from public, anon, authenticated;
grant execute on function public.party_game_record_win(bigint, bigint, text) to anon, service_role;

create or replace view public.party_game_ranking
with (security_invoker = false) as
select
  w.guild_id,
  w.game,
  w.user_id,
  w.wins,
  rank() over (partition by w.guild_id, w.game order by w.wins desc) as rank
from public.party_game_wins w
where w.wins > 0;

revoke all on public.party_game_ranking from public, anon, authenticated;
grant select on public.party_game_ranking to anon, service_role;

commit;
