-- DDD レイド・レイドチケット・突破修正
-- Supabase Dashboard の SQL Editor で、既存の 20260907_ddd_progression.sql の後に一度だけ実行してください。
-- 実行前に、強力なランダム文字列へ置換してDB側の共有シークレットを設定してください。
-- Botの環境変数 DDD_RAID_RPC_SECRET にも完全に同じ値を設定します。
-- alter database postgres set app.ddd_raid_rpc_secret = 'REPLACE_WITH_A_LONG_RANDOM_SECRET';

-- 既存のアイテム制約とショップ制約にレイドチケットを追加する。
alter table public.ddd_items
    drop constraint if exists ddd_items_item_code_check;
alter table public.ddd_items
    add constraint ddd_items_item_code_check
    check (item_code in (
        'orb_虚', 'orb_実', 'orb_正', 'orb_負', 'orb_無',
        'move_reset_ticket', 'trade_ticket', 'raid_ticket', 'upraise_crystal', 'herb'
    ));

alter table public.ddd_shop_purchases
    drop constraint if exists ddd_shop_purchases_item_code_check;
alter table public.ddd_shop_purchases
    add constraint ddd_shop_purchases_item_code_check
    check (item_code in (
        'orb_虚', 'orb_実', 'orb_正', 'orb_負', 'orb_無',
        'move_reset_ticket', 'trade_ticket', 'raid_ticket', 'upraise_crystal', 'herb'
    ));

-- 過去データを含め、Lv.30 / Lv.40 の突破判定に必要な段階を必ず初期化する。
-- 旧仕様でLv.31以上まで育成済みのモンスターは、到達済みの突破段階を復元する。
alter table public.monsters
    add column if not exists breakthrough_stage integer not null default 0;
update public.monsters
set breakthrough_stage = case
    when current_level >= 41 then 40
    when current_level >= 31 then 30
    else 0
end
where breakthrough_stage is null
   or breakthrough_stage not in (0, 30, 40)
   or (current_level between 31 and 40 and breakthrough_stage = 0)
   or (current_level >= 41 and breakthrough_stage in (0, 30));
alter table public.monsters
    drop constraint if exists monsters_breakthrough_stage_check;
alter table public.monsters
    add constraint monsters_breakthrough_stage_check
    check (breakthrough_stage in (0, 30, 40));

-- 旧スキーマのLv.30上限制約を解除し、突破後のLv.31/Lv.41〜50を許可する。
alter table public.monsters
    drop constraint if exists monsters_current_level_check;
alter table public.monsters
    add constraint monsters_current_level_check
    check (current_level between 1 and 50);

-- アップレイズクリスタルは1キャラにつき1個分だけ保持し、次回使用時に上書きする。
alter table public.monsters
    add column if not exists upraise_crystal_boosts jsonb not null default '[]'::jsonb;

create table if not exists public.ddd_raids (
    id uuid primary key default gen_random_uuid(),
    host_user_id text not null,
    boss_state jsonb not null,
    raid_state jsonb,
    channel_id text,
    status text not null default 'recruiting'
        check (status in ('recruiting', 'active', 'cleared', 'failed', 'cancelled')),
    join_deadline timestamptz not null,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists public.ddd_raid_participants (
    id uuid primary key default gen_random_uuid(),
    raid_id uuid not null references public.ddd_raids(id) on delete cascade,
    user_id text not null,
    monster_id uuid not null references public.monsters(id) on delete restrict,
    monster_snapshot jsonb,
    joined_at timestamptz not null default now(),
    unique (raid_id, user_id),
    unique (raid_id, monster_id)
);

-- テーブルが先に作成されていた場合も、参加中モンスターの削除を防ぐ。
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'ddd_raid_participants_monster_id_fkey'
          and conrelid = 'public.ddd_raid_participants'::regclass
    ) then
        alter table public.ddd_raid_participants
            add constraint ddd_raid_participants_monster_id_fkey
            foreign key (monster_id) references public.monsters(id) on delete restrict;
    end if;
end;
$$;

create index if not exists ddd_raids_status_deadline_idx
    on public.ddd_raids (status, join_deadline);
create index if not exists ddd_raid_participants_user_raid_idx
    on public.ddd_raid_participants (user_id, raid_id);

alter table public.ddd_raids
    add column if not exists channel_id text;
alter table public.ddd_raid_participants
    add column if not exists monster_snapshot jsonb;

-- Bot の公開キーからレイド状態を直接変更できないよう、読み取り以外の権限を外す。
revoke all on table public.ddd_raids from anon, authenticated;
revoke all on table public.ddd_raid_participants from anon, authenticated;
grant select on table public.ddd_raids to anon, authenticated;
grant select on table public.ddd_raid_participants to anon, authenticated;

-- レイドチケットを消費し、ホストを参加者として含めた3分間の募集を作成する。
create or replace function public.ddd_create_raid(
    p_host_user_id text,
    p_monster_id uuid,
    p_boss_state jsonb,
    p_join_deadline timestamptz,
    p_channel_id text,
    p_access_token text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    ticket_row public.ddd_items%rowtype;
    host_monster public.monsters%rowtype;
    raid_row public.ddd_raids%rowtype;
    participant_count integer;
begin
    if p_access_token is null
       or p_access_token is distinct from current_setting('app.ddd_raid_rpc_secret', true) then
        raise exception 'raid_unauthorized';
    end if;
    perform pg_advisory_xact_lock(hashtext('ddd_raid:' || p_host_user_id));
    if p_join_deadline <= now() then
        raise exception 'raid_recruitment_closed';
    end if;
    if exists (
        select 1
        from public.ddd_raid_participants participant
        join public.ddd_raids raid on raid.id = participant.raid_id
        where participant.user_id = p_host_user_id
          and raid.status in ('recruiting', 'active')
    ) then
        raise exception 'raid_user_busy';
    end if;
    select * into host_monster from public.monsters
    where id = p_monster_id and user_id = p_host_user_id
    for key share;
    if not found then
        raise exception 'raid_monster_not_found';
    end if;
    select * into ticket_row
    from public.ddd_items
    where user_id = p_host_user_id and item_code = 'raid_ticket'
    order by created_at
    limit 1
    for update skip locked;
    if not found then
        raise exception 'raid_ticket_missing';
    end if;

    insert into public.ddd_raids (host_user_id, boss_state, join_deadline, channel_id)
    values (p_host_user_id, p_boss_state, p_join_deadline, p_channel_id)
    returning * into raid_row;
    insert into public.ddd_raid_participants (raid_id, user_id, monster_id, monster_snapshot)
    values (raid_row.id, p_host_user_id, p_monster_id, to_jsonb(host_monster));
    delete from public.ddd_items where id = ticket_row.id;

    select count(*) into participant_count
    from public.ddd_raid_participants where raid_id = raid_row.id;
    return jsonb_build_object(
        'id', raid_row.id,
        'host_user_id', raid_row.host_user_id,
        'boss_state', raid_row.boss_state,
        'join_deadline', raid_row.join_deadline,
        'status', raid_row.status,
        'participant_count', participant_count
    );
end;
$$;

-- 募集期限内の参加者からチケットを1枚消費し、1体をレイドに登録する。
create or replace function public.ddd_join_raid(
    p_raid_id uuid,
    p_user_id text,
    p_monster_id uuid,
    p_access_token text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    raid_row public.ddd_raids%rowtype;
    ticket_row public.ddd_items%rowtype;
    participant_monster public.monsters%rowtype;
    participant_count integer;
begin
    if p_access_token is null
       or p_access_token is distinct from current_setting('app.ddd_raid_rpc_secret', true) then
        raise exception 'raid_unauthorized';
    end if;
    select * into raid_row
    from public.ddd_raids
    where id = p_raid_id and status = 'recruiting'
    for update;
    if not found or raid_row.join_deadline <= now() then
        raise exception 'raid_recruitment_closed';
    end if;
    perform pg_advisory_xact_lock(hashtext('ddd_raid:' || p_user_id));
    if exists (
        select 1
        from public.ddd_raid_participants participant
        join public.ddd_raids raid on raid.id = participant.raid_id
        where participant.user_id = p_user_id
          and raid.status in ('recruiting', 'active')
    ) then
        if exists (
            select 1 from public.ddd_raid_participants
            where raid_id = p_raid_id and user_id = p_user_id
        ) then
            raise exception 'raid_already_joined';
        end if;
        raise exception 'raid_user_busy';
    end if;
    select count(*) into participant_count
    from public.ddd_raid_participants where raid_id = p_raid_id;
    if participant_count >= 20 then
        raise exception 'raid_full';
    end if;
    select * into participant_monster from public.monsters
    where id = p_monster_id and user_id = p_user_id
    for key share;
    if not found then
        raise exception 'raid_monster_not_found';
    end if;
    select * into ticket_row
    from public.ddd_items
    where user_id = p_user_id and item_code = 'raid_ticket'
    order by created_at
    limit 1
    for update skip locked;
    if not found then
        raise exception 'raid_ticket_missing';
    end if;

    insert into public.ddd_raid_participants (raid_id, user_id, monster_id, monster_snapshot)
    values (p_raid_id, p_user_id, p_monster_id, to_jsonb(participant_monster));
    delete from public.ddd_items where id = ticket_row.id;
    participant_count := participant_count + 1;
    return jsonb_build_object('raid_id', p_raid_id, 'participant_count', participant_count);
end;
$$;

-- 募集済みの参加者と確定した速度順の状態を一括で開始する。
create or replace function public.ddd_start_raid(
    p_raid_id uuid,
    p_host_user_id text,
    p_state jsonb,
    p_access_token text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    raid_row public.ddd_raids%rowtype;
    stored_roster jsonb;
begin
    if p_access_token is null
       or p_access_token is distinct from current_setting('app.ddd_raid_rpc_secret', true) then
        raise exception 'raid_unauthorized';
    end if;
    select * into raid_row
    from public.ddd_raids
    where id = p_raid_id and status = 'recruiting'
    for update;
    if not found then
        raise exception 'raid_not_recruiting';
    end if;
    if raid_row.host_user_id <> p_host_user_id then
        raise exception 'raid_not_host';
    end if;
    if not exists (select 1 from public.ddd_raid_participants where raid_id = p_raid_id) then
        raise exception 'raid_no_participants';
    end if;
    select coalesce(jsonb_agg(jsonb_build_object('user_id', user_id, 'monster_id', monster_id::text) order by joined_at), '[]'::jsonb)
    into stored_roster
    from public.ddd_raid_participants
    where raid_id = p_raid_id;
    if coalesce(p_state -> 'roster', '[]'::jsonb) <> stored_roster then
        raise exception 'raid_roster_changed';
    end if;
    update public.ddd_raids
    set status = 'active', raid_state = p_state, started_at = now()
    where id = p_raid_id;
    return jsonb_build_object('id', p_raid_id, 'status', 'active');
end;
$$;

-- バージョン照合を行い、討伐時だけ全参加者へ報酬を原子的に配布する。
create or replace function public.ddd_finalize_raid(
    p_raid_id uuid,
    p_expected_version integer,
    p_state jsonb,
    p_outcome text,
    p_access_token text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    raid_row public.ddd_raids%rowtype;
    participant record;
    reward_index integer;
begin
    if p_access_token is null
       or p_access_token is distinct from current_setting('app.ddd_raid_rpc_secret', true) then
        raise exception 'raid_unauthorized';
    end if;
    if p_outcome not in ('cleared', 'failed') then
        raise exception 'raid_outcome_invalid';
    end if;
    select * into raid_row
    from public.ddd_raids
    where id = p_raid_id and status = 'active'
    for update;
    if not found then
        raise exception 'raid_not_active';
    end if;
    if coalesce((raid_row.raid_state ->> 'version')::integer, -1) <> p_expected_version then
        raise exception 'raid_state_conflict';
    end if;
    if p_outcome = 'cleared'
       and coalesce((p_state -> 'boss' ->> 'current_hp')::integer, 1) > 0 then
        raise exception 'raid_not_defeated';
    end if;

    if p_outcome = 'cleared' then
        for participant in
            select user_id from public.ddd_raid_participants where raid_id = p_raid_id
        loop
            update public.users
            set balance = balance + 20000
            where user_id = participant.user_id;
            if not found then
                raise exception 'raid_user_not_found';
            end if;
            insert into public.transaction_history (sender_id, receiver_id, amount, reason)
            values ('SYSTEM_DDD_RAID', participant.user_id, 20000, 'ddd_raid_clear_reward');
            for reward_index in 1..5 loop
                insert into public.ddd_chests (user_id, source)
                values (participant.user_id, 'raid');
            end loop;
        end loop;
    end if;

    update public.ddd_raids
    set status = p_outcome, raid_state = p_state, finished_at = now()
    where id = p_raid_id;
    return jsonb_build_object('id', p_raid_id, 'status', p_outcome);
end;
$$;

-- レイドの行動状態はBotからの署名付きRPCだけが更新する。
create or replace function public.ddd_save_raid_state(
    p_raid_id uuid,
    p_expected_version integer,
    p_state jsonb,
    p_access_token text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    raid_row public.ddd_raids%rowtype;
begin
    if p_access_token is null
       or p_access_token is distinct from current_setting('app.ddd_raid_rpc_secret', true) then
        raise exception 'raid_unauthorized';
    end if;
    select * into raid_row from public.ddd_raids
    where id = p_raid_id and status = 'active'
    for update;
    if not found then
        raise exception 'raid_not_active';
    end if;
    if coalesce((raid_row.raid_state ->> 'version')::integer, -1) <> p_expected_version then
        raise exception 'raid_state_conflict';
    end if;
    update public.ddd_raids set raid_state = p_state where id = p_raid_id;
    return jsonb_build_object('id', p_raid_id, 'status', 'active');
end;
$$;

revoke all on function public.ddd_create_raid(text, uuid, jsonb, timestamptz, text, text) from public, anon, authenticated;
revoke all on function public.ddd_join_raid(uuid, text, uuid, text) from public, anon, authenticated;
revoke all on function public.ddd_start_raid(uuid, text, jsonb, text) from public, anon, authenticated;
revoke all on function public.ddd_finalize_raid(uuid, integer, jsonb, text, text) from public, anon, authenticated;
revoke all on function public.ddd_save_raid_state(uuid, integer, jsonb, text) from public, anon, authenticated;
grant execute on function public.ddd_create_raid(text, uuid, jsonb, timestamptz, text, text) to anon, authenticated;
grant execute on function public.ddd_join_raid(uuid, text, uuid, text) to anon, authenticated;
grant execute on function public.ddd_start_raid(uuid, text, jsonb, text) to anon, authenticated;
grant execute on function public.ddd_finalize_raid(uuid, integer, jsonb, text, text) to anon, authenticated;
grant execute on function public.ddd_save_raid_state(uuid, integer, jsonb, text) to anon, authenticated;

-- レイドチケットを週1回、7,000コインで購入できるようショップ確定処理を更新する。
create or replace function public.ddd_shop_purchase(
    p_week_start date,
    p_user_id text,
    p_item_code text,
    p_price integer,
    p_quantity integer
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    shop_row public.ddd_shop_weeks%rowtype;
    purchase_id uuid;
    item_index integer;
begin
    select * into shop_row from public.ddd_shop_weeks where week_start = p_week_start for update;
    if not found then raise exception 'shop_week_not_found'; end if;
    if p_item_code in ('orb_虚', 'orb_実', 'orb_正', 'orb_負', 'orb_無') then
        if p_quantity <> 1 or p_price <> 10000 then raise exception 'shop_price_invalid'; end if;
    elsif p_item_code in ('move_reset_ticket', 'trade_ticket', 'raid_ticket') then
        if p_quantity <> 1 or p_price <> 7000 then raise exception 'shop_price_invalid'; end if;
    elsif p_item_code = 'herb' then
        if p_quantity <> 5 or p_price <> 3000 then raise exception 'shop_price_invalid'; end if;
    else
        raise exception 'shop_item_invalid';
    end if;
    if exists (select 1 from public.ddd_shop_purchases where week_start = p_week_start and user_id = p_user_id and item_code = p_item_code) then
        raise exception 'shop_item_already_purchased';
    end if;
    if p_item_code in ('orb_虚', 'orb_実', 'orb_正', 'orb_負', 'orb_無')
       and exists (
           select 1 from public.ddd_shop_purchases
           where week_start = p_week_start and user_id = p_user_id
             and item_code in ('orb_虚', 'orb_実', 'orb_正', 'orb_負', 'orb_無')
       ) then
        raise exception 'shop_orb_already_purchased';
    end if;
    update public.users set balance = balance - p_price where user_id = p_user_id and balance >= p_price;
    if not found then raise exception 'shop_insufficient_coin'; end if;
    insert into public.transaction_history (sender_id, receiver_id, amount, reason)
    values (p_user_id, 'SYSTEM_DDD_SHOP', p_price, 'ddd_shop_purchase');
    for item_index in 1..p_quantity loop
        insert into public.ddd_items (user_id, item_code, metadata)
        values (p_user_id, p_item_code, '{}'::jsonb);
    end loop;
    insert into public.ddd_shop_purchases (week_start, user_id, item_code, quantity)
    values (p_week_start, p_user_id, p_item_code, p_quantity)
    returning id into purchase_id;
    return jsonb_build_object('purchase_id', purchase_id, 'item_code', p_item_code, 'quantity', p_quantity, 'price', p_price);
end;
$$;

grant execute on function public.ddd_shop_purchase(date, text, text, integer, integer) to anon, authenticated;
