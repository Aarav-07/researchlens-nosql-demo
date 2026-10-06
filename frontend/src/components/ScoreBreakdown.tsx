import type { ScoreParts } from "../lib/types";

/* Ranking has to be legible, not a black box: each signal shows its own bar,
   all in the single accent at different opacities (one accent per page). */

const LABELS: { key: keyof ScoreParts; label: string; hint: string }[] = [
  { key: "semantic", label: "Meaning", hint: "Cosine similarity between your query and this paper" },
  { key: "keyword", label: "Terms", hint: "Weighted keyword match on title, abstract, authors, topics" },
  { key: "recency", label: "Recency", hint: "Exponential decay, 3-year half life" },
  { key: "citations", label: "Citations", hint: "Log-compressed citation count" },
];

const OPACITY: Record<string, string> = {
  semantic: "1",
  keyword: "0.72",
  recency: "0.46",
  citations: "0.32",
};

export function ScoreBreakdown({ parts }: { parts: ScoreParts }) {
  const present = LABELS.filter(({ key }) => typeof parts[key] === "number");
  if (present.length === 0) return null;

  return (
    <dl className="grid gap-1.5" aria-label="Why this paper ranked here">
      {present.map(({ key, label, hint }) => {
        const value = parts[key] as number;
        return (
          <div key={key} className="grid grid-cols-[66px_1fr_34px] items-center gap-2" title={hint}>
            <dt className="label-mono text-ink-3">{label}</dt>
            <dd className="h-[4px] overflow-hidden bg-surface-3">
              <div
                className="h-full bg-accent transition-[width] duration-300"
                style={{
                  width: `${Math.max(0, Math.min(1, value)) * 100}%`,
                  opacity: OPACITY[key] ?? "1",
                }}
              />
            </dd>
            <dd className="font-mono text-[11px] tabular-nums text-ink-2">{value.toFixed(2)}</dd>
          </div>
        );
      })}
    </dl>
  );
}
