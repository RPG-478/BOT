-- DDDの戦闘特性。自由入力のcharacteristicとは分離し、許可済みIDだけを保存する。
alter table public.monsters
    add column if not exists trait_id text not null default 'none';

update public.monsters
set trait_id = 'none'
where trait_id is null
   or trait_id not in ('none', 'regen', 'guard', 'valor', 'focus');

alter table public.monsters
    drop constraint if exists monsters_trait_id_check;

alter table public.monsters
    add constraint monsters_trait_id_check
    check (trait_id in ('none', 'regen', 'guard', 'valor', 'focus'));
