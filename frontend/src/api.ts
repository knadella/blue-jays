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

export async function fetchToday(signal?: AbortSignal): Promise<TodayResponse> {
  const url = `${API_BASE}/api/today`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Today HTTP ${response.status}. Is the API running on 127.0.0.1:8000?`);
  }
  return response.json();
}


// ---------------------------------------------------------------------------
// Players (season-long net contribution)
// ---------------------------------------------------------------------------

export interface GameRef {
  game_pk: number;
  game_date: string;
  opp_abbr: string;
  jays_won: boolean;
  wpa: number;
}

export interface BatterCard {
  player_id: number;
  name: string;
  wpa: number;
  games: number;
  pa: number;
  rbi: number;
  best_game: GameRef | null;
  worst_game: GameRef | null;
}

export interface PitcherCard {
  player_id: number;
  name: string;
  wpa: number;
  games: number;
  starts: number;
  bf: number;
  pitches: number;
  best_game: GameRef | null;
  worst_game: GameRef | null;
}

export interface PlayersResponse {
  season: number;
  games_included: number;
  last_game_date: string | null;
  batters: BatterCard[];
  pitchers: PitcherCard[];
  generated_at: string;
}

export async function fetchPlayers(season: number, signal?: AbortSignal): Promise<PlayersResponse> {
  const url = `${API_BASE}/api/players?season=${season}`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Players HTTP ${response.status}. Is the API running on 127.0.0.1:8000?`);
  }
  return response.json();
}
