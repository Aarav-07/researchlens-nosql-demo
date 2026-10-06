import { useState } from "react";
import { DownloadSimple } from "@phosphor-icons/react";
import { api, ApiError } from "../lib/api";
import { Button } from "./primitives";

/** Downloads only a verified PDF, never an API error JSON body. */
export function PdfDownloadButton({
  paperId,
  compact = false,
}: {
  paperId: string;
  compact?: boolean;
}) {
  const [error, setError] = useState<string | null>(null);

  const download = async () => {
    setError(null);
    try {
      await api.downloadFile(paperId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The PDF could not be downloaded.");
    }
  };

  return (
    <>
      {compact ? (
        <button
          type="button"
          onClick={() => void download()}
          title="Download the PDF"
          aria-label="Download the PDF"
          className="p-1.5 text-ink-3 transition-colors duration-150 hover:bg-surface-3 hover:text-ink active:translate-y-[1px]"
        >
          <DownloadSimple size={14} weight="bold" />
        </button>
      ) : (
        <Button size="sm" icon={<DownloadSimple size={14} weight="bold" />} onClick={() => void download()}>
          Download
        </Button>
      )}
      {error ? (
        <div
          role="alert"
          className="fixed bottom-4 right-4 z-50 max-w-sm border border-line-strong bg-surface px-3 py-2 font-mono text-[11px] leading-relaxed text-ink shadow-[var(--shadow-stamp)]"
        >
          PDF unavailable: {error}
        </div>
      ) : null}
    </>
  );
}
