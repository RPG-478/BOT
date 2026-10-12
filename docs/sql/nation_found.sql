-- 国づくり: 建国（/nation found）を 1 トランザクションで行う関数
-- 前提: docs/sql/nation.sql が適用済みであること
--
-- これまでは Bot から nation_guilds・nation_tiles・nation_players へ別々に insert していたため、
--   * 2 つのサーバーが同時に建国すると同じ首都マスを選び、片方の国に首都がなくなる
--   * 途中で失敗すると中途半端な国が残る
-- という問題があった。この関数はすべてを 1 トランザクションで行い、失敗したら全部取り消される。
--
-- エラー（Bot 側で日本語のメッセージに変換する）:
--   NATION_EXISTS     … このサーバーの国はもうある
--   ALREADY_IN_NATION … 建国する人がすでに別の国に所属している
--   NO_FREE_TILE      … 原点から距離 50 以内に空きマスがない
create or replace function public.nation_found(
    p_guild_id text,
    p_user_id  text
) returns table (capital_x int, capital_y int)
language plpgsql
set search_path = public
as $$
declare
    v_radius   constant int := 50;
    v_attempts constant int := 5;
    v_x int;
    v_y int;
    v_found boolean;
    v_r int;
    v_i int;
    v_attempt int;
begin
    -- 建国どうしを直列化する（トランザクション終了で自動的に解放）
    perform pg_advisory_xact_lock(hashtext('nation_found'));

    if exists (select 1 from public.nation_guilds g where g.guild_id = p_guild_id) then
        raise exception 'NATION_EXISTS: guild % already has a nation', p_guild_id;
    end if;
    if exists (select 1 from public.nation_players p
                where p.user_id = p_user_id and p.guild_id is not null) then
        raise exception 'ALREADY_IN_NATION: user % already belongs to a nation', p_user_id;
    end if;

    for v_attempt in 1..v_attempts loop
        -- 原点から近い順（チェビシェフ距離のリング、Python の spiral_coords と同じ順）に空きマスを探す
        v_found := false;
        if not exists (select 1 from public.nation_tiles t where t.x = 0 and t.y = 0) then
            v_x := 0; v_y := 0; v_found := true;
        end if;
        v_r := 1;
        while not v_found and v_r <= v_radius loop
            v_i := -v_r;
            while not v_found and v_i <= v_r loop
                if not exists (select 1 from public.nation_tiles t where t.x = v_i and t.y = -v_r) then
                    v_x := v_i; v_y := -v_r; v_found := true;
                elsif not exists (select 1 from public.nation_tiles t where t.x = v_i and t.y = v_r) then
                    v_x := v_i; v_y := v_r; v_found := true;
                end if;
                v_i := v_i + 1;
            end loop;
            v_i := -v_r + 1;
            while not v_found and v_i < v_r loop
                if not exists (select 1 from public.nation_tiles t where t.x = -v_r and t.y = v_i) then
                    v_x := -v_r; v_y := v_i; v_found := true;
                elsif not exists (select 1 from public.nation_tiles t where t.x = v_r and t.y = v_i) then
                    v_x := v_r; v_y := v_i; v_found := true;
                end if;
                v_i := v_i + 1;
            end loop;
            v_r := v_r + 1;
        end loop;

        if not v_found then
            raise exception 'NO_FREE_TILE: no free tile within % of the origin', v_radius;
        end if;

        begin
            insert into public.nation_tiles (x, y, owner_guild_id, tile_type, connected)
            values (v_x, v_y, p_guild_id, 'capital', true);
            exit;  -- 首都マスを確保できた
        exception when unique_violation then
            -- ロックの外から同じマスが埋まった場合など。次の空きマスで再試行
            if v_attempt = v_attempts then
                raise exception 'NO_FREE_TILE: capital tile kept colliding (% attempts)', v_attempts;
            end if;
        end;
    end loop;

    begin
        insert into public.nation_guilds (guild_id, capital_x, capital_y)
        values (p_guild_id, v_x, v_y);
    exception when unique_violation then
        raise exception 'NATION_EXISTS: guild % already has a nation', p_guild_id;
    end;

    insert into public.nation_players as p (user_id, guild_id, role, hunger)
    values (p_user_id, p_guild_id, 'king', 100)
    on conflict (user_id) do update
        set guild_id = excluded.guild_id, role = 'king', hunger = 100
        where p.guild_id is null;
    if not found then
        raise exception 'ALREADY_IN_NATION: user % already belongs to a nation', p_user_id;
    end if;

    return query select v_x, v_y;
end;
$$;

grant execute on function public.nation_found(text, text) to anon, authenticated;
