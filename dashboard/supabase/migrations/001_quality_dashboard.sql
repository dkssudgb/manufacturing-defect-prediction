-- Supabase production schema corresponding to the local SQLite demo repository.
-- Run this migration after creating Auth users. The frontend currently uses the
-- local demo adapter; these tables are ready for the next Supabase integration step.

create type public.app_role as enum ('worker', 'manager', 'analyst');
create type public.inspection_status as enum ('검사 대기', '검사 중', '검사 완료');

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  worker_code text not null unique,
  name text not null,
  role public.app_role not null default 'worker',
  created_at timestamptz not null default now()
);

create table public.predictions (
  id bigint generated always as identity primary key,
  record_id text not null unique,
  produced_at timestamptz,
  part text,
  part_no text,
  part_name text not null,
  equip_cd text,
  equip_name text,
  supported boolean not null,
  unsupported_reason text,
  defect_probability double precision check (defect_probability between 0 and 1),
  predicted_label smallint check (predicted_label in (0, 1)),
  prediction text not null,
  threshold double precision not null check (threshold between 0 and 1),
  model_version text not null,
  inspection_status public.inspection_status,
  process_values jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.prediction_events (
  id bigint generated always as identity primary key,
  record_id text not null references public.predictions(record_id) on delete cascade,
  produced_at timestamptz,
  part text,
  part_name text not null,
  equip_cd text,
  equip_name text,
  supported boolean not null,
  defect_probability double precision check (defect_probability between 0 and 1),
  predicted_label smallint check (predicted_label in (0, 1)),
  prediction text not null,
  threshold double precision not null check (threshold between 0 and 1),
  model_version text not null,
  replay_sequence bigint,
  replay_cycle integer,
  created_at timestamptz not null default now()
);

create table public.inspections (
  id bigint generated always as identity primary key,
  prediction_id bigint not null unique references public.predictions(id) on delete cascade,
  record_id text not null unique,
  worker_id uuid not null references public.profiles(user_id),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  actual_label text check (actual_label in ('정상', '불량')),
  defect_type text,
  checked_items jsonb not null default '[]'::jsonb,
  action text,
  additional_inspection boolean not null default false,
  evaluation text check (evaluation in ('TP', 'FP', 'FN', 'TN')),
  constraint defect_type_required check (actual_label <> '불량' or defect_type is not null)
);

create table public.threshold_history (
  id bigint generated always as identity primary key,
  previous_threshold double precision not null check (previous_threshold between 0 and 1),
  new_threshold double precision not null check (new_threshold between 0 and 1),
  changed_by uuid not null references public.profiles(user_id),
  reason text not null,
  changed_at timestamptz not null default now()
);

create index predictions_created_at_idx on public.predictions(created_at desc);
create index predictions_inspection_status_idx on public.predictions(inspection_status);
create index predictions_part_idx on public.predictions(part);
create index prediction_events_created_at_idx on public.prediction_events(created_at desc);
create index prediction_events_equipment_idx on public.prediction_events(equip_cd, id desc);
create index inspections_completed_at_idx on public.inspections(completed_at desc);

alter table public.profiles enable row level security;
alter table public.predictions enable row level security;
alter table public.prediction_events enable row level security;
alter table public.inspections enable row level security;
alter table public.threshold_history enable row level security;

create policy "authenticated users read profiles"
  on public.profiles for select to authenticated using (true);
create policy "users read predictions"
  on public.predictions for select to authenticated using (true);
create policy "users read prediction events"
  on public.prediction_events for select to authenticated using (true);
create policy "users read inspections"
  on public.inspections for select to authenticated using (true);
create policy "worker starts own inspection"
  on public.inspections for insert to authenticated with check (worker_id = auth.uid());
create policy "worker updates own inspection or manager updates any"
  on public.inspections for update to authenticated
  using (
    worker_id = auth.uid() or exists (
      select 1 from public.profiles p where p.user_id = auth.uid() and p.role = 'manager'
    )
  );
create policy "users read threshold history"
  on public.threshold_history for select to authenticated using (true);
create policy "manager or analyst changes threshold"
  on public.threshold_history for insert to authenticated
  with check (
    changed_by = auth.uid() and exists (
      select 1 from public.profiles p
      where p.user_id = auth.uid() and p.role in ('manager', 'analyst')
    )
  );
