from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from .gemma_graph_builder import build_graph_with_llm, build_research_plan_with_llm, _serialize_graph
    from .trends_collector import get_search_volumes
    from .wikipedia_collector import _create_wiki, get_important_skills
except ImportError:  # pragma: no cover
    from gemma_graph_builder import build_graph_with_llm, build_research_plan_with_llm, _serialize_graph
    from trends_collector import get_search_volumes
    from wikipedia_collector import _create_wiki, get_important_skills


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "graphs"
LEGACY_OUTPUT_PATH = PROJECT_ROOT / "output" / "knowledge_graph.json"


def _sanitize_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-", " "} else "_" for ch in value).strip()
    cleaned = "_".join(part for part in cleaned.split() if part)
    return cleaned or "graph"


def _group_by_layer(nodes: list[dict[str, Any]]) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = defaultdict(list)
    for node in nodes:
        try:
            layer = int(node.get("layer", 0) or 0)
        except Exception:
            layer = 0
        layer = max(0, min(3, layer))
        grouped[layer].append(str(node.get("label") or node.get("node_id") or ""))
    return grouped


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if str(item).strip()))


def print_summary(topic: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], saved_path: Path) -> None:
    grouped = _group_by_layer(nodes)
    print("===============================")
    print(f"トピック: {topic}")
    print(f"ノード数: {len(nodes)}")
    print(f"エッジ数: {len(edges)}")
    print(f"Layer 0（前提）: {', '.join(grouped.get(0, []))}")
    print(f"Layer 1（基礎）: {', '.join(grouped.get(1, []))}")
    print(f"Layer 2（中核）: {', '.join(grouped.get(2, []))}")
    print(f"Layer 3（応用）: {', '.join(grouped.get(3, []))}")
    print(f"保存先: {saved_path}")
    print("===============================")


def _collect_candidate_skills(
    topic: str,
    research_plan: dict[str, Any],
    wiki: Any,
) -> list[str]:
    seed_terms = _dedupe(
        [topic]
        + list(research_plan.get("seed_terms", []))
        + list(research_plan.get("must_include", []))
    )
    if not seed_terms:
        seed_terms = [topic]

    candidate_skills: list[str] = []
    per_seed_limit = 35
    for seed in seed_terms[:8]:
        try:
            skills = get_important_skills(seed, max_skills=per_seed_limit, wiki=wiki)
            candidate_skills.extend(skills)
        except Exception as exc:
            print(f"[Pipeline][WARN] seed_term の収集に失敗しました: {seed} ({exc})")

    if not candidate_skills:
        candidate_skills = get_important_skills(topic, max_skills=100, wiki=wiki)

    candidate_skills = _dedupe(candidate_skills)
    if research_plan.get("must_exclude"):
        exclusions = {str(item).strip() for item in research_plan.get("must_exclude", []) if str(item).strip()}
        candidate_skills = [skill for skill in candidate_skills if skill not in exclusions]
    return candidate_skills[:180]


def _generate_payload(
    topic: str,
    stream_callback: Any | None = None,
    extra_instruction: str = "",
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    wiki = _create_wiki()
    research_plan = build_research_plan_with_llm(topic, stream_callback=stream_callback)
    candidate_skills = _collect_candidate_skills(topic, research_plan, wiki)
    search_volumes = get_search_volumes(candidate_skills)
    graph = build_graph_with_llm(
        topic=topic,
        candidate_skills=candidate_skills,
        search_volumes=search_volumes,
        stream_callback=stream_callback,
        extra_instruction=extra_instruction,
        research_context=research_plan,
    )
    payload = _serialize_graph(graph)
    return payload, graph, research_plan


def generate_knowledge_graph(topic: str = "Python プログラミング", stream_callback: Any | None = None) -> dict[str, Any]:
    try:
        print(f"[Pipeline] トピック: {topic}")
        payload, graph, research_plan = _generate_payload(topic, stream_callback=stream_callback)

        if len(payload.get("nodes", [])) > 25:
            print("警告：ノード数が多すぎます。gemma4に再度絞り込みを依頼します。")
            payload, graph, research_plan = _generate_payload(
                topic,
                stream_callback=stream_callback,
                extra_instruction="ノード数が多すぎます。必ず20個以下に絞ってください。",
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{_sanitize_filename(topic)}_{timestamp}.json"
        output_path = OUTPUT_DIR / filename
        _write_json(output_path, payload)
        _write_json(LEGACY_OUTPUT_PATH, payload)
        print_summary(topic, payload.get("nodes", []), payload.get("edges", []), output_path)

        return {
            "topic": topic,
            "nodes": payload.get("nodes", []),
            "edges": payload.get("edges", []),
            "research_plan": research_plan,
            "summary": {
                "node_count": len(payload.get("nodes", [])),
                "edge_count": len(payload.get("edges", [])),
            },
            "meta": payload.get("meta", {}),
            "output_path": str(output_path.relative_to(PROJECT_ROOT)),
        }
    except Exception as exc:
        print(f"[Pipeline][WARN] 処理に失敗しました: {exc}")
        return {
            "topic": topic,
            "nodes": [],
            "edges": [],
            "summary": {
                "node_count": 0,
                "edge_count": 0,
            },
            "error": str(exc),
        }


def main() -> None:
    try:
        topic = sys.argv[1] if len(sys.argv) > 1 else "Python プログラミング"
        generate_knowledge_graph(topic)
    except Exception as exc:
        print(f"[Pipeline][WARN] 処理に失敗しました: {exc}")


if __name__ == "__main__":
    main()
