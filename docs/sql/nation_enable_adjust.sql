-- 国づくり: nation_adjust を Bot（anon キー）から呼べるようにする
-- 前提: TYPETA #20（残高上書きの修正）がマージ済みであること
grant execute on function public.nation_adjust(text, bigint, int) to anon, authenticated;
