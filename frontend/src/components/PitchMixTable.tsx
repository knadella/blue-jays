import type { PitchTypeRow } from "../api";

interface PitchMixTableProps {
  title: string;
  subtitle: string;
  rows: PitchTypeRow[];
}

function pct(x: number | null | undefined) {
  if (x == null || Number.isNaN(x)) {
    return "—";
  }
  return `${(x * 100).toFixed(1)}%`;
}

function num3(x: number | null | undefined) {
  if (x == null || Number.isNaN(x)) {
    return "—";
  }
  return x.toFixed(3);
}

export function PitchMixTable({ title, subtitle, rows }: PitchMixTableProps) {
  if (rows.length === 0) {
    return (
      <div className="pitch-mix-block">
        <h3 className="pitch-mix-title">{title}</h3>
        <p className="pitch-mix-sub">{subtitle}</p>
        <p className="pitch-mix-empty">Not enough pitches in this window to break down by type.</p>
      </div>
    );
  }

  return (
    <div className="pitch-mix-block">
      <h3 className="pitch-mix-title">{title}</h3>
      <p className="pitch-mix-sub">{subtitle}</p>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Pitch</th>
              <th className="num">#</th>
              <th className="num">Swing</th>
              <th className="num">Whiff</th>
              <th className="num">Chase</th>
              <th className="num">xwOBAcon</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, idx) => (
              <tr key={`${r.pitch_type}-${idx}`}>
                <td>
                  <span className="pitch-code">{r.pitch_type}</span>
                  <span className="pitch-name">{r.pitch_label}</span>
                </td>
                <td className="num">{r.pitches}</td>
                <td className="num">{pct(r.swing_rate)}</td>
                <td className="num">{pct(r.whiff_rate)}</td>
                <td className="num">{pct(r.chase_rate)}</td>
                <td className="num">{num3(r.xwoba_on_contact)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
