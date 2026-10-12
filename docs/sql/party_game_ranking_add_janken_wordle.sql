-- パーティーゲームのランキングに 'janken'（じゃんけん）と 'wordle'（Wordle）を足す。
-- party_game_ranking.sql を適用済みの本番向け。何度流しても同じ結果になる（冪等）。
-- - 表 party_game_wins の game の check 制約を、新しい一覧で張り直す。
-- - 関数 party_game_record_win を同じ中身で作り直し、許すゲーム名だけ増やす。
--   security definer・search_path の固定・guild_id / user_id の確認・権限はそのまま。
-- 適用は TYPETA のレビュー後に Luna が行う。本番では試さないこと。

begin;

-- 名前の付いていない check 制約は既定で party_game_wins_game_check になる
alter table public.party_game_wins drop constraint if exists party_game_wins_game_check;
alter table public.party_game_wins add constraint party_game_wins_game_check
  check (game in ('ngword', 'shiritori', 'wordwolf', 'jinrou', 'uno', 'doubt', 'janken', 'wordle'));

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
  if p_game is null or p_game not in ('ngword', 'shiritori', 'wordwolf', 'jinrou', 'uno', 'doubt', 'janken', 'wordle') then
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

commit;
