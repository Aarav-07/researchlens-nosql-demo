import {
  ArrowSquareOut,
  Clock,
  Compass,
  Path,
  Sparkle,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import { authorLine, compactNumber, paperLink, sourceLabel, truncate, yearOf } from "../lib/format";
import type { Paper, RecommendationGroup } from "../lib/types";
import { PdfDownloadButton } from "./PdfDownloadButton";

/* Grouped view, set like a catalogue.

   Competing tools either dump one long ranked list or open with a citation
   graph; both leave the reader deciding what each result is for. Here each
   group states its job in a mono standfirst, and each entry states why it sits
   in that group. Entries are ruled cells, not floating cards. */

const GROUP_ICON: Record<string, ReactNode> = {
  closest: <Compass size={12} weight="bold" />,
  recent: <Clock size={12} weight="bold" />,
  foundational: <Path size={12} weight="bold" />,
  adjacent: <Sparkle size={12} weight="bold" />,
};

export function RecommendationGroups({
  groups,
  selectedId,
  onSelect,
}: {
  groups: RecommendationGroup[];
  selectedId: string | null;
  onSelect: (paper: Paper) => void;
}) {
  return (
    <div className="space-y-8">
      {groups.map((group, groupIndex) => (
        <section key={group.key} aria-labelledby={`group-${group.key}`}>
          <header className="mb-3 border-b border-[rgb(var(--c-ink))] pb-2">
            <p className="label-mono rule-lead flex items-center text-accent">
              <span className="mr-1.5">{GROUP_ICON[group.key]}</span>
              {group.key}
              <span className="ml-auto text-ink-3">{group.hits.length}</span>
            </p>
            <h2
              id={`group-${group.key}`}
              className="mt-1.5 text-[20px] font-bold leading-tight tracking-[-0.015em] text-ink"
            >
              {group.title}
            </h2>
            <p className="prose-serif mt-0.5 text-ink-2">{group.description}</p>
          </header>

          <div className="grid border-l border-t border-line md:grid-cols-2">
            {group.hits.map((hit, index) => (
              <RecommendationCell
                key={hit.paper.id}
                paper={hit.paper}
                score={hit.score}
                reason={hit.reason}
                selected={hit.paper.id === selectedId}
                delay={groupIndex * 0.03 + index * 0.02}
                onSelect={onSelect}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function RecommendationCell({
  paper,
  score,
  reason,
  selected,
  delay,
  onSelect,
}: {
  paper: Paper;
  score: number;
  reason: string;
  selected: boolean;
  delay: number;
  onSelect: (paper: Paper) => void;
}) {
  const reduce = useReducedMotion();
  const external = paperLink(paper);

  return (
    <motion.article
      initial={reduce ? false : { opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: Math.min(delay, 0.24), ease: [0.16, 1, 0.3, 1] }}
      className={`flex flex-col justify-between gap-3 border-r border-b border-line p-4 transition-colors duration-150 ${
        selected ? "bg-accent-soft" : "bg-surface hover:bg-surface-2"
      }`}
    >
      <button type="button" onClick={() => onSelect(paper)} className="text-left">
        <h3 className="text-[15px] font-semibold leading-snug tracking-[-0.01em] text-ink">
          {truncate(paper.title, 116)}
        </h3>
        <p className="label-mono mt-1.5 text-ink-3">
          {authorLine(paper.authors, 2)} / {yearOf(paper)}
        </p>
        <p className="prose-serif mt-2 text-ink-2">{reason}</p>
      </button>

      <footer className="flex items-center justify-between gap-2 border-t border-line pt-2.5">
        <div className="flex min-w-0 items-center gap-2 label-mono text-ink-3">
          <span>{sourceLabel(paper.source)}</span>
          {paper.citation_count > 0 ? (
            <>
              <span aria-hidden="true">/</span>
              <span title={`${paper.citation_count.toLocaleString()} citations`}>
                {compactNumber(paper.citation_count)} cited
              </span>
            </>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <span className="font-mono text-[12px] font-medium tabular-nums text-accent">
            {score.toFixed(2)}
          </span>
          <PdfDownloadButton paperId={paper.id} compact />
          {external ? (
            <a
              href={external}
              target="_blank"
              rel="noreferrer noopener"
              title="Open at source"
              className="p-1.5 text-ink-3 transition-colors duration-150 hover:bg-surface-3 hover:text-ink active:translate-y-[1px]"
            >
              <ArrowSquareOut size={14} weight="bold" />
            </a>
          ) : null}
        </div>
      </footer>
    </motion.article>
  );
}

export function RecommendationSkeleton() {
  return (
    <div className="space-y-8">
      {[0, 1].map((group) => (
        <div key={group}>
          <div className="rl-skeleton mb-3 h-[18px] w-[210px]" />
          <div className="grid border-l border-t border-line md:grid-cols-2">
            {[0, 1, 2, 3].map((cell) => (
              <div key={cell} className="border-r border-b border-line bg-surface p-4">
                <div className="rl-skeleton h-[14px] w-[85%]" />
                <div className="rl-skeleton mt-2 h-[11px] w-[45%]" />
                <div className="rl-skeleton mt-3 h-[11px] w-[70%]" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
