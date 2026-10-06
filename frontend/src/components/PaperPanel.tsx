import { useEffect, useState } from "react";
import { ArrowSquareOut, GraphIcon, X } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { api, ApiError } from "../lib/api";
import {
  authorLine,
  compactNumber,
  formatDate,
  paperLink,
  sourceLabel,
  yearOf,
} from "../lib/format";
import type { Paper, SearchHit } from "../lib/types";
import { Button, Chip, ErrorNote, Skeleton } from "./primitives";
import { PdfReader } from "./PdfReader";
import { PdfDownloadButton } from "./PdfDownloadButton";

/* Two tabs, because a reader does two things with a candidate paper: judge it,
   then read it. Both happen without leaving the page. */

type Tab = "overview" | "read";

export function PaperPanel({
  paper,
  onClose,
  onSelect,
  expanded,
  onToggleExpand,
}: {
  paper: Paper;
  onClose: () => void;
  onSelect: (paper: Paper) => void;
  expanded: boolean;
  onToggleExpand: () => void;
}) {
  const reduce = useReducedMotion();
  const [tab, setTab] = useState<Tab>("overview");
  const [related, setRelated] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const external = paperLink(paper);

  useEffect(() => {
    let active = true;
    setRelated(null);
    setError(null);
    api
      .similar(paper.id, 6)
      .then((hits) => {
        if (active) setRelated(hits);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof ApiError ? err.message : "Could not load related papers.");
        }
      });
    return () => {
      active = false;
    };
  }, [paper.id]);

  // A different paper starts on the overview again.
  useEffect(() => setTab("overview"), [paper.id]);

  return (
    <motion.aside
      initial={reduce ? false : { opacity: 0, x: 10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
      className="flex h-full min-h-0 flex-col overflow-hidden border border-line bg-surface"
      aria-label="Paper detail"
    >
      <header className="border-b-2 border-[rgb(var(--c-ink))] px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="label-mono text-accent">
              {sourceLabel(paper.source)} / {yearOf(paper)}
            </p>
            <h2 className="mt-1.5 text-[18px] font-bold leading-tight tracking-[-0.015em] text-ink">
              {paper.title}
            </h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close detail panel">
            <X size={15} weight="bold" />
          </Button>
        </div>

        <div className="mt-3 flex items-center gap-1" role="tablist" aria-label="Paper views">
          {(["overview", "read"] as const).map((item) => (
            <button
              key={item}
              role="tab"
              type="button"
              aria-selected={tab === item}
              onClick={() => setTab(item)}
              className={`border border-line px-3 py-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em] transition-colors duration-150 ${
                tab === item
                  ? "border-accent bg-accent text-accent-ink"
                  : "text-ink-3 hover:border-line-strong hover:text-ink"
              }`}
            >
              {item === "overview" ? "Overview" : "Read PDF"}
            </button>
          ))}
        </div>
      </header>

      {tab === "read" ? (
        <PdfReader paper={paper} expanded={expanded} onToggleExpand={onToggleExpand} />
      ) : (
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
          <div className="space-y-2.5">
            <p className="prose-serif text-ink-2">{authorLine(paper.authors, 8)}</p>
            <div className="flex flex-wrap items-center gap-1.5">
              {paper.venue ? <Chip>{paper.venue}</Chip> : null}
              <Chip title="Publication date">{formatDate(paper.published_date)}</Chip>
              {paper.citation_count > 0 ? (
                <Chip title={`${paper.citation_count.toLocaleString()} citations`}>
                  {compactNumber(paper.citation_count)} citations
                </Chip>
              ) : null}
              {paper.doi ? <Chip title={`DOI ${paper.doi}`}>DOI</Chip> : null}
            </div>
            <div className="flex flex-wrap items-center gap-2 pt-0.5">
              <Button variant="primary" size="sm" onClick={() => setTab("read")}>
                Read here
              </Button>
              <PdfDownloadButton paperId={paper.id} />
              {external ? (
                <a href={external} target="_blank" rel="noreferrer noopener">
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<ArrowSquareOut size={14} weight="bold" />}
                  >
                    Source
                  </Button>
                </a>
              ) : null}
            </div>
          </div>

          {paper.abstract ? (
            <div>
              <h3 className="label-mono mb-2 border-b border-line pb-1.5 text-ink-3">Abstract</h3>
              <p className="prose-serif max-w-[66ch] text-ink-2">{paper.abstract}</p>
            </div>
          ) : null}

          {paper.topics.length > 0 ? (
            <div>
              <h3 className="label-mono mb-2 border-b border-line pb-1.5 text-ink-3">Topics</h3>
              <div className="flex flex-wrap gap-1.5">
                {paper.topics.map((topic) => (
                  <Chip key={topic}>{topic}</Chip>
                ))}
              </div>
            </div>
          ) : null}

          <div>
            <h3 className="label-mono mb-2 flex items-center gap-1.5 border-b border-line pb-1.5 text-ink-3">
              <GraphIcon size={12} weight="bold" className="text-accent" />
              Related papers
            </h3>

            {error ? <ErrorNote message={error} /> : null}

            {!error && related === null ? (
              <div className="space-y-3">
                {[0, 1, 2].map((key) => (
                  <div key={key} className="space-y-1.5">
                    <Skeleton className="h-[13px] w-[72%]" />
                    <Skeleton className="h-[11px] w-[38%]" />
                  </div>
                ))}
              </div>
            ) : null}

            {related !== null && related.length === 0 ? (
              <p className="prose-serif text-ink-3">
                No neighbours yet. Related papers appear once more work in this area has been
                ingested.
              </p>
            ) : null}

            {related && related.length > 0 ? (
              <ul className="divide-y divide-[var(--border)]">
                {related.map((hit) => (
                  <li key={hit.paper.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(hit.paper)}
                      className="w-full py-2.5 text-left transition-colors duration-150 hover:bg-surface-2"
                    >
                      <p className="text-[13.5px] font-semibold leading-snug text-ink">
                        {hit.paper.title}
                      </p>
                      <p className="label-mono mt-1 flex items-center gap-2 text-ink-3">
                        <span className="tabular-nums text-accent">{hit.score.toFixed(2)}</span>
                        <span>
                          {yearOf(hit.paper)} / {sourceLabel(hit.paper.source)}
                        </span>
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
      )}
    </motion.aside>
  );
}
