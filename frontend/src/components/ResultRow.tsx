import { ArrowSquareOut } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import type { Paper, SearchHit } from "../lib/types";
import { authorLine, compactNumber, paperLink, sourceLabel, truncate, yearOf } from "../lib/format";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { PdfDownloadButton } from "./PdfDownloadButton";

/* A result is a reading decision, so the row leads with title and reason, then
   the evidence. Rows are separated by hairlines rather than cards: 25 cards in
   a column is noise, 25 ruled rows is a list you can scan. */

export function ResultRow({
  hit,
  index,
  selected,
  onSelect,
}: {
  hit: SearchHit;
  index: number;
  selected: boolean;
  onSelect: (paper: Paper) => void;
}) {
  const reduce = useReducedMotion();
  const { paper } = hit;
  const link = paperLink(paper);

  return (
    <motion.article
      initial={reduce ? false : { opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: Math.min(index * 0.02, 0.2), ease: [0.16, 1, 0.3, 1] }}
      className={`group relative border-b border-line px-5 py-4 transition-colors duration-150 last:border-b-0 ${
        selected ? "bg-accent-soft" : "hover:bg-surface-2"
      }`}
    >
      {selected ? (
        <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-accent" />
      ) : null}

      <div className="flex items-start justify-between gap-4">
        <button
          type="button"
          onClick={() => onSelect(paper)}
          className="flex-1 text-left"
          aria-current={selected ? "true" : undefined}
        >
          <h3 className="text-[16px] font-semibold leading-snug tracking-[-0.012em] text-ink">
            {paper.title}
          </h3>
          <p className="label-mono mt-1.5 text-ink-3">
            {authorLine(paper.authors)} / {yearOf(paper)}
            {paper.venue ? ` / ${truncate(paper.venue, 38)}` : ""}
          </p>
        </button>

        <div className="flex shrink-0 items-center gap-1">
          <span
            className="font-mono text-[13px] font-medium tabular-nums text-accent"
            title="Combined relevance score"
          >
            {hit.score.toFixed(2)}
          </span>
          <PdfDownloadButton paperId={paper.id} compact />
          {link ? (
            <a
              href={link}
              target="_blank"
              rel="noreferrer noopener"
              title="Open the paper at its source"
              className="p-1.5 text-ink-3 transition-colors duration-150 hover:bg-surface-3 hover:text-ink active:translate-y-[1px]"
            >
              <ArrowSquareOut size={14} weight="bold" />
            </a>
          ) : null}
        </div>
      </div>

      {paper.abstract ? (
        <p className="prose-serif mt-2 max-w-[84ch] text-ink-2">
          {truncate(paper.abstract, 230)}
        </p>
      ) : null}

      <div className="mt-3 grid gap-4 md:grid-cols-[1fr_250px] md:items-start">
        <div className="label-mono flex flex-wrap items-center gap-x-2.5 gap-y-1 text-ink-3">
          <span className="text-ink-2">{sourceLabel(paper.source)}</span>
          {paper.citation_count > 0 ? (
            <>
              <span aria-hidden="true">/</span>
              <span title={`${paper.citation_count.toLocaleString()} citations`}>
                {compactNumber(paper.citation_count)} cited
              </span>
            </>
          ) : null}
          {paper.topics.slice(0, 2).map((topic) => (
            <span key={topic} className="flex items-center gap-2.5">
              <span aria-hidden="true">/</span>
              {truncate(topic, 26)}
            </span>
          ))}
          <span className="basis-full pt-0.5 normal-case tracking-normal text-ink-2">
            {hit.reason}
          </span>
        </div>

        <ScoreBreakdown parts={hit.score_parts} />
      </div>
    </motion.article>
  );
}

export function ResultRowSkeleton() {
  return (
    <div className="border-b border-line px-5 py-4 last:border-b-0">
      <div className="rl-skeleton h-[16px] w-[62%]" />
      <div className="rl-skeleton mt-2 h-[11px] w-[34%]" />
      <div className="rl-skeleton mt-3 h-[12px] w-full" />
      <div className="rl-skeleton mt-1.5 h-[12px] w-[78%]" />
      <div className="mt-3 flex gap-2">
        <div className="rl-skeleton h-[18px] w-[64px]" />
        <div className="rl-skeleton h-[18px] w-[88px]" />
      </div>
    </div>
  );
}
