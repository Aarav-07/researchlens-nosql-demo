import { useCallback, useEffect, useRef, useState } from "react";
import { ListMagnifyingGlass, SquaresFour, WifiSlash } from "@phosphor-icons/react";
import { api, ApiError } from "./lib/api";
import type { DiscoverResponse, Paper, SearchMode } from "./lib/types";
import { TopBar } from "./components/TopBar";
import { StatusLine } from "./components/StatusLine";
import { ResultRow, ResultRowSkeleton } from "./components/ResultRow";
import { RecommendationGroups, RecommendationSkeleton } from "./components/RecommendationGroups";
import { PaperPanel } from "./components/PaperPanel";
import { LibraryView } from "./components/LibraryView";
import { EmptyState, ErrorNote, Panel, Segmented } from "./components/primitives";

type View = "discover" | "library";
type Layout = "grouped" | "ranked";

const EXAMPLES = [
  "multimodal learning for healthcare",
  "transformer architectures for medical image analysis",
  "graph neural networks for recommendation",
];

export default function App() {
  const [view, setView] = useState<View>("discover");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [layout, setLayout] = useState<Layout>("grouped");
  const [result, setResult] = useState<DiscoverResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Paper | null>(null);
  const [readerExpanded, setReaderExpanded] = useState(false);
  const [corpus, setCorpus] = useState<number | null>(null);
  const [offline, setOffline] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    api
      .health()
      .then((health) => {
        setCorpus(health.papers);
        setOffline(!health.mongodb);
      })
      .catch(() => setOffline(true));
  }, []);

  const runSearch = useCallback(
    (raw?: string) => {
      const q = (raw ?? query).trim();
      if (!q) return;
      if (raw !== undefined) setQuery(raw);
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;

      setBusy(true);
      setError(null);
      setView("discover");
      api
        .discover(q, mode, { limit: 25, live: true, signal: controller.signal })
        .then((response) => {
          setResult(response);
          if (response.live_fetch) {
            api.health().then((health) => setCorpus(health.papers)).catch(() => undefined);
          }
        })
        .catch((err: unknown) => {
          if (err instanceof DOMException && err.name === "AbortError") return;
          setError(err instanceof ApiError ? err.message : "Search failed.");
        })
        .finally(() => {
          if (abort.current === controller) setBusy(false);
        });
    },
    [mode, query],
  );

  const selectPaper = useCallback((paper: Paper) => {
    setSelected(paper);
    setReaderExpanded(false);
  }, []);

  const closePaper = useCallback(() => {
    setSelected(null);
    setReaderExpanded(false);
  }, []);

  const goHome = useCallback(() => {
    abort.current?.abort();
    setView("discover");
    setQuery("");
    setMode("hybrid");
    setLayout("grouped");
    setResult(null);
    setBusy(false);
    setError(null);
    closePaper();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [closePaper]);

  // Escape closes the detail panel; expanded reader collapses first.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (readerExpanded) setReaderExpanded(false);
      else if (selected) closePaper();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [readerExpanded, selected, closePaper]);

  const hits = result?.search.hits ?? [];
  const groups = result?.recommendations?.groups ?? [];

  return (
    <div className="min-h-[100dvh] bg-bg">
      <TopBar
        query={query}
        onQueryChange={setQuery}
        onSubmit={() => runSearch()}
        mode={mode}
        onModeChange={(next) => {
          setMode(next);
          if (result) runSearch();
        }}
        view={view}
        onViewChange={setView}
        onHome={goHome}
        busy={busy}
      />

      {offline ? (
        <div className="mx-auto max-w-[1520px] px-4 pt-4">
          <ErrorNote message="The API is unreachable or MongoDB is down. Start the backend on port 8010, then reload." />
        </div>
      ) : null}

      {view === "library" ? (
        <LibraryView onSelect={selectPaper} />
      ) : (
        <>
          {result ? <StatusLine result={result} corpusSize={corpus} /> : null}

          <main
            className={`mx-auto grid max-w-[1520px] gap-4 px-4 py-4 ${
              selected
                ? readerExpanded
                  ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]"
                  : "lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]"
                : "lg:grid-cols-1"
            }`}
          >
            <section className="min-w-0">
              {result ? (
                <div className="mb-3 flex items-center justify-between gap-3">
                  <Segmented<Layout>
                    options={[
                      { value: "grouped", label: "Grouped", hint: "Recommendations by role" },
                      { value: "ranked", label: "Ranked", hint: "One relevance-ordered list" },
                    ]}
                    value={layout}
                    onChange={setLayout}
                  />
                  <p className="label-mono text-ink-3">
                    {layout === "grouped"
                      ? "Each group states the job it does"
                      : "Every row shows its score breakdown"}
                  </p>
                </div>
              ) : null}

              {error ? <ErrorNote message={error} retry={() => runSearch()} /> : null}

              {busy && !result ? (
                <div className="space-y-4">
                  <Panel padded={false}>
                    {[0, 1, 2].map((key) => (
                      <ResultRowSkeleton key={key} />
                    ))}
                  </Panel>
                  <RecommendationSkeleton />
                </div>
              ) : null}

              {!busy && !result && !error ? (
                <EmptyState
                  icon={<ListMagnifyingGlass size={22} />}
                  title="Describe what you are working on"
                  body="ResearchLens searches its corpus, and when a topic is thinly covered it fetches matching work from arXiv and OpenAlex before ranking. Results are grouped by the job each paper does, and every paper can be read and downloaded here."
                  action={
                    /* Uppercase mono runs wide, so examples stack as ruled rows
                       and wrap rather than overflowing their button. */
                    <ul className="w-full max-w-[560px] border-t border-line">
                      {EXAMPLES.map((example) => (
                        <li key={example} className="border-b border-line">
                          <button
                            type="button"
                            onClick={() => runSearch(example)}
                            className="group flex w-full items-baseline gap-3 py-2.5 text-left transition-colors duration-150 hover:bg-surface-2"
                          >
                            <span className="label-mono shrink-0 text-accent">Try</span>
                            <span className="text-[14px] font-medium leading-snug text-ink">
                              {example}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  }
                />
              ) : null}

              {result && hits.length === 0 && !busy ? (
                <EmptyState
                  icon={<WifiSlash size={22} />}
                  title="Nothing matched, even after fetching"
                  body="The sources returned no usable records for this phrasing. Try fewer words, or a different framing of the same idea."
                />
              ) : null}

              {result && hits.length > 0 && layout === "grouped" && groups.length > 0 ? (
                <RecommendationGroups
                  groups={groups}
                  selectedId={selected?.id ?? null}
                  onSelect={selectPaper}
                />
              ) : null}

              {result && hits.length > 0 && (layout === "ranked" || groups.length === 0) ? (
                <Panel padded={false}>
                  {hits.map((hit, index) => (
                    <ResultRow
                      key={hit.paper.id}
                      hit={hit}
                      index={index}
                      selected={selected?.id === hit.paper.id}
                      onSelect={selectPaper}
                    />
                  ))}
                </Panel>
              ) : null}
            </section>

            {selected ? (
              <section className="min-w-0 lg:sticky lg:top-[80px] lg:h-[calc(100dvh-96px)]">
                <PaperPanel
                  paper={selected}
                  onClose={closePaper}
                  onSelect={selectPaper}
                  expanded={readerExpanded}
                  onToggleExpand={() => setReaderExpanded((value) => !value)}
                />
              </section>
            ) : null}
          </main>
        </>
      )}

      <footer className="mt-4 border-t-2 border-[rgb(var(--c-ink))]">
        <div className="label-mono mx-auto flex max-w-[1520px] flex-wrap items-center gap-3 px-5 py-5 text-ink-3">
          <SquaresFour size={12} weight="bold" className="text-accent" />
          <span>Ranking is explainable by design</span>
          <span aria-hidden="true">/</span>
          <span>Every result shows the signals behind its position</span>
          <span className="ml-auto">arXiv + OpenAlex</span>
        </div>
      </footer>
    </div>
  );
}
