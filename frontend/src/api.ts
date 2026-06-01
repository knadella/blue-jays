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


// ---------------------------------------------------------------------------
// Today (post-game story)
// ---------------------------------------------------------------------------

export interface TodayHeader {
  game_pk: number;
  game_date: string;
  venue: string;
  home_team: string;
  home_abbr: string;
  away_team: string;
  away_abbr: string;
  home_score: number;
  away_score: number;
  jays_won: boolean;
  jays_score: number;
  opp_score: number;
}

export interface WEPoint {
  play_index: number;
  inning: number;
  half: "T" | "B";
  we_jays: number;
}

export interface LeveragePlay {
  play_index: number;
  inning: number;
  half: "T" | "B";
  score_before: string;
  description: string;
  wpa_jays: number;
  we_before_jays: number;
  we_after_jays: number;
  outs_before: number;
  bases_before: string;
  jays_diff_before: number;
  why: string;
}

export interface Contributor {
  player_id: number;
  name: string;
  wpa: number;
  pa: number;
  rbi: number;
  best_play: string | null;
  worst_play: string | null;
}

export interface PitcherLine {
  player_id: number;
  name: string;
  role: "starter" | "relief";
  ip: string;
  h: number;
  r: number;
  er: number;
  k: number;
  bb: number;
  pitches: number;
  note: string;
}

export interface TodayResponse {
  header: TodayHeader;
  we_trajectory: WEPoint[];
  leverage_plays: LeveragePlay[];
  top_contributors: Contributor[];
  negative_contributors: Contributor[];
  starter: PitcherLine | null;
  relievers: PitcherLine[];
  bullpen_pitches: number;
  opp_starter: PitcherLine | null;
  we_table_meta: { seasons?: number[]; n_states?: number; n_observations?: number };
  generated_at: string;
}

export async function fetchToday(team: string, signal?: AbortSignal): Promise<TodayResponse> {
  const url = `${API_BASE}/api/today?team=${encodeURIComponent(team)}`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Today HTTP ${response.status}. Is the API running on 127.0.0.1:8000?`);
  }
  return response.json();
}


// ---------------------------------------------------------------------------
// Players (season-long net contribution)
// ---------------------------------------------------------------------------

export interface BatterWindow {
  wpa: number;
  games: number;
  pa: number;
  rbi: number;
  ab: number;
  h: number;
  hr: number;
  so: number;
  bb: number;
  avg: number | null;
  obp: number | null;
  slg: number | null;
}

export interface PitcherWindow {
  wpa: number;
  games: number;
  starts: number;
  bf: number;
  pitches: number;
  ip: string;
  er: number;
  so: number;
  bb: number;
  era: number | null;
}

export interface BatterCard {
  player_id: number;
  name: string;
  wpa: number;
  games: number;
  pa: number;
  rbi: number;
  ab: number;
  h: number;
  hr: number;
  so: number;
  bb: number;
  avg: number | null;
  obp: number | null;
  slg: number | null;
  recent30: BatterWindow | null;
  spark_30: number[];
}

export interface PitcherCard {
  player_id: number;
  name: string;
  wpa: number;
  games: number;
  starts: number;
  bf: number;
  pitches: number;
  ip: string;
  er: number;
  so: number;
  bb: number;
  era: number | null;
  recent30: PitcherWindow | null;
  spark_30: number[];
}

export interface PlayersResponse {
  season: number;
  games_included: number;
  last_game_date: string | null;
  batters: BatterCard[];
  pitchers: PitcherCard[];
  generated_at: string;
}

export async function fetchPlayers(
  season: number,
  team: string,
  signal?: AbortSignal,
): Promise<PlayersResponse> {
  const url = `${API_BASE}/api/players?season=${season}&team=${encodeURIComponent(team)}`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Players HTTP ${response.status}. Is the API running on 127.0.0.1:8000?`);
  }
  return response.json();
}


// ---------------------------------------------------------------------------
// Standings (division table + momentum + quality of competition)
// ---------------------------------------------------------------------------

export interface TeamStanding {
  team: string;
  abbrev: string;
  w: number;
  l: number;
  pct: number;
  gb: number;
  streak: string;
  last10: string;
  last10_results: string[];
  run_diff: number;
  is_favorite: boolean;
}

export interface QualityRecord {
  label: string;
  w: number;
  l: number;
  pct: number;
}

export interface StandingsResponse {
  season: number;
  division: string;
  last_game_date: string | null;
  teams: TeamStanding[];
  favorite_streak: string;
  favorite_last10: string;
  favorite_run_diff: number;
  favorite_results: string[];
  vs_winning: QualityRecord;
  vs_losing: QualityRecord;
  generated_at: string;
}

export async function fetchStandings(
  season: number,
  team: string,
  signal?: AbortSignal,
): Promise<StandingsResponse> {
  const url = `${API_BASE}/api/standings?season=${season}&team=${encodeURIComponent(team)}`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Standings HTTP ${response.status}. Is the API running on 127.0.0.1:8000?`);
  }
  return response.json();
}


// ---------------------------------------------------------------------------
// Players client cache — stale-while-revalidate + prefetch.
//
// Players data changes at most once a day, so we render whatever we have
// instantly (memory → localStorage) and revalidate in the background. Prefetch
// warms it before the user opens the tab, making the switch feel instant.
// ---------------------------------------------------------------------------

const PLAYERS_CACHE_PREFIX = "mlb.players.";
const playersMem = new Map<string, PlayersResponse>();
const playersInflight = new Map<string, Promise<PlayersResponse>>();

function playersKey(season: number, team: string): string {
  return `${team}:${season}`;
}

/** Synchronous read for instant first paint: memory first, then localStorage. */
export function getCachedPlayers(season: number, team: string): PlayersResponse | null {
  const k = playersKey(season, team);
  const mem = playersMem.get(k);
  if (mem) return mem;
  try {
    const raw = localStorage.getItem(PLAYERS_CACHE_PREFIX + k);
    if (raw) {
      const parsed = JSON.parse(raw) as PlayersResponse;
      playersMem.set(k, parsed);
      return parsed;
    }
  } catch {
    /* localStorage unavailable or corrupt — ignore */
  }
  return null;
}

function setCachedPlayers(season: number, team: string, data: PlayersResponse): void {
  const k = playersKey(season, team);
  playersMem.set(k, data);
  try {
    localStorage.setItem(PLAYERS_CACHE_PREFIX + k, JSON.stringify(data));
  } catch {
    /* quota/private mode — memory cache still works */
  }
}

/** Fetch + cache, de-duping concurrent requests for the same team/season. */
export function loadPlayers(season: number, team: string): Promise<PlayersResponse> {
  const k = playersKey(season, team);
  const existing = playersInflight.get(k);
  if (existing) return existing;
  const p = fetchPlayers(season, team)
    .then((d) => {
      setCachedPlayers(season, team, d);
      return d;
    })
    .finally(() => {
      playersInflight.delete(k);
    });
  playersInflight.set(k, p);
  return p;
}

/** Fire-and-forget warm-up; safe to call repeatedly. */
export function prefetchPlayers(season: number, team: string): void {
  if (playersMem.has(playersKey(season, team))) return;
  loadPlayers(season, team).catch(() => {
    /* prefetch failures surface on the real load */
  });
}
