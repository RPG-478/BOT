-- 提案のみ（本番にはまだ適用していません。Bot のコードはこの関数がなくても動きます）。
-- /pay の送金を 1 回のトランザクションで行う関数の案です。適用する場合は Luna に依頼し、
-- 適用後に cogs/wallet.py から rpc('transfer_coins', ...) を呼ぶよう切り替えます。

create or replace function public.transfer_coins(
    p_sender_id text,
    p_receiver_id text,
    p_amount bigint,
    p_new_user_balance bigint default 10
) returns bigint            -- 送金後の送り手の残高。残高不足なら例外
language plpgsql
as $$
declare
    v_sender_balance bigint;
begin
    if p_amount <= 0 then
        raise exception 'amount must be positive';
    end if;
    if p_sender_id = p_receiver_id then
        raise exception 'cannot pay yourself';
    end if;

    update public.users
       set balance = balance - p_amount
     where user_id = p_sender_id and balance >= p_amount
    returning balance into v_sender_balance;
    if not found then
        raise exception 'insufficient balance';
    end if;

    insert into public.users (user_id, balance, debt)
    values (p_receiver_id, p_new_user_balance + p_amount, 0)
    on conflict (user_id) do update set balance = public.users.balance + p_amount;

    insert into public.transaction_history (sender_id, receiver_id, amount, reason)
    values (p_sender_id, p_receiver_id, p_amount, '送金');

    return v_sender_balance;
end;
$$;
