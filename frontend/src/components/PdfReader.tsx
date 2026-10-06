import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowSquareOut,
  CornersIn,
  CornersOut,
  FileX,
  MagnifyingGlassMinus,
  MagnifyingGlassPlus,
} from "@phosphor-icons/react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { api, ApiError } from "../lib/api";
import { paperLink } from "../lib/format";
import type { Paper } from "../lib/types";
import { Button, EmptyState, Skeleton } from "./primitives";
import { PdfDownloadButton } from "./PdfDownloadButton";

/* Reading happens here, not in a new tab.

   Two decisions make that work:
   1. The file is streamed through the API, because publishers block cross-origin
      embedding and fetching.
   2. Pages are rendered with PDF.js rather than handed to the browser's built-in
      viewer. Browsers disagree about whether an embedded PDF renders or triggers
      a download, and a reading tool cannot depend on that coin flip. */

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const ZOOM_STEPS = [0.75, 1, 1.25, 1.5, 2];

export function PdfReader({
  paper,
  expanded,
  onToggleExpand,
}: {
  paper: Paper;
  expanded: boolean;
  onToggleExpand: () => void;
}) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [pageCount, setPageCount] = useState(0);
  const [zoomIndex, setZoomIndex] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const external = paperLink(paper);

  useEffect(() => {
    let cancelled = false;
    // The loading task, not the document proxy, is what gets torn down.
    let task: ReturnType<typeof pdfjs.getDocument> | null = null;

    setLoading(true);
    setError(null);
    setDoc(null);
    setPageCount(0);

    // Confirm a PDF exists before pulling megabytes over the wire.
    api
      .fileInfo(paper.id)
      .then((info) => {
        if (cancelled) return null;
        if (!info.available) throw new ApiError("This record has no open-access PDF on file.", 404);
        task = pdfjs.getDocument({ url: api.fileUrl(paper.id), withCredentials: false });
        return task.promise;
      })
      .then((document) => {
        if (cancelled || !document) return;
        setDoc(document);
        setPageCount(document.numPages);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoading(false);
        setError(
          err instanceof ApiError
            ? err.message
            : "The PDF could not be loaded from its host.",
        );
      });

    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [paper.id]);

  const zoom = ZOOM_STEPS[zoomIndex];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <p className="label-mono truncate text-ink-3">
          {pageCount > 0 ? `${pageCount} pages` : "PDF"}
        </p>
        <div className="flex shrink-0 items-center gap-1.5">
          <div className="flex items-center border border-line bg-surface">
            <button
              type="button"
              onClick={() => setZoomIndex((i) => Math.max(0, i - 1))}
              disabled={zoomIndex === 0}
              aria-label="Zoom out"
              className="px-1.5 py-1 text-ink-2 disabled:opacity-40"
            >
              <MagnifyingGlassMinus size={14} weight="bold" />
            </button>
            <span className="px-1.5 font-mono text-[11px] tabular-nums text-ink-2">
              {Math.round(zoom * 100)}%
            </span>
            <button
              type="button"
              onClick={() => setZoomIndex((i) => Math.min(ZOOM_STEPS.length - 1, i + 1))}
              disabled={zoomIndex === ZOOM_STEPS.length - 1}
              aria-label="Zoom in"
              className="px-1.5 py-1 text-ink-2 disabled:opacity-40"
            >
              <MagnifyingGlassPlus size={14} weight="bold" />
            </button>
          </div>

          <PdfDownloadButton paperId={paper.id} />

          <Button
            size="sm"
            variant="ghost"
            onClick={onToggleExpand}
            aria-label={expanded ? "Collapse reader" : "Expand reader"}
            title={expanded ? "Collapse reader" : "Expand reader"}
          >
            {expanded ? (
              <CornersIn size={15} weight="bold" />
            ) : (
              <CornersOut size={15} weight="bold" />
            )}
          </Button>
        </div>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto bg-surface-2 px-3 py-3">
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-[12px] w-[40%]" />
            <Skeleton className="h-[420px] w-full" />
          </div>
        ) : null}

        {error ? (
          <EmptyState
            icon={<FileX size={20} />}
            title="No readable PDF"
            body={error}
            action={
              external ? (
                <a href={external} target="_blank" rel="noreferrer noopener">
                  <Button size="sm" icon={<ArrowSquareOut size={14} weight="bold" />}>
                    Open at source
                  </Button>
                </a>
              ) : undefined
            }
          />
        ) : null}

        {doc
          ? Array.from({ length: pageCount }, (_, index) => (
              <PdfPage
                key={`${paper.id}-${index + 1}-${zoom}`}
                doc={doc}
                pageNumber={index + 1}
                zoom={zoom}
                root={scrollRef}
              />
            ))
          : null}
      </div>
    </div>
  );
}

/* Pages render only once they are near the viewport. A 40-page paper would
   otherwise rasterize every page before the reader sees the first one. */
function PdfPage({
  doc,
  pageNumber,
  zoom,
  root,
}: {
  doc: PDFDocumentProxy;
  pageNumber: number;
  zoom: number;
  root: React.RefObject<HTMLDivElement | null>;
}) {
  const holderRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(pageNumber <= 2);
  const [rendered, setRendered] = useState(false);

  useEffect(() => {
    const node = holderRef.current;
    if (!node || visible) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { root: root.current ?? null, rootMargin: "600px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible, root]);

  const render = useCallback(async () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const page = await doc.getPage(pageNumber);
    const containerWidth = root.current?.clientWidth ?? 800;
    const base = page.getViewport({ scale: 1 });
    // Fit the panel width first, then apply the user's zoom on top.
    const fitScale = Math.max((containerWidth - 32) / base.width, 0.2);
    const viewport = page.getViewport({ scale: fitScale * zoom });
    const ratio = window.devicePixelRatio || 1;

    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = `${Math.floor(viewport.width)}px`;
    canvas.style.height = `${Math.floor(viewport.height)}px`;

    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    await page.render({ canvas, canvasContext: context, viewport }).promise;
    setRendered(true);
  }, [doc, pageNumber, zoom, root]);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    render().catch(() => {
      if (!cancelled) setRendered(false);
    });
    return () => {
      cancelled = true;
    };
  }, [visible, render]);

  return (
    <div ref={holderRef} className="mb-3 flex justify-center">
      <div className="relative border border-line bg-white shadow-[var(--shadow-stamp)]">
        {!rendered ? <Skeleton className="h-[420px] w-[320px]" /> : null}
        <canvas
          ref={canvasRef}
          aria-label={`Page ${pageNumber}`}
          className={rendered ? "block" : "hidden"}
        />
      </div>
    </div>
  );
}
