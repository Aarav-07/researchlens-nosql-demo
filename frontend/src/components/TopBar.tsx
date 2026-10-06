import { type FormEvent } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import type { SearchMode } from "../lib/types";
import { Button, Segmented } from "./primitives";

/* Masthead. Wordmark in Archivo, byline in mono, and a 2px ink rule closing the
   header the way a printed page closes its header block.

   Below `lg` the bar stacks instead of squeezing: one row cannot hold the
   wordmark, section nav, a usable field, the mode switch and two buttons. */

const MODES: { value: SearchMode; label: string; hint: string }[] = [
  {
    value: "hybrid",
    label: "Hybrid",
    hint: "Meaning and terms combined, with recency and citations",
  },
  { value: "semantic", label: "Meaning", hint: "Embedding similarity only" },
  { value: "keyword", label: "Terms", hint: "Weighted keyword match only" },
];

export function TopBar({
  query,
  onQueryChange,
  onSubmit,
  mode,
  onModeChange,
  view,
  onViewChange,
  onHome,
  busy,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit: () => void;
  mode: SearchMode;
  onModeChange: (mode: SearchMode) => void;
  view: "discover" | "library";
  onViewChange: (view: "discover" | "library") => void;
  onHome: () => void;
  busy: boolean;
}) {
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };

  const searchField = (
    <form onSubmit={handleSubmit} className="flex min-w-0 flex-1 items-center gap-2" role="search">
      <div className="flex h-9 min-w-0 flex-1 items-center gap-2 border border-line bg-surface px-3 focus-within:border-accent">
        <MagnifyingGlass size={14} weight="bold" className="shrink-0 text-ink-3" />
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Describe what you are looking for, for example multimodal learning for healthcare"
          aria-label="Search query"
          className="min-w-0 flex-1 bg-transparent text-[13px] text-ink placeholder:text-ink-3 focus:outline-none"
        />
      </div>
      <Button type="submit" variant="primary" disabled={busy || !query.trim()}>
        {busy ? "Searching" : "Search"}
      </Button>
    </form>
  );

  const nav = (
    <nav className="flex shrink-0 items-center border border-line bg-surface" aria-label="Sections">
      {(["discover", "library"] as const).map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => onViewChange(item)}
          className={`border-r border-line px-3 py-[7px] font-mono text-[10.5px] uppercase tracking-[0.1em] transition-colors duration-150 last:border-r-0 ${
            view === item ? "bg-ink text-[rgb(250_250_247)]" : "text-ink-3 hover:bg-surface-2 hover:text-ink"
          }`}
        >
          {item === "discover" ? "Discover" : "Library"}
        </button>
      ))}
    </nav>
  );

  const brand = (
    <button
      type="button"
      onClick={onHome}
      aria-label="ResearchLens home"
      className="flex shrink-0 items-baseline gap-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
    >
      <span className="text-[19px] font-extrabold leading-none tracking-[-0.02em] text-ink">
        ResearchLens
      </span>
      <span className="label-mono hidden text-ink-3 sm:inline">Literature intelligence</span>
    </button>
  );

  return (
    <header className="sticky top-0 z-20 border-b-2 border-[rgb(var(--c-ink))] bg-bg">
      <div className="mx-auto hidden h-[66px] max-w-[1520px] items-center gap-5 px-5 lg:flex">
        {brand}
        {nav}
        {searchField}
        <Segmented options={MODES} value={mode} onChange={onModeChange} />
      </div>

      <div className="mx-auto max-w-[1520px] space-y-2.5 px-4 py-3 lg:hidden">
        <div className="flex items-center justify-between gap-3">
          {brand}
          {nav}
        </div>
        {searchField}
        <Segmented options={MODES} value={mode} onChange={onModeChange} />
      </div>
    </header>
  );
}
