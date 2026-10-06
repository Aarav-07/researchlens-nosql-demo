import type { Author, Paper } from "./types";

export function authorLine(authors: Author[], max = 3): string {
  if (authors.length === 0) return "Unknown authors";
  const names = authors.slice(0, max).map((a) => shortName(a.name));
  if (authors.length > max) names.push(`+${authors.length - max}`);
  return names.join(", ");
}

/** "Yongfeng Zhang" stays; very long author strings get trimmed to initials. */
function shortName(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length < 3) return name;
  return `${parts[0]} ${parts[parts.length - 1]}`;
}

export function yearOf(paper: Paper): string {
  if (paper.year) return String(paper.year);
  if (paper.published_date) return paper.published_date.slice(0, 4);
  return "n.d.";
}

export function formatDate(value: string | null): string {
  if (!value) return "No date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function compactNumber(value: number): string {
  if (value < 1000) return String(value);
  if (value < 10_000) return `${(value / 1000).toFixed(1)}k`;
  return `${Math.round(value / 1000)}k`;
}

export function sourceLabel(source: string): string {
  if (source === "arxiv") return "arXiv";
  if (source === "openalex") return "OpenAlex";
  return source;
}

export function paperLink(paper: Paper): string | null {
  return paper.pdf_url ?? paper.url ?? (paper.doi ? `https://doi.org/${paper.doi}` : null);
}

export function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max).trimEnd()}...`;
}
