"""OpenAlex source adapter (JSON API, no key required).

OpenAlex covers ~250M works across every field, which is what makes "any paper
on the internet" tractable. Abstracts arrive as an inverted index
(`abstract_inverted_index`) and are reconstructed here.
"""
from __future__ import annotations

from typing import Any

from ..documents import RawPaper
from ..logging_conf import get_logger
from .base import PaperSource, SourceError

log = get_logger(__name__)

# Only pull what the document schema uses - keeps responses small and fast.
_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_date",
        "publication_year",
        "type",
        "cited_by_count",
        "referenced_works_count",
        "authorships",
        "primary_location",
        "best_oa_location",
        "open_access",
        "topics",
        "keywords",
        "abstract_inverted_index",
    ]
)

SORT_FIELDS = {
    "relevance": "relevance_score:desc",
    "date": "publication_date:desc",
    "citations": "cited_by_count:desc",
}


class OpenAlexSource(PaperSource):
    name = "openalex"

    def search(
        self,
        query: str,
        limit: int = 25,
        sort: str = "relevance",
        from_year: int | None = None,
        **kwargs,
    ) -> list[RawPaper]:
        filters = []
        if from_year:
            filters.append(f"from_publication_date:{from_year}-01-01")

        params: dict[str, Any] = {
            "search": query,
            "per_page": max(1, min(limit, 200)),  # OpenAlex page cap
            "select": _FIELDS,
            "sort": SORT_FIELDS.get(sort, "relevance_score:desc"),
        }
        if filters:
            params["filter"] = ",".join(filters)
        if self.settings.openalex_mailto:
            params["mailto"] = self.settings.openalex_mailto

        payload = self._get(self.settings.openalex_base_url, params).json()
        results = payload.get("results")
        if results is None:
            raise SourceError(self.name, "response had no 'results' array")

        papers = [p for p in (self._to_raw(item) for item in results) if p]
        log.info("openalex: %d papers for %r", len(papers), query)
        return papers

    def fetch_by_id(self, external_id: str) -> RawPaper | None:
        ident = external_id.rsplit("/", 1)[-1]
        url = f"{self.settings.openalex_base_url}/{ident}"
        params = {"select": _FIELDS}
        if self.settings.openalex_mailto:
            params["mailto"] = self.settings.openalex_mailto
        return self._to_raw(self._get(url, params).json())

    # ------------------------------------------------------------------ mapping

    def _to_raw(self, item: dict[str, Any]) -> RawPaper | None:
        title = item.get("title") or item.get("display_name")
        if not title:
            return None

        authors = []
        for authorship in item.get("authorships") or []:
            author = authorship.get("author") or {}
            name = author.get("display_name")
            if not name:
                continue
            entry: dict[str, Any] = {"name": name}
            institutions = authorship.get("institutions") or []
            if institutions and institutions[0].get("display_name"):
                entry["affiliation"] = institutions[0]["display_name"]
            authors.append(entry)

        primary = item.get("primary_location") or {}
        best_oa = item.get("best_oa_location") or {}
        source_info = primary.get("source") or {}

        topics = [t["display_name"] for t in (item.get("topics") or []) if t.get("display_name")]
        keywords = [
            k["display_name"] for k in (item.get("keywords") or []) if k.get("display_name")
        ]

        openalex_id = (item.get("id") or "").rsplit("/", 1)[-1]

        return RawPaper(
            title=title,
            source=self.name,
            abstract=_invert_abstract(item.get("abstract_inverted_index")),
            authors=authors,
            published_date=self._parse_date(item.get("publication_date"))
            or self._parse_date(str(item.get("publication_year") or "") or None),
            venue=source_info.get("display_name"),
            doi=item.get("doi"),
            url=primary.get("landing_page_url") or item.get("id"),
            pdf_url=best_oa.get("pdf_url") or primary.get("pdf_url"),
            topics=topics,
            keywords=keywords,
            citation_count=int(item.get("cited_by_count") or 0),
            reference_count=int(item.get("referenced_works_count") or 0),
            source_ids={"openalex": openalex_id, "doi": item.get("doi") or ""},
        )


def _invert_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}; rebuild the sentence."""
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for word, spots in inverted.items():
        for spot in spots:
            positions.append((spot, word))
    if not positions:
        return None
    positions.sort(key=lambda p: p[0])
    return " ".join(word for _, word in positions)
