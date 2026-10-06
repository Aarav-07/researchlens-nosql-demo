import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Books, CloudArrowDown, Funnel } from "@phosphor-icons/react";
import { api, ApiError } from "../lib/api";
import { authorLine, compactNumber, sourceLabel, truncate, yearOf } from "../lib/format";
import type { IngestResult, Paper, Stats, TopicCount } from "../lib/types";
import {
  Button,
  Chip,
  EmptyState,
  ErrorNote,
  Panel,
  SectionLabel,
  Segmented,
  Skeleton,
} from "./primitives";

/* Library is the corpus itself: what has been collected, from where, and a way
   to pull a topic in deliberately rather than through a search. Keeping this on
   its own screen is what keeps Discover uncluttered. */

type Sort = "date" | "citations" | "added";

export function LibraryView({ onSelect }: { onSelect: (paper: Paper) => void }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [topics, setTopics] = useState<TopicCount[] | null>(null);
  const [papers, setPapers] = useState<Paper[] | null>(null);
  const [total, setTotal] = useState(0);
  const [topic, setTopic] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>("date");
  const [error, setError] = useState<string | null>(null);

  const loadCorpus = useCallback(() => {
    setError(null);
    Promise.all([
      api.stats(),
      api.topics(18),
      api.papers({ limit: 40, topic: topic ?? undefined, source: source ?? undefined, sort }),
    ])
      .then(([statsOut, topicsOut, list]) => {
        setStats(statsOut);
        setTopics(topicsOut);
        setPapers(list.items);
        setTotal(list.total);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Could not load the library.");
      });
  }, [topic, source, sort]);

  useEffect(loadCorpus, [loadCorpus]);

  return (
    <div className="mx-auto grid max-w-[1520px] gap-4 px-4 py-4 lg:grid-cols-[300px_1fr]">
      <div className="space-y-4">
        <CorpusPanel stats={stats} />
        <IngestPanel onDone={loadCorpus} />
      </div>

      <div className="space-y-4">
        {error ? <ErrorNote message={error} retry={loadCorpus} /> : null}

        <Panel>
          <SectionLabel right={`${total.toLocaleString()} matching`}>
            <span className="flex items-center gap-1.5">
              <Funnel size={13} weight="bold" className="text-ink-3" />
              Filter
            </span>
          </SectionLabel>

          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip active={topic === null} onClick={() => setTopic(null)}>
                All topics
              </Chip>
              {topics === null
                ? [0, 1, 2, 3, 4].map((key) => (
                    <Skeleton key={key} className="h-[22px] w-[92px]" />
                  ))
                : topics.map((entry) => (
                    <Chip
                      key={entry.topic}
                      active={topic === entry.topic}
                      onClick={() => setTopic(entry.topic === topic ? null : entry.topic)}
                      title={`${entry.count} papers`}
                    >
                      {truncate(entry.topic, 30)}
                    </Chip>
                  ))}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1.5">
                <Chip active={source === null} onClick={() => setSource(null)}>
                  All sources
                </Chip>
                {Object.keys(stats?.by_source ?? {}).map((key) => (
                  <Chip
                    key={key}
                    active={source === key}
                    onClick={() => setSource(key === source ? null : key)}
                  >
                    {sourceLabel(key)}
                  </Chip>
                ))}
              </div>

              <div className="ml-auto">
                <Segmented<Sort>
                  options={[
                    { value: "date", label: "Newest" },
                    { value: "citations", label: "Most cited" },
                    { value: "added", label: "Recently added" },
                  ]}
                  value={sort}
                  onChange={setSort}
                />
              </div>
            </div>
          </div>
        </Panel>

        <Panel padded={false}>
          {papers === null ? (
            <div className="divide-y divide-[var(--border)]">
              {[0, 1, 2, 3, 4].map((key) => (
                <div key={key} className="px-4 py-3">
                  <Skeleton className="h-[14px] w-[58%]" />
                  <Skeleton className="mt-2 h-[11px] w-[32%]" />
                </div>
              ))}
            </div>
          ) : papers.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={<Books size={20} />}
                title="Nothing here yet"
                body="Ingest a topic from the panel on the left, or run a search in Discover and results will be collected automatically."
              />
            </div>
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {papers.map((paper) => (
                <li key={paper.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(paper)}
                    className="flex w-full items-baseline justify-between gap-4 px-4 py-3 text-left transition-colors duration-150 hover:bg-surface-2"
                  >
                    <span className="min-w-0">
                      <span className="block text-[14.5px] font-semibold leading-snug tracking-[-0.01em] text-ink">
                        {paper.title}
                      </span>
                      <span className="label-mono mt-1 block text-ink-3">
                        {authorLine(paper.authors, 2)} / {yearOf(paper)} /{" "}
                        {sourceLabel(paper.source)}
                      </span>
                    </span>
                    <span className="shrink-0 font-mono text-[11px] tabular-nums text-ink-2">
                      {paper.citation_count > 0 ? `${compactNumber(paper.citation_count)} cited` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

function CorpusPanel({ stats }: { stats: Stats | null }) {
  if (!stats) {
    return (
      <Panel>
        <SectionLabel>Corpus</SectionLabel>
        <Skeleton className="h-[13px] w-[70%]" />
        <Skeleton className="mt-2 h-[13px] w-[52%]" />
      </Panel>
    );
  }

  const rows: [string, string][] = [
    ["Papers", stats.papers.toLocaleString()],
    ["With embeddings", stats.embedded.toLocaleString()],
    ["Vector index", `${stats.index_backend} · ${stats.indexed_vectors.toLocaleString()}`],
    ["Model", stats.embedding_model.split("/").pop() ?? stats.embedding_model],
  ];

  return (
    <Panel>
      <SectionLabel>Corpus</SectionLabel>
      <dl className="space-y-1.5">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3">
            <dt className="label-mono text-ink-3">{label}</dt>
            <dd className="truncate font-mono text-[12px] text-ink">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 flex flex-wrap gap-1.5 border-t border-line pt-3">
        {Object.entries(stats.by_source).map(([key, count]) => (
          <Chip key={key}>
            {sourceLabel(key)} {count.toLocaleString()}
          </Chip>
        ))}
      </div>
    </Panel>
  );
}

function IngestPanel({ onDone }: { onDone: () => void }) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim() || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    api
      .ingest({ query: query.trim(), limit_per_source: 25 })
      .then((out) => {
        setResult(out);
        onDone();
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Ingest failed.");
      })
      .finally(() => setBusy(false));
  };

  return (
    <Panel>
      <SectionLabel>Collect a topic</SectionLabel>
      <form onSubmit={submit} className="space-y-2">
        <label htmlFor="ingest-query" className="label-mono block text-ink-3">
          Topic or research question
        </label>
        <input
          id="ingest-query"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="graph neural networks for drug discovery"
          className="h-9 w-full border border-line bg-surface px-3 text-[13px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
        />
        <p className="prose-serif text-[13.5px] text-ink-3">
          Pulls matching work from arXiv and OpenAlex, then embeds it for semantic search.
        </p>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={busy || !query.trim()}
          icon={<CloudArrowDown size={14} weight="bold" />}
        >
          {busy ? "Collecting" : "Collect"}
        </Button>
      </form>

      {error ? (
        <div className="mt-3">
          <ErrorNote message={error} />
        </div>
      ) : null}

      {result ? (
        <dl className="label-mono mt-3 space-y-1.5 border-t border-line pt-3">
          <div className="flex justify-between">
            <dt className="text-ink-3">Fetched</dt>
            <dd className="tabular-nums text-ink">{result.fetched}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-3">New</dt>
            <dd className="tabular-nums text-ink">{result.created}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-3">Embedded</dt>
            <dd className="tabular-nums text-ink">{result.embedded}</dd>
          </div>
        </dl>
      ) : null}
    </Panel>
  );
}
