-- サイト（web/）のランキング用・読み取り専用ビュー
-- 公開してよい集計値だけを出す。サイトはサーバー側（Server Component / Route Handler）からのみ読むこと。
-- security_invoker = true: 呼び出したロール（anon）の権限・RLS で元の表を読む。
-- 適用は TYPETA のレビュー後に Luna が行う。

begin;

-- 所持コイン上位 100 人（users には表示名がないため Discord の user_id のみ）
create or replace view public.ranking_balance_top
with (security_invoker = true) as
select
  rank() over (order by u.balance desc) as rank,
  u.user_id,
  u.balance
from public.users u
where u.balance > 0
order by u.balance desc, u.user_id
limit 100;

-- 国（サーバー）ごとの領土ランキング
create or replace view public.ranking_nations
with (security_invoker = true) as
select
  rank() over (order by count(t.x) desc) as rank,
  g.guild_id,
  count(t.x)::int as tile_count,
  g.capital_x,
  g.capital_y,
  (select count(*)::int from public.nation_players p where p.guild_id = g.guild_id) as member_count
from public.nation_guilds g
left join public.nation_tiles t on t.owner_guild_id = g.guild_id
group by g.guild_id, g.capital_x, g.capital_y
order by tile_count desc, g.guild_id
limit 100;

-- 権限: 読み取りのみ、サイトの anon キーのロールだけに許可
revoke all on public.ranking_balance_top, public.ranking_nations from public, anon, authenticated;
grant select on public.ranking_balance_top, public.ranking_nations to anon;

commit;
