from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

try:
    import networkx as nx
except Exception:  # pragma: no cover - dependency fallback for constrained envs
    nx = None

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - dependency fallback for constrained envs
    BaseModel = None
    Field = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "output" / "knowledge_graph.json"


if BaseModel is not None:

    class NodeModel(BaseModel):
        node_id: str
        label: str
        type: str = "concept"
        difficulty_score: float = Field(ge=0.0, le=1.0)
        mastery: float = Field(default=0.0, ge=0.0, le=1.0)
        layer: int = Field(default=0, ge=0)
        description: str = ""
        prerequisites: list[str] = Field(default_factory=list)
        hesitation_score: float = Field(default=0.0, ge=0.0, le=1.0)
        cognitive_load_history: list[float] = Field(default_factory=list)
        next_review: str = Field(default_factory=lambda: date.today().isoformat())
        review_count: int = Field(default=0, ge=0)
        semantic: dict[str, Any] = Field(default_factory=dict)

    class EdgeModel(BaseModel):
        from_: str = Field(alias="from")
        to: str
        weight: float = Field(default=1.0, ge=0.0)
        relationship: str = "prerequisite"
        description: str = ""
        semantic: dict[str, Any] = Field(default_factory=dict)


def _dump_model(model: Any) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True)
    return model.dict(by_alias=True)


def build_nodes(
    skills: list[str],
    search_volumes: dict[str, int],
    semantic_enrichment: dict[str, dict[str, Any]] | None = None,
) -> list[dict]:
    """
    スキルをノードに変換する。
    search_volumeを0〜1に正規化してdifficulty_scoreとして使う。
    mastery は全て0.0で初期化する。
    """
    try:
        print(f"[Graph] ノードを生成中: {len(skills)}件")
        unique_skills = list(dict.fromkeys(skills))
        max_volume = max([search_volumes.get(skill, 0) for skill in unique_skills] or [0])
        nodes: list[dict] = []
        for skill in unique_skills:
            volume = max(0, int(search_volumes.get(skill, 0)))
            difficulty = round(volume / max_volume, 4) if max_volume > 0 else 0.0
            node = {
                "node_id": skill,
                "label": skill,
                "difficulty_score": difficulty,
                "mastery": 0.0,
                "layer": 0,
            }
            if semantic_enrichment:
                semantic = dict(semantic_enrichment.get(skill, {}))
                node.update(
                    {
                        "type": str(semantic.get("page_type", "concept")),
                        "description": str(semantic.get("summary", ""))[:250],
                        "prerequisites": list(dict.fromkeys(semantic.get("prerequisites", []) or [])),
                        "hesitation_score": float(semantic.get("hesitation_score", 0.0) or 0.0),
                        "cognitive_load_history": list(semantic.get("cognitive_load_history", []) or []),
                        "next_review": str(semantic.get("next_review", date.today().isoformat())),
                        "review_count": int(semantic.get("review_count", 0) or 0),
                        "semantic": semantic,
                    }
                )
            if BaseModel is not None:
                node = _dump_model(NodeModel(**node))
            nodes.append(node)
        return nodes
    except Exception as exc:
        print(f"[Graph][WARN] ノード生成に失敗しました: {exc}")
        return []


def build_edges(
    skills: list[str],
    link_map: dict[str, set[str]],
    semantic_enrichment: dict[str, dict[str, Any]] | None = None,
) -> list[dict]:
    """
    スキル間のリンク関係からエッジを生成する。
    AのページがBにリンクしている場合、
    「BはAの前提知識」としてエッジを作る。
    スキルリスト内のスキル間のエッジのみ生成する。
    """
    try:
        print("[Graph] エッジを生成中")
        skill_set = set(skills)
        seen: set[tuple[str, str]] = set()
        edges: list[dict] = []
        for later_skill, links in link_map.items():
            if later_skill not in skill_set:
                continue
            for prerequisite in links:
                if prerequisite == later_skill or prerequisite not in skill_set:
                    continue
                key = (prerequisite, later_skill)
                if key in seen:
                    continue
                edge = {"from": prerequisite, "to": later_skill, "weight": 1.0}
                if semantic_enrichment:
                    source_meta = semantic_enrichment.get(prerequisite, {})
                    target_meta = semantic_enrichment.get(later_skill, {})
                    similarity = max(
                        float(source_meta.get("topic_similarity", 0.0) or 0.0),
                        float(target_meta.get("topic_similarity", 0.0) or 0.0),
                    )
                    edge.update(
                        {
                            "weight": round(min(1.0, 0.55 + similarity), 4),
                            "relationship": str(
                                target_meta.get("relationship_hint")
                                or source_meta.get("relationship_hint")
                                or "prerequisite"
                            ),
                            "description": f"{prerequisite} -> {later_skill} の依存関係",
                            "semantic": {
                                "relatedness": round(similarity, 4),
                                "source_type": source_meta.get("page_type", "concept"),
                                "target_type": target_meta.get("page_type", "concept"),
                                "relevance_label": target_meta.get("relevance_label", "low"),
                            },
                        }
                    )
                if BaseModel is not None and semantic_enrichment is not None:
                    edge = _dump_model(EdgeModel(**edge))
                edges.append(edge)
                seen.add(key)
        print(f"[Graph] エッジ生成完了: {len(edges)}件")
        return edges
    except Exception as exc:
        print(f"[Graph][WARN] エッジ生成に失敗しました: {exc}")
        return []


def _assign_layers_fallback(nodes: list[dict], edges: list[dict]) -> list[dict]:
    node_ids = [node["node_id"] for node in nodes]
    layers = {node_id: 0 for node_id in node_ids}
    valid_edges = [(edge["from"], edge["to"]) for edge in edges if edge["from"] in layers and edge["to"] in layers]
    for _ in range(len(node_ids)):
        changed = False
        for source, target in valid_edges:
            next_layer = layers[source] + 1
            if layers[target] < next_layer:
                layers[target] = next_layer
                changed = True
        if not changed:
            break
    for node in nodes:
        node["layer"] = layers.get(node["node_id"], 0)
    return nodes


def assign_layers(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """
    NetworkXのトポロジカルソートを使って
    各ノードのlayerを自動計算する。
    前提ノードがないものはlayer=0。
    循環依存が発生した場合はそのエッジを除外して処理を続ける。
    """
    try:
        print("[Graph] レイヤーを計算中")
        if nx is None:
            print("[Graph][WARN] networkxが未導入のためフォールバックで計算します")
            return _assign_layers_fallback(nodes, edges)

        graph = nx.DiGraph()
        graph.add_nodes_from(node["node_id"] for node in nodes)
        graph.add_edges_from((edge["from"], edge["to"]) for edge in edges)

        while not nx.is_directed_acyclic_graph(graph):
            cycle = nx.find_cycle(graph)
            source, target = cycle[-1][:2]
            graph.remove_edge(source, target)
            print(f"[Graph][WARN] 循環依存を除外: {source} -> {target}")

        layers = {node_id: 0 for node_id in graph.nodes}
        for node_id in nx.topological_sort(graph):
            predecessors = list(graph.predecessors(node_id))
            if predecessors:
                layers[node_id] = max(layers[pred] + 1 for pred in predecessors)

        for node in nodes:
            node["layer"] = int(layers.get(node["node_id"], 0))
        return nodes
    except Exception as exc:
        print(f"[Graph][WARN] レイヤー計算に失敗しました: {exc}")
        return nodes


def save_graph(nodes: list[dict], edges: list[dict], topic: str) -> None:
    """
    ノードとエッジをoutput/knowledge_graph.jsonに保存する。
    """
    try:
        print(f"[Graph] JSONへ保存中: {OUTPUT_PATH}")
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        graph = {
            "topic": topic,
            "nodes": nodes,
            "edges": edges,
            "refinement": [],
        }
        OUTPUT_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[Graph] 保存完了")
    except Exception as exc:
        print(f"[Graph][WARN] 保存に失敗しました: {exc}")
