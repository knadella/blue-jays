// Vite injects the configured `base` path (e.g. "/mlb/" on GitHub Pages).
// We prepend it to logo filenames so they resolve correctly on any host.
const BASE = import.meta.env.BASE_URL; // always ends with "/"

const TEAM_METADATA = {
  "Arizona Diamondbacks": { abbrev: "ARI", color: "#A71930", logo: `${BASE}team-logos/ari_l.svg` },
  "Atlanta Braves": { abbrev: "ATL", color: "#CE1141", logo: `${BASE}team-logos/atl_l.svg` },
  "Baltimore Orioles": { abbrev: "BAL", color: "#DF4601", logo: `${BASE}team-logos/bal_l.svg` },
  "Boston Red Sox": { abbrev: "BOS", color: "#BD3039", logo: `${BASE}team-logos/bos_l.svg` },
  "Chicago Cubs": { abbrev: "CHC", color: "#0E3386", logo: `${BASE}team-logos/chc_l.svg` },
  "Chicago White Sox": { abbrev: "CHW", color: "#27251F", logo: `${BASE}team-logos/cws_l.svg` },
  "Cincinnati Reds": { abbrev: "CIN", color: "#C6011F", logo: `${BASE}team-logos/cin_l.svg` },
  "Cleveland Guardians": { abbrev: "CLE", color: "#00385D", logo: `${BASE}team-logos/cle_l.svg` },
  "Colorado Rockies": { abbrev: "COL", color: "#333366", logo: `${BASE}team-logos/col_l.svg` },
  "Detroit Tigers": { abbrev: "DET", color: "#0C2340", logo: `${BASE}team-logos/det_l.svg` },
  "Houston Astros": { abbrev: "HOU", color: "#002D62", logo: `${BASE}team-logos/hou_l.svg` },
  "Kansas City Royals": { abbrev: "KC", color: "#004687", logo: `${BASE}team-logos/kc_l.svg` },
  "Los Angeles Angels": { abbrev: "LAA", color: "#BA0021", logo: `${BASE}team-logos/laa_l.svg` },
  "Los Angeles Dodgers": { abbrev: "LAD", color: "#005A9C", logo: `${BASE}team-logos/lad_l.svg` },
  "Miami Marlins": { abbrev: "MIA", color: "#00A3E0", logo: `${BASE}team-logos/mia_l.svg` },
  "Milwaukee Brewers": { abbrev: "MIL", color: "#FFC52F", logo: `${BASE}team-logos/mil_l.svg` },
  "Minnesota Twins": { abbrev: "MIN", color: "#002B5C", logo: `${BASE}team-logos/min_l.svg` },
  "New York Mets": { abbrev: "NYM", color: "#002D72", logo: `${BASE}team-logos/nym_l.svg` },
  "New York Yankees": { abbrev: "NYY", color: "#003087", logo: `${BASE}team-logos/nyy_l.svg` },
  "Oakland Athletics": { abbrev: "OAK", color: "#003831", logo: `${BASE}team-logos/oak_l.svg` },
  "Philadelphia Phillies": { abbrev: "PHI", color: "#E81828", logo: `${BASE}team-logos/phi_l.svg` },
  "Pittsburgh Pirates": { abbrev: "PIT", color: "#FDB827", logo: `${BASE}team-logos/pit_l.svg` },
  "San Diego Padres": { abbrev: "SD", color: "#2F241D", logo: `${BASE}team-logos/sd_l.svg` },
  "San Francisco Giants": { abbrev: "SF", color: "#FD5A1E", logo: `${BASE}team-logos/sf_l.svg` },
  "Seattle Mariners": { abbrev: "SEA", color: "#0C2C56", logo: `${BASE}team-logos/sea_l.svg` },
  "St. Louis Cardinals": { abbrev: "STL", color: "#C41E3A", logo: `${BASE}team-logos/stl_l.svg` },
  "Tampa Bay Rays": { abbrev: "TB", color: "#092C5C", logo: `${BASE}team-logos/tb_l.svg` },
  "Texas Rangers": { abbrev: "TEX", color: "#003278", logo: `${BASE}team-logos/tex_l.svg` },
  "Toronto Blue Jays": { abbrev: "TOR", color: "#134A8E", logo: `${BASE}team-logos/tor_l.svg` },
  "Washington Nationals": { abbrev: "WSH", color: "#AB0003", logo: `${BASE}team-logos/wsh_l.svg` },
} as const;

export function getTeamAbbrev(team: string): string {
  return TEAM_METADATA[team as keyof typeof TEAM_METADATA]?.abbrev ?? team.slice(0, 3).toUpperCase();
}

export function getTeamColor(team: string): string {
  return TEAM_METADATA[team as keyof typeof TEAM_METADATA]?.color ?? "#0d5c75";
}

export function getTeamLogoPath(team: string): string | null {
  return TEAM_METADATA[team as keyof typeof TEAM_METADATA]?.logo ?? null;
}

export { TEAM_METADATA };
