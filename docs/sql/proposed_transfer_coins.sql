-- /pay の送金を1回のDBトランザクションで行うマイグレーション。
-- アプリ起動時にDDLを実行せず、Supabase SQL Editor / Migrationで一度だけ適用する。

begin;
create or replace function public.transfer_coins(
    p_sender_id text,
    p_receiver_id text,
    p_amount bigint,
    p_new_user_balance bigint default 10
) returns bigint            -- 送金後の送り手の残高。残高不足なら例外
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_sender_balance bigint;
begin
    if p_amount is null or p_amount <= 0 then
        raise exception 'amount must be positive';
    end if;
    if p_sender_id is null or p_receiver_id is null or p_sender_id = p_receiver_id then
        raise exception 'invalid transfer parties';
    end if;

    update public.users
       set balance = coalesce(balance, 0) - p_amount
     where user_id = p_sender_id and coalesce(balance, 0) >= p_amount
    returning balance into v_sender_balance;
    if not found then
        raise exception 'insufficient balance';
    end if;

    insert into public.users (user_id, balance, debt)
    values (p_receiver_id, p_new_user_balance + p_amount, 0)
    on conflict (user_id) do update
        set balance = coalesce(public.users.balance, 0) + p_amount;

    insert into public.transaction_history (sender_id, receiver_id, amount, reason)
    values (p_sender_id, p_receiver_id, p_amount, '送金');

    return v_sender_balance;
end;
$$;
revoke all on function public.transfer_coins(text, text, bigint, bigint) from public, anon, authenticated;
grant execute on function public.transfer_coins(text, text, bigint, bigint) to anon, authenticated, service_role;
commit;
