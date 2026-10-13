-- Separate bump and up RTA tracks without relabeling historical mixed records.
-- Existing combined records become 'legacy' and remain available for audit.
ALTER TABLE public.bump_rta_events
    ADD COLUMN IF NOT EXISTS event_type text NOT NULL DEFAULT 'legacy';
ALTER TABLE public.bump_rta_events
    DROP CONSTRAINT IF EXISTS bump_rta_events_event_type_check;
ALTER TABLE public.bump_rta_events
    ADD CONSTRAINT bump_rta_events_event_type_check CHECK (event_type IN ('bump', 'up', 'legacy'));

ALTER TABLE public.bump_rta_records
    ADD COLUMN IF NOT EXISTS event_type text NOT NULL DEFAULT 'legacy';
ALTER TABLE public.bump_rta_records
    DROP CONSTRAINT IF EXISTS bump_rta_records_event_type_check;
ALTER TABLE public.bump_rta_records
    ADD CONSTRAINT bump_rta_records_event_type_check CHECK (event_type IN ('bump', 'up', 'legacy'));
ALTER TABLE public.bump_rta_records DROP CONSTRAINT IF EXISTS bump_rta_records_pkey;
ALTER TABLE public.bump_rta_records
    ADD CONSTRAINT bump_rta_records_pkey PRIMARY KEY (guild_id, user_id, event_type);
CREATE INDEX IF NOT EXISTS bump_rta_records_type_ranking_idx
    ON public.bump_rta_records (guild_id, event_type, elapsed_ms ASC);
CREATE INDEX IF NOT EXISTS bump_rta_events_guild_type_time_idx
    ON public.bump_rta_events (guild_id, event_type, completed_at DESC);
CREATE INDEX IF NOT EXISTS bump_rta_events_user_type_time_idx
    ON public.bump_rta_events (user_id, event_type, elapsed_ms ASC);

ALTER TABLE public.bump_rta_pending
    ADD COLUMN IF NOT EXISTS event_type text NOT NULL DEFAULT 'legacy';
ALTER TABLE public.bump_rta_pending ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE public.bump_rta_pending
    DROP CONSTRAINT IF EXISTS bump_rta_pending_event_type_check;
ALTER TABLE public.bump_rta_pending
    ADD CONSTRAINT bump_rta_pending_event_type_check CHECK (event_type IN ('bump', 'up', 'legacy'));
ALTER TABLE public.bump_rta_pending DROP CONSTRAINT IF EXISTS bump_rta_pending_pkey;
ALTER TABLE public.bump_rta_pending
    ADD CONSTRAINT bump_rta_pending_pkey PRIMARY KEY (guild_id, event_type);

DROP FUNCTION IF EXISTS public.record_bump_rta_best(text, text, integer, timestamptz);
CREATE OR REPLACE FUNCTION public.record_bump_rta_best(
    p_guild_id text, p_user_id text, p_event_type text, p_elapsed_ms integer, p_completed_at timestamptz
) RETURNS void
LANGUAGE sql SECURITY INVOKER
AS $$
    INSERT INTO public.bump_rta_records (guild_id, user_id, event_type, elapsed_ms, completed_at)
    VALUES (p_guild_id, p_user_id, p_event_type, p_elapsed_ms, p_completed_at)
    ON CONFLICT (guild_id, user_id, event_type) DO UPDATE
      SET elapsed_ms = EXCLUDED.elapsed_ms, completed_at = EXCLUDED.completed_at
      WHERE EXCLUDED.elapsed_ms < public.bump_rta_records.elapsed_ms;
$$;
REVOKE ALL ON FUNCTION public.record_bump_rta_best(text, text, text, integer, timestamptz) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_bump_rta_best(text, text, text, integer, timestamptz) TO anon, service_role;

DROP FUNCTION IF EXISTS public.get_bump_rta_global_ranking(integer);
CREATE OR REPLACE FUNCTION public.get_bump_rta_global_ranking(p_event_type text, p_limit integer DEFAULT 10)
RETURNS TABLE(user_id text, elapsed_ms integer, attempts bigint)
LANGUAGE sql SECURITY INVOKER
AS $$
    SELECT e.user_id, min(e.elapsed_ms)::integer AS elapsed_ms, count(*)::bigint AS attempts
    FROM public.bump_rta_events AS e
    WHERE e.event_type = p_event_type
    GROUP BY e.user_id
    ORDER BY min(e.elapsed_ms) ASC
    LIMIT greatest(1, least(coalesce(p_limit, 10), 100));
$$;
REVOKE ALL ON FUNCTION public.get_bump_rta_global_ranking(text, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_bump_rta_global_ranking(text, integer) TO anon, service_role;
