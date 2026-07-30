from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

import requests


API_URL = "https://ja.wikipedia.org/w/api.php"
USER_AGENT = "KnowledgeGraphCollector/2.0 (requests; local research tool)"
REQUEST_TIMEOUT = 20

_EXCLUDED_KEYWORDS = [
    "大学",
    "王国",
    "共和国",
    "州",
    "市",
    "町",
    "村",
    "県",
    "区",
    "諸島",
    "半島",
]


@dataclass
class _MediaWikiPage:
    title: str
    _exists: bool = False
    _text: str = ""
    _summary: str = ""
    _links: dict[str, Any] | None = None

    def exists(self) -> bool:
        return self._exists

    @property
    def text(self) -> str:
        return self._text

    @property
    def summary(self) -> str:
        return self._summary or self._text

    @property
    def links(self) -> dict[str, Any]:
        return self._links or {}


class _MediaWikiClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            }
        )
        self._page_cache: dict[str, _MediaWikiPage] = {}

    def _request(self, params: dict[str, Any], max_attempts: int = 4) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._session.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    sleep_seconds = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else min(8.0, 1.5 * attempt)
                    print(f"[Wikipedia][WARN] 429 を検知したため {sleep_seconds:.1f} 秒待機して再試行します: {params.get('titles', '')}")
                    time.sleep(sleep_seconds)
                    continue
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt < max_attempts:
                    sleep_seconds = min(8.0, 1.5 * attempt)
                    print(f"[Wikipedia][WARN] 取得失敗のため再試行します ({attempt}/{max_attempts}): {exc}")
                    time.sleep(sleep_seconds)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("request failed")

    def _fetch_page(self, title: str) -> _MediaWikiPage:
        if title in self._page_cache:
            return self._page_cache[title]
        try:
            payload = self._request(
                {
                    "action": "query",
                    "titles": title,
                    "prop": "links|extracts",
                    "pllimit": "max",
                    "explaintext": 1,
                    "exsectionformat": "plain",
                    "redirects": 1,
                    "format": "json",
                    "formatversion": 2,
                }
            )
            pages = payload.get("query", {}).get("pages", [])
            if not pages:
                page = _MediaWikiPage(title=title)
                self._page_cache[title] = page
                return page
            page_data = pages[0]
            if page_data.get("missing"):
                page = _MediaWikiPage(title=title)
                self._page_cache[title] = page
                return page
            links = {
                str(item.get("title") or ""): {}
                for item in page_data.get("links", [])
                if str(item.get("title") or "")
            }
            text = str(page_data.get("extract") or "")
            page_title = str(page_data.get("title") or title)
            page = _MediaWikiPage(
                title=page_title,
                _exists=True,
                _text=text,
                _summary=text[:4000],
                _links=links,
            )
            self._page_cache[title] = page
            self._page_cache[page_title] = page
            return page
        except Exception as exc:
            print(f"[Wikipedia][WARN] ページ取得に失敗しました: {title} ({exc})")
            page = _MediaWikiPage(title=title)
            self._page_cache[title] = page
            return page

    def page(self, title: str) -> _MediaWikiPage:
        return self._fetch_page(title)


def _create_wiki() -> _MediaWikiClient:
    return _MediaWikiClient()


def _is_content_title(title: str) -> bool:
    return bool(title and ":" not in title and not title.startswith("List of"))


def _topic_candidates(topic: str) -> list[str]:
    normalized = topic.strip()
    candidates = [normalized]
    for suffix in (" プログラミング", "プログラミング", " programming", " Programming"):
        if normalized.endswith(suffix):
            base = normalized[: -len(suffix)].strip()
            if base:
                candidates.extend([base, f"{base} (プログラミング言語)"])
    return list(dict.fromkeys(candidates))


def _resolve_page(wiki: Any, topic: str):
    for candidate in _topic_candidates(topic):
        page = wiki.page(candidate)
        if getattr(page, "exists", lambda: False)():
            if candidate != topic:
                print(f"[Wikipedia] ページ名を解決: {topic} -> {candidate}")
            return page
    return wiki.page(topic)


def _page_text(page: Any) -> str:
    summary = getattr(page, "summary", "") or ""
    if summary:
        return summary
    text = getattr(page, "text", "") or ""
    return text or ""


def _tokenize(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(text).lower())
    return re.findall(r"[a-z0-9]+|[一-龠々仝ー]+|[ぁ-ゖ]+|[ァ-ヶ]+", normalized)


def _build_tfidf_vectors(texts: list[str]) -> tuple[list[Counter[str]], dict[str, float], list[str]]:
    tokenized_docs = [_tokenize(text) for text in texts]
    doc_freq: Counter[str] = Counter()
    for tokens in tokenized_docs:
        doc_freq.update(set(tokens))

    vocab = sorted(doc_freq)
    doc_count = max(1, len(tokenized_docs))
    idf = {term: float(doc_count / max(1, doc_freq[term])) for term in vocab}
    vectors = []
    for tokens in tokenized_docs:
        token_counter = Counter(tokens)
        vector = Counter({term: token_counter[term] * idf[term] for term in token_counter if term in idf})
        vectors.append(vector)
    return vectors, idf, vocab


def calculate_tfidf_similarity(text_a: str, text_b: str) -> float:
    """TF-IDF ベースの類似度を算出する。"""
    try:
        vectors, _, _ = _build_tfidf_vectors([text_a, text_b])
        if not vectors[0] or not vectors[1]:
            return 0.0
        numerator = sum(vectors[0][term] * vectors[1][term] for term in set(vectors[0]) & set(vectors[1]))
        norm_a = sum(value * value for value in vectors[0].values()) ** 0.5
        norm_b = sum(value * value for value in vectors[1].values()) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return round(numerator / (norm_a * norm_b), 4)
    except Exception:
        return 0.0


def calculate_content_similarity(text_a: str, text_b: str) -> float:
    """簡易なトークン重なりベースの類似度と TF-IDF 類似度を組み合わせる。"""
    try:
        overlap = 0.0
        tokens_a = Counter(_tokenize(text_a))
        tokens_b = Counter(_tokenize(text_b))
        if tokens_a and tokens_b:
            union = set(tokens_a) | set(tokens_b)
            if union:
                overlap = sum(min(tokens_a[token], tokens_b[token]) for token in union) / max(1, len(union))
        tfidf_similarity = calculate_tfidf_similarity(text_a, text_b)
        return round((overlap * 0.4) + (tfidf_similarity * 0.6), 4)
    except Exception:
        return 0.0


def classify_page_type(title: str, text: str) -> str:
    """ページ内容から大まかな種類を推定する。"""
    try:
        haystack = f"{title}\n{text}".lower()
        if any(
            keyword in haystack
            for keyword in [
                "プログラミング",
                "ソフトウェア",
                "ライブラリ",
                "フレームワーク",
                "アルゴリズム",
                "言語",
                "api",
                "database",
                "framework",
                "software",
                "compiler",
                "library",
                "protocol",
                "system",
            ]
        ):
            return "technology"
        if any(keyword in haystack for keyword in ["都市", "県", "国", "島", "山", "川", "駅", "地域", "地方", "首都", "地名"]):
            return "place"
        if any(keyword in haystack for keyword in ["企業", "会社", "株式会社", "大学", "学校", "組織", "団体", "協会"]):
            return "organization"
        if any(keyword in haystack for keyword in ["人物", "政治家", "作家", "映画", "作品", "歌手", "選手", "王", "皇帝"]):
            return "person"
        if any(keyword in haystack for keyword in ["戦争", "事件", "会議", "祭", "歴史", "年", "時代"]):
            return "event"
        return "concept"
    except Exception:
        return "concept"


def _relevance_label(similarity: float) -> str:
    if similarity >= 0.25:
        return "high"
    if similarity >= 0.1:
        return "medium"
    return "low"


def _relationship_from_types(topic_type: str, page_type: str, similarity: float) -> str:
    if page_type == topic_type and similarity >= 0.15:
        return "same_domain"
    if page_type in {"technology", "concept"} and topic_type in {"technology", "concept"}:
        return "prerequisite"
    if page_type in {"organization", "person", "place", "event"}:
        return "context"
    return "related"


def _iter_titles_from_links(links: Any) -> list[str]:
    if isinstance(links, dict):
        return [str(title) for title in links.keys() if _is_content_title(str(title))]
    return [str(title) for title in links if _is_content_title(str(title))]


def get_all_links(topic: str, wiki: Any | None = None) -> tuple[list[str], str]:
    """トピックページの全リンクと本文を MediaWiki API から取得する。"""
    try:
        print(f"[Wikipedia] トピックページを取得中: {topic}")
        wiki = wiki or _create_wiki()
        page = _resolve_page(wiki, topic)
        if not getattr(page, "exists", lambda: False)():
            print(f"[Wikipedia][WARN] ページが存在しません: {topic}")
            return [], ""
        links = []
        seen = set()
        for title in _iter_titles_from_links(getattr(page, "links", {})):
            if title in seen:
                continue
            seen.add(title)
            links.append(title)
        return links, _page_text(page)
    except Exception as exc:
        print(f"[Wikipedia][WARN] トピックリンク取得に失敗しました: {exc}")
        return [], ""


def get_page_text(title: str, wiki: Any | None = None) -> str:
    """MediaWiki APIでページ本文を取得して返す。"""
    try:
        wiki = wiki or _create_wiki()
        page = wiki.page(title)
        if not getattr(page, "exists", lambda: False)():
            return ""
        return _page_text(page)
    except Exception as exc:
        print(f"[Wikipedia][WARN] ページ本文取得に失敗しました: {title} ({exc})")
        return ""


def get_related_skills(topic: str, max_skills: int | None = 200, wiki: Any | None = None) -> list[str]:
    """
    トピックのWikipediaページからリンク先ページ名を取得する。
    存在しないページは除外する。
    エラー時は空リストを返す。
    """
    try:
        print(f"[Wikipedia] トピックページを取得中: {topic}")
        wiki = wiki or _create_wiki()
        page = _resolve_page(wiki, topic)
        if not getattr(page, "exists", lambda: False)():
            print(f"[Wikipedia][WARN] ページが存在しません: {topic}")
            return []

        skills: list[str] = []
        for title in _iter_titles_from_links(getattr(page, "links", {})):
            try:
                if title in skills:
                    continue
                linked_page = wiki.page(title)
                if getattr(linked_page, "exists", lambda: False)():
                    skills.append(title)
                    print(f"[Wikipedia] 関連スキルを追加: {title}")
                else:
                    print(f"[Wikipedia][WARN] 存在しないリンクを除外: {title}")
                if max_skills is not None and len(skills) >= max_skills:
                    break
            except Exception as exc:
                print(f"[Wikipedia][WARN] リンク確認に失敗しました: {title} ({exc})")
                continue
        return skills
    except Exception as exc:
        print(f"[Wikipedia][WARN] 関連スキル取得に失敗しました: {exc}")
        return []


def get_link_map(skills: list[str], wiki: Any | None = None) -> dict[str, set[str]]:
    """
    各スキルページが持つリンク先を取得して辞書で返す。
    例：{"関数": {"変数", "引数", "戻り値"}, ...}
    取得に失敗したスキルはスキップする。
    """
    try:
        print(f"[Wikipedia] リンクマップを取得中: {len(skills)}件")
        wiki = wiki or _create_wiki()
        link_map: dict[str, set[str]] = {}
        for index, skill in enumerate(skills, start=1):
            try:
                page = wiki.page(skill)
                if not getattr(page, "exists", lambda: False)():
                    print(f"[Wikipedia][WARN] スキルページが存在しないためスキップ: {skill}")
                    continue
                links = set(_iter_titles_from_links(getattr(page, "links", {})))
                link_map[skill] = links
                print(f"[Wikipedia] {skill}: {len(links)}リンク")
            except Exception as exc:
                print(f"[Wikipedia][WARN] リンク取得に失敗しました: {skill} ({exc})")
                continue
            if index % 5 == 0:
                time.sleep(0.5)
        return link_map
    except Exception as exc:
        print(f"[Wikipedia][WARN] リンクマップ取得に失敗しました: {exc}")
        return {}


def filter_skills(
    skills: list[str],
    root_text: str,
    link_map: dict[str, set[str]],
    min_text_length: int = 300,
    min_backlinks: int = 2,
    wiki: Any | None = None,
) -> list[str]:
    """
    指定した4条件で候補スキルを絞り込む。
    """
    try:
        print(f"[Wikipedia] スキルをフィルタリング中: {len(skills)}件")
        candidate_set = list(dict.fromkeys(skills))
        backlinks = Counter()
        for links in link_map.values():
            for title in links:
                backlinks[title] += 1

        filtered: list[str] = []
        for skill in candidate_set:
            if not skill or skill[0].isdigit() or any(keyword in skill for keyword in _EXCLUDED_KEYWORDS):
                continue
            page_text = get_page_text(skill, wiki=wiki)
            if len(page_text.strip()) < min_text_length:
                continue
            if backlinks.get(skill, 0) < min_backlinks:
                continue
            similarity = calculate_tfidf_similarity(root_text, page_text)
            if similarity < 0.05:
                continue
            filtered.append(skill)
            print(f"[Wikipedia] 候補を採用: {skill} (similarity={similarity:.3f})")
        return filtered
    except Exception as exc:
        print(f"[Wikipedia][WARN] スキルフィルタリングに失敗しました: {exc}")
        return []


def get_semantic_enrichment(topic: str, skills: list[str], wiki: Any | None = None) -> dict[str, dict[str, Any]]:
    """トピックページと候補ページの本文類似度・種類を計算してメタデータを返す。"""
    try:
        if wiki is None:
            wiki = _create_wiki()
        topic_page = _resolve_page(wiki, topic)
        topic_text = _page_text(topic_page)
        topic_type = classify_page_type(topic_page.title, topic_text)

        enrichment: dict[str, dict[str, Any]] = {}
        for skill in skills:
            try:
                page = wiki.page(skill)
                if not getattr(page, "exists", lambda: False)():
                    continue
                page_text = _page_text(page)
                similarity = calculate_content_similarity(topic_text, page_text)
                page_type = classify_page_type(page.title, page_text)
                enrichment[skill] = {
                    "page_type": page_type,
                    "topic_similarity": similarity,
                    "topic_page_type": topic_type,
                    "relevance_label": _relevance_label(similarity),
                    "relationship_hint": _relationship_from_types(topic_type, page_type, similarity),
                    "summary": (page_text[:250] if page_text else ""),
                }
            except Exception as exc:
                print(f"[Wikipedia][WARN] セマンティック情報取得に失敗しました: {skill} ({exc})")
                continue
        return enrichment
    except Exception as exc:
        print(f"[Wikipedia][WARN] セマンティック情報取得に失敗しました: {exc}")
        return {}


def get_important_skills(topic: str, max_skills: int | None = 100, wiki: Any | None = None) -> list[str]:
    """
    トピック候補をできるだけ広く集めたうえで、
    本文量・被リンク・類似度で重要スキルを返す。
    """
    try:
        print(f"[Wikipedia] 重要スキルを取得中: {topic}")
        wiki = wiki or _create_wiki()
        raw_skills, root_text = get_all_links(topic, wiki=wiki)
        if not raw_skills:
            return []
        raw_link_map = get_link_map(raw_skills, wiki=wiki)
        combined_link_map = dict(raw_link_map)
        combined_link_map[topic] = set(raw_skills)
        filtered = filter_skills(raw_skills, root_text, combined_link_map, wiki=wiki)
        if not filtered:
            print("[Wikipedia] フィルタ後の候補が空のため、基本候補を使用します")
            filtered = [skill for skill in raw_skills if _is_content_title(skill)]
        if max_skills is not None:
            filtered = filtered[:max_skills]
        return filtered
    except Exception as exc:
        print(f"[Wikipedia][WARN] 重要スキル取得に失敗しました: {exc}")
        return []
