-- DDD 進行・宝箱・アイテム・トレード拡張
-- Supabase SQL Editor で一度だけ実行する。

create table if not exists public.ddd_items (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    item_code text not null check (item_code in (
        'orb_虚', 'orb_実', 'orb_正', 'orb_負', 'orb_無',
        'move_reset_ticket', 'trade_ticket', 'upraise_crystal', 'herb'
    )),
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists ddd_items_user_item_created_idx
    on public.ddd_items (user_id, item_code, created_at);

create table if not exists public.ddd_chests (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    source text not null default 'work',
    opened_at timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists ddd_chests_unopened_idx
    on public.ddd_chests (user_id, created_at)
    where opened_at is null;

alter table public.monsters
    add column if not exists breakthrough_stage integer not null default 0;

alter table public.monsters
    drop constraint if exists monsters_breakthrough_stage_check;

alter table public.monsters
    add constraint monsters_breakthrough_stage_check
    check (breakthrough_stage in (0, 30, 40));

alter table public.work_sessions
    add column if not exists work_type text not null default 'normal';

alter table public.work_sessions
    drop constraint if exists work_sessions_work_type_check;

alter table public.work_sessions
    add constraint work_sessions_work_type_check
    check (work_type in ('normal', 'training'));

-- 通常作業とトレーニングを含め、プレイヤーごとの同時派遣は1件だけにする。
create unique index if not exists work_sessions_one_active_per_user_idx
    on public.work_sessions (user_id);

-- 完了済みの作業報酬を、残高・EXP・宝箱・セッション削除まで一括で確定する。
create or replace function public.ddd_finalize_work(
    p_session_id uuid,
    p_user_id text,
    p_old_level integer,
    p_old_exp integer,
    p_new_level integer,
    p_new_exp integer,
    p_coins integer,
    p_award_chest boolean
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    session_row public.work_sessions%rowtype;
    monster_row public.monsters%rowtype;
begin
    select * into session_row
    from public.work_sessions
    where id = p_session_id and user_id = p_user_id
    for update;
    if not found then
        raise exception 'work_session_not_found';
    end if;
    if session_row.finish_time > now() then
        raise exception 'work_not_finished';
    end if;

    select * into monster_row
    from public.monsters
    where id = session_row.monster_id and user_id = p_user_id
    for update;
    if not found then
        raise exception 'work_monster_not_found';
    end if;
    if monster_row.current_level <> p_old_level or monster_row.current_exp <> p_old_exp then
        raise exception 'work_monster_changed';
    end if;

    if p_coins > 0 then
        update public.users
        set balance = balance + p_coins
        where user_id = p_user_id;
        if not found then
            raise exception 'work_user_not_found';
        end if;
        insert into public.transaction_history (sender_id, receiver_id, amount, reason)
        values ('SYSTEM_WORK', p_user_id, p_coins, 'ddd_work_normal_reward');
    end if;

    update public.monsters
    set current_level = p_new_level, current_exp = p_new_exp
    where id = session_row.monster_id;

    if p_award_chest then
        insert into public.ddd_chests (user_id, source)
        values (p_user_id, 'work');
    end if;

    delete from public.work_sessions where id = p_session_id;
    return jsonb_build_object('completed', true);
end;
$$;

grant execute on function public.ddd_finalize_work(uuid, text, integer, integer, integer, integer, integer, boolean) to anon, authenticated;

create table if not exists public.ddd_trades (
    id uuid primary key default gen_random_uuid(),
    proposer_id text not null,
    partner_id text not null,
    proposer_monster_id uuid not null references public.monsters(id),
    partner_monster_id uuid references public.monsters(id),
    payment_kind text not null check (payment_kind in ('coin', 'ticket')),
    proposer_approved_at timestamptz,
    partner_approved_at timestamptz,
    status text not null default 'selecting_partner'
        check (status in ('selecting_partner', 'awaiting_approval', 'completed', 'cancelled', 'expired')),
    expires_at timestamptz not null default (now() + interval '10 minutes'),
    completed_at timestamptz,
    cancelled_at timestamptz,
    created_at timestamptz not null default now(),
    check (proposer_id <> partner_id),
    check (proposer_monster_id <> partner_monster_id)
);

create index if not exists ddd_trades_active_participants_idx
    on public.ddd_trades (proposer_id, partner_id, expires_at)
    where status in ('selecting_partner', 'awaiting_approval');

create unique index if not exists ddd_trades_active_proposer_card_idx
    on public.ddd_trades (proposer_monster_id)
    where status in ('selecting_partner', 'awaiting_approval');

create unique index if not exists ddd_trades_active_partner_card_idx
    on public.ddd_trades (partner_monster_id)
    where status in ('selecting_partner', 'awaiting_approval') and partner_monster_id is not null;

-- 承認済みトレードを一つのDBトランザクションで確定する。
create or replace function public.ddd_finalize_trade(p_trade_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    trade_row public.ddd_trades%rowtype;
    proposer_card public.monsters%rowtype;
    partner_card public.monsters%rowtype;
    payment_ticket public.ddd_items%rowtype;
begin
    select * into trade_row
    from public.ddd_trades
    where id = p_trade_id
    for update;

    if not found then
        raise exception 'trade_not_found';
    end if;
    if trade_row.status <> 'awaiting_approval'
       or trade_row.proposer_approved_at is null
       or trade_row.partner_approved_at is null then
        raise exception 'trade_not_ready';
    end if;
    if trade_row.expires_at <= now() then
        update public.ddd_trades
        set status = 'expired', cancelled_at = now()
        where id = p_trade_id;
        raise exception 'trade_expired';
    end if;

    select * into proposer_card
    from public.monsters
    where id = trade_row.proposer_monster_id
    for update;
    select * into partner_card
    from public.monsters
    where id = trade_row.partner_monster_id
    for update;

    if proposer_card.user_id <> trade_row.proposer_id
       or partner_card.user_id <> trade_row.partner_id then
        raise exception 'trade_card_owner_changed';
    end if;

    if trade_row.payment_kind = 'coin' then
        update public.users
        set balance = balance - 5000
        where user_id = trade_row.proposer_id
          and balance >= 5000;
        if not found then
            raise exception 'trade_insufficient_coin';
        end if;
        insert into public.transaction_history (sender_id, receiver_id, amount, reason)
        values (trade_row.proposer_id, 'SYSTEM_DDD', 5000, 'ddd_trade_fee');
    else
        select * into payment_ticket
        from public.ddd_items
        where user_id = trade_row.proposer_id
          and item_code = 'trade_ticket'
        order by created_at
        limit 1
        for update;
        if not found then
            raise exception 'trade_ticket_missing';
        end if;
        delete from public.ddd_items where id = payment_ticket.id;
    end if;

    update public.monsters
    set user_id = trade_row.partner_id
    where id = trade_row.proposer_monster_id;
    update public.monsters
    set user_id = trade_row.proposer_id
    where id = trade_row.partner_monster_id;

    update public.ddd_trades
    set status = 'completed', completed_at = now()
    where id = p_trade_id;

    return jsonb_build_object(
        'proposer_card_name', proposer_card.name,
        'partner_card_name', partner_card.name
    );
end;
$$;

grant execute on function public.ddd_finalize_trade(uuid) to anon, authenticated;

-- 過去のパレット情報は動作に参照されない。新規ユーザー作成時にも不要にする。
alter table public.monsters
    alter column canvas_size drop not null;

alter table public.users
    alter column unlocked_palettes drop not null;
