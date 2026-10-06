import { CloudArrowDown, Database, Lightning } from "@phosphor-icons/react";
import type { DiscoverResponse } from "../lib/types";

/* What the system actually did, in one line. The opacity complaint about
   existing tools ("no idea why these papers") starts here: how many were
   considered, what was fetched live, how long it took, which ranking ran. */

export function StatusLine({
  result,
  corpusSize,
}: {
  result: DiscoverResponse;
  corpusSize: number | null;
}) {
  const { search, recommendations, live_fetch: live } = result;

  return (
    <div className="label-mono flex flex-wrap items-center gap-x-5 gap-y-1.5 border-b border-line bg-surface px-5 py-2.5 text-ink-3">
      <span className="flex items-center gap-1.5">
        <Lightning size={12} weight="fill" className="text-accent" />
        <span className="text-ink">{search.total} ranked</span>
        <span className="tabular-nums">{search.took_ms} ms</span>
        <span>via {search.mode}</span>
      </span>

      <span title="Raw cosine of the closest paper to your query, before ranking">
        best match{" "}
        <span className="tabular-nums text-ink">{search.top_similarity.toFixed(2)}</span>
      </span>

      {recommendations ? (
        <span>
          {recommendations.considered} candidates considered in {recommendations.groups.length}{" "}
          groups
        </span>
      ) : null}

      {live ? (
        <span className="flex items-center gap-1.5 text-ink">
          <CloudArrowDown size={12} weight="bold" className="text-accent" />
          fetched {live.fetched} live from{" "}
          {live.sources
            .filter((source) => source.status === "ok")
            .map((source) => source.source)
            .join(", ")}{" "}
          ({live.created} new)
        </span>
      ) : null}

      {corpusSize !== null ? (
        <span className="ml-auto flex items-center gap-1.5">
          <Database size={12} weight="bold" />
          <span className="tabular-nums">{corpusSize.toLocaleString()}</span> papers indexed
        </span>
      ) : null}
    </div>
  );
}
