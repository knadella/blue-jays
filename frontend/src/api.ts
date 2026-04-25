/** In dev, default to same-origin so Vite can proxy `/api` → FastAPI (no CORS, no prod URL). */
const API_BASE =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ??
  (import.meta.env.DEV ? "" : "http://localhost:8000");

const _viteApiUrl = (import.meta.env.VITE_API_URL as string | undefined)?.trim();
if (import.meta.env.DEV && _viteApiUrl) {
  const u = _viteApiUrl.replace(/\/$/, "");
  const local =
    u.startsWith("http://127.0.0.1:") ||
    u.startsWith("http://localhost:") ||
    u === "http://127.0.0.1" ||
    u === "http://localhost";
  if (!local) {
    console.warn(
      "[mlb] VITE_API_URL is set to a non-loopback URL in dev. The browser will skip the Vite /api proxy (hangs, CORS, or wrong data). Remove VITE_API_URL from repo-root .env / .env.local for local work.",
      u,
    );
  }
}

export interface PitchTypeRow {
  pitch_type: string;
  pitch_label: string;
  pitches: number;
  swing_rate: number;
  whiff_rate: number | null;
  chase_rate: number | null;
  xwoba_on_contact: number | null;
}

export interface WeekSideMetrics {
  pitches: number;
  plate_appearances: number;
  swing_rate: number | null;
  whiff_rate: number | null;
  zone_swing_rate: number | null;
  chase_rate: number | null;
  contact_rate: number | null;
  called_strike_rate: number | null;
  xwoba_on_contact: number | null;
  xwoba: number | null;
  avg_exit_velo_bip: number | null;
  hard_hit_rate: number | null;
  barrel_rate: number | null;
  avg_launch_angle_bip: number | null;
  groundball_rate: number | null;
  flyball_rate: number | null;
  popup_rate: number | null;
  avg_iso_value_bip: number | null;
  if_standard_pct: number | null;
  if_strategic_pct: number | null;
  of_strategic_pct: number | null;
}

export interface WeeklyBucket {
  week_key: string;
  week_start: string;
  week_end: string;
  offense: WeekSideMetrics;
  run_prevention: WeekSideMetrics;
  hitting_vs_pitch_types: PitchTypeRow[];
  pitching_pitch_types: PitchTypeRow[];
}

export interface OffenseMonthLeagueShape {
  month: number;
  xwoba_pct: number | null;
  chase_pct: number | null;
  whiff_pct: number | null;
  hard_hit_pct: number | null;
  xwoba_rank: number | null;
  barrel_rank: number | null;
  chase_rank: number | null;
  whiff_rank: number | null;
  p_xwoba_rank: number | null;
  p_barrel_rank: number | null;
  p_chase_rank: number | null;
  p_whiff_rank: number | null;
}

export interface ChaseZoneCell {
  x: number;
  y: number;
  n: number;
  sw: number;
  iz: number;
}

export interface ChaseZoneMonth {
  month: number;
  cells: ChaseZoneCell[];
}

export interface ChaseZoneGrid {
  sz_top: number;
  sz_bot: number;
  zone_width: number;
  nx: number;
  ny: number;
  x_range: [number, number];
  y_range: [number, number];
  months: ChaseZoneMonth[];
}

export interface WhiffZoneCell {
  x: number; y: number; n: number; wh: number;
}
export interface WhiffZoneMonth {
  month: number; cells: WhiffZoneCell[];
}
export interface WhiffZoneGrid {
  sz_top: number; sz_bot: number; zone_width: number;
  nx: number; ny: number;
  x_range: [number, number]; y_range: [number, number];
  months: WhiffZoneMonth[];
}

export interface BarrelCell {
  x: number; y: number; n: number; brl: number;
}
export interface BarrelMonth {
  month: number; cells: BarrelCell[];
}
export interface BarrelGrid {
  nx: number; ny: number;
  ev_range: [number, number]; la_range: [number, number];
  months: BarrelMonth[];
}

export interface SprayCell {
  x: number; y: number; n: number; xw: number;
}
export interface SprayMonth {
  month: number; cells: SprayCell[];
}
export interface SprayGrid {
  nx: number; ny: number;
  x_range: [number, number]; y_range: [number, number];
  months: SprayMonth[];
}

export interface WeeklyActualsResponse {
  season: number;
  team: string;
  team_abbrev: string;
  wins: number;
  losses: number;
  runs_per_game: number;
  runs_allowed_per_game: number;
  run_differential: number;
  streak: string;
  weeks: WeeklyBucket[];
  statcast_rows: number;
  data_through: string | null;
  generated_at: string;
  note: string | null;
  chase_zone_grid?: ChaseZoneGrid;
  whiff_zone_grid?: WhiffZoneGrid;
  barrel_grid?: BarrelGrid;
  spray_grid?: SprayGrid;
  pitching_chase_zone_grid?: ChaseZoneGrid;
  pitching_whiff_zone_grid?: WhiffZoneGrid;
  pitching_barrel_grid?: BarrelGrid;
  pitching_spray_grid?: SprayGrid;
}

async function fetchSampleWeeklyActuals(): Promise<WeeklyActualsResponse> {
  const base = import.meta.env.BASE_URL;
  const response = await fetch(`${base}sample-weekly-actuals.json`);
  if (!response.ok) {
    throw new Error("Sample weekly data not found.");
  }
  return response.json();
}

export async function fetchWeeklyActuals(
  season: number,
  signal?: AbortSignal,
): Promise<WeeklyActualsResponse> {
  const params = new URLSearchParams({ season: String(season) });
  const url = `${API_BASE}/api/weekly-actuals?${params.toString()}`;
  try {
    const response = await fetch(url, { signal });
    if (!response.ok) {
      throw new Error(`Weekly data HTTP ${response.status}. Is the API running on 127.0.0.1:8000?`);
    }
    return response.json();
  } catch (e: unknown) {
    const name = e && typeof e === "object" && "name" in e ? String((e as { name: string }).name) : "";
    if (name === "AbortError") {
      throw e;
    }
    console.warn("API unavailable, using sample weekly-actuals data.");
    return fetchSampleWeeklyActuals();
  }
}
