-- Permit the Bot's public anon API key to call the bump/up RTA RPCs.
-- The functions remain SECURITY INVOKER; no table grants or RLS settings are changed here.
-- Re-running these GRANT statements is safe.
GRANT EXECUTE ON FUNCTION public.record_bump_rta_best(text, text, text, integer, timestamptz) TO anon;
GRANT EXECUTE ON FUNCTION public.get_bump_rta_global_ranking(text, integer) TO anon;
