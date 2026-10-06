export type SearchMode = "hybrid" | "semantic" | "keyword";

export interface Author {
  name: string;
  affiliation?: string | null;
}

export interface Paper {
  id: string;
  title: string;
  abstract: string | null;
  authors: Author[];
  published_date: string | null;
  year: number | null;
  venue: string | null;
  doi: string | null;
  url: string | null;
  pdf_url: string | null;
  topics: string[];
  keywords: string[];
  citation_count: number;
  source: string;
  source_ids: Record<string, string>;
  has_embedding: boolean;
}

export interface ScoreParts {
  semantic?: number;
  keyword?: number;
  recency?: number;
  citations?: number;
}

export interface SearchHit {
  paper: Paper;
  score: number;
  score_parts: ScoreParts;
  reason: string;
  /** Raw cosine against the query: comparable across searches, unlike `score`. */
  similarity: number;
}

export interface SearchResponse {
  query: string;
  mode: SearchMode;
  total: number;
  took_ms: number;
  backend: string;
  /** Best raw cosine in the corpus for this query, even when nothing passed the floor. */
  top_similarity: number;
  hits: SearchHit[];
}

export interface PaperList {
  total: number;
  limit: number;
  offset: number;
  items: Paper[];
}

export interface TopicCount {
  topic: string;
  count: number;
}

export interface Stats {
  papers: number;
  embedded: number;
  by_source: Record<string, number>;
  top_topics: TopicCount[];
  embedding_model: string;
  search_backend: string;
  index_backend: string;
  indexed_vectors: number;
}

export interface SourceOutcome {
  source: string;
  fetched: number;
  status: string;
  error: string | null;
}

export interface IngestResult {
  query: string;
  requested: number;
  fetched: number;
  created: number;
  updated: number;
  embedded: number;
  sources: SourceOutcome[];
}

export interface RecommendationGroup {
  key: "closest" | "recent" | "foundational" | "adjacent";
  title: string;
  description: string;
  hits: SearchHit[];
}

export interface Recommendations {
  query: string;
  took_ms: number;
  considered: number;
  groups: RecommendationGroup[];
}

export interface LiveFetch {
  fetched: number;
  created: number;
  updated: number;
  embedded: number;
  sources: SourceOutcome[];
}

export interface DiscoverResponse {
  search: SearchResponse;
  recommendations: Recommendations | null;
  live_fetch: LiveFetch | null;
  notes: string[];
}
