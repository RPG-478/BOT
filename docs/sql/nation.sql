-- 国づくり MMO フェーズ 1 のテーブルと関数（何度実行しても安全）。
-- 所持金は /wallet と共通で public.users.balance を使います（users.user_id は text）。
-- RLS は使いません（bot は anon キーで読み書きするため）。

create table if not exists public.nation_guilds (
    guild_id        text primary key,
    capital_x       int,
    capital_y       int,
    treasury_coins  bigint  not null default 0,
    tax_rate        numeric not null default 0   check (tax_rate between 0 and 0.5),
    labor_reward    int     not null default 0   check (labor_reward >= 0),
    entry_fee       int     not null default 0   check (entry_fee >= 0),
    exit_fee_rate   numeric not null default 0   check (exit_fee_rate between 0 and 0.8),
    created_at      timestamptz not null default now()
);

create table if not exists public.nation_tiles (
    x                 int not null,
    y                 int not null,
    owner_guild_id    text,
    owner_user_id     text,
    tile_type         text not null default 'plain'
        check (tile_type in ('plain','farm','mine','shop','casino','restaurant','capital','railway')),
    individual_values jsonb not null default '{}'::jsonb,
    hp                int not null default 100,
    max_hp            int not null default 100,
    def               int not null default 0,
    connected         boolean not null default false,
    created_at        timestamptz not null default now(),
    primary key (x, y)
);
create index if not exists nation_tiles_owner_guild_idx on public.nation_tiles (owner_guild_id);
create index if not exists nation_tiles_owner_user_idx  on public.nation_tiles (owner_user_id);

create table if not exists public.nation_alliances (
    guild_id      text not null,
    ally_guild_id text not null,
    primary key (guild_id, ally_guild_id)
);

create table if not exists public.nation_players (
    user_id         text primary key,
    guild_id        text,
    hunger          int  not null default 100 check (hunger between 0 and 100),
    role            text not null default 'citizen' check (role in ('king','minister','citizen')),
    last_hunger_at  timestamptz not null default now(),
    joined_at       timestamptz not null default now()
);
create index if not exists nation_players_guild_idx on public.nation_players (guild_id);

-- 所持金（users.balance）と空腹度を 1 トランザクションで増減します。
-- #33 の transfer_coins 案と同じく、条件付き UPDATE 1 回で残高チェックと更新を同時に行います。
-- 残高がマイナスになる場合、空腹度が 0 未満になる場合、プレイヤー未登録の場合は例外。
-- users.balance は integer で NULL 可のため coalesce で 0 扱い。users.hunger 列は既存の別機能のもので、使いません。
-- 空腹度の上限は 100 で丸めます。users の行がなければ /wallet と同じく残高 10 で作ります。
create or replace function public.nation_adjust(
    p_user_id     text,
    p_coins_delta bigint,
    p_hunger_delta int
) returns table (balance bigint, hunger int)
language plpgsql
as $$
declare
    v_balance bigint;
    v_hunger  int;
begin
    update public.nation_players p
       set hunger = least(100, p.hunger + p_hunger_delta),
           last_hunger_at = case when p_hunger_delta < 0 then now() else p.last_hunger_at end
     where p.user_id = p_user_id and p.hunger + p_hunger_delta >= 0
    returning p.hunger into v_hunger;
    if not found then
        if exists (select 1 from public.nation_players where user_id = p_user_id) then
            raise exception 'insufficient hunger';
        end if;
        raise exception 'player not found';
    end if;

    insert into public.users (user_id, balance, debt)
    values (p_user_id, 10, 0)
    on conflict (user_id) do nothing;

    update public.users u
       set balance = coalesce(u.balance, 0) + p_coins_delta
     where u.user_id = p_user_id and coalesce(u.balance, 0) + p_coins_delta >= 0
    returning u.balance::bigint into v_balance;
    if not found then
        raise exception 'insufficient balance';
    end if;

    return query select v_balance, v_hunger;
end;
$$;

grant select, insert, update, delete on
    public.nation_guilds, public.nation_tiles, public.nation_alliances, public.nation_players
    to anon, authenticated;
-- コインを動かす関数は、TYPETA の tradedemo/quiz 修正が入るまで本番では呼べないようにしておきます。
revoke execute on function public.nation_adjust(text, bigint, int) from public, anon, authenticated;

-- 【あとで有効化】修正が入って OK が出たら、次の 1 行を実行します。
-- grant execute on function public.nation_adjust(text, bigint, int) to anon, authenticated;
