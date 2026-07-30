from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from ..models.graph_models import KnowledgeEdge, KnowledgeGraph, KnowledgeNode
except ImportError:  # pragma: no cover
    from src.models.graph_models import KnowledgeEdge, KnowledgeGraph, KnowledgeNode


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:latest")

_NODE_TYPES = {"FOUNDATIONAL", "BASIC", "CORE", "APPLICATION"}
_JSON_RETRY_MESSAGE = "前回の出力はJSON解析に失敗しました。\nJSONオブジェクトのみを出力してください。\n他の文字は一切含めないでください。"


def call_ollama(prompt: str, model: str, stream_callback: Any | None = None) -> str:
    """Ollama API をストリーミングで呼び出す。"""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate",
            json={"model": model, "prompt": prompt, "stream": True},
            stream=True,
        )
        response.raise_for_status()
        chunks: list[str] = []
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            token = str(payload.get("response", "") or "")
            if token:
                chunks.append(token)
                if stream_callback is not None:
                    stream_callback(token)
        return "".join(chunks).strip()
    except Exception as exc:
        print(f"[Ollama][WARN] 呼び出しに失敗しました: {exc}")
        return ""


def parse_json_response(response: str) -> dict[str, Any]:
    """LLM 出力から JSON を抽出してパースする。"""
    text = str(response or "").strip()
    if not text:
        raise ValueError("empty response")

    fenced = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("response is not a JSON object")
    return parsed


def _call_json_object(
    prompt: str,
    model: str,
    stream_callback: Any | None = None,
    attempts: int = 3,
) -> tuple[dict[str, Any], str]:
    last_error: Exception | None = None
    current_prompt = prompt
    for attempt in range(1, attempts + 1):
        print(f"[Ollama] JSON生成中: {model} (attempt {attempt}/{attempts})")
        raw_response = call_ollama(current_prompt, model=model, stream_callback=stream_callback)
        if not raw_response:
            last_error = ValueError("empty response")
        else:
            try:
                return parse_json_response(raw_response), raw_response
            except Exception as exc:
                last_error = exc
                print(f"[Ollama][WARN] JSON解析に失敗しました: {exc}")
        if attempt < attempts:
            current_prompt = prompt + "\n\n" + _JSON_RETRY_MESSAGE
    if last_error is not None:
        raise last_error
    raise ValueError("JSON generation failed")


def _clamp_float(value: Any, minimum: float = 0.0, maximum: float = 1.0, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except Exception:
        return default
    return max(minimum, min(maximum, numeric))


def _normalize_layer(value: Any) -> int:
    try:
        layer = int(value)
    except Exception:
        layer = 0
    return max(0, min(3, layer))


def _normalize_node_type(value: Any) -> str:
    candidate = str(value or "CORE").strip().upper()
    return candidate if candidate in _NODE_TYPES else "CORE"


def _normalize_node_id(label: str, index: int) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", str(label)).strip("_")
    if not cleaned:
        cleaned = f"N{index}"
    if not re.match(r"^[A-Za-z_]", cleaned):
        cleaned = f"N{index}_{cleaned}"
    return cleaned[:64]


def _topic_prompt(topic: str, candidate_skills: list[str], extra_instruction: str = "") -> str:
    extra = f"\n{extra_instruction}\n" if extra_instruction else ""
    return f"""
あなたは教育設計の専門家です。
「{topic}」を完全に理解するための
学習ナレッジグラフを作成してください。

参考として以下の関連ワードリストがあります。
学習に必要なものだけを選び、
不足があれば追加してください。

関連ワードリスト：
{json.dumps(candidate_skills, ensure_ascii=False)}

## 厳守するルール

1. ノード数は15〜25個に絞る

2. 含めるノードは「学習して習得できる概念・スキル」のみ
   含めてはいけないもの：
   ・人名（ニュートン・パスカルなど歴史上の人物）
   ・教科書・書籍名
   ・識別子（ISBN・DOIなど）
   ・WebサービスやURLなど
   ・言語名（英語・アラビア語など）

3. layerは0〜3の整数のみ
   layer 0：このトピックより前に学ぶ前提知識
   layer 1：基礎概念
   layer 2：中核概念（このトピックの本質）
   layer 3：応用・発展

4. エッジの方向は教育的な依存関係のみ
   「AがなければBが学べない」場合のみ
   source=A, target=Bとする
   Wikipediaのリンク関係は無視する

5. 全エッジにweightを付ける
   必須の依存: 0.8〜1.0
   あると望ましい: 0.4〜0.7
   参考程度: 0.1〜0.3

JSONのみ出力。
前置き・説明・```json などの記号は不要。

出力形式：
{{
  "nodes": [
    {{
      "node_id": "英数字とアンダースコアのみ（例：N1_VARIABLE）",
      "label": "スキル名（日本語可）",
      "type": "FOUNDATIONAL | BASIC | CORE | APPLICATION",
      "layer": 0〜3の整数,
      "description": "このスキルの説明（50字以内）",
      "prerequisites": ["前提ノードIDのリスト"]
    }}
  ],
  "edges": [
    {{
      "source_id": "前提ノードID",
      "target_id": "学習先ノードID",
      "relationship": "依存関係の種類",
      "weight": 0.0〜1.0,
      "description": "なぜこの依存関係があるか"
    }}
  ]
}}
{extra}""".strip()


def _research_plan_prompt(user_request: str) -> str:
    return f"""
あなたは教育設計と情報収集の専門家です。
以下の文章を読み、学習ナレッジグラフ生成のための調査計画を作成してください。

入力文：
{user_request}

## 目的
この入力文に含まれる学習したい内容、前提知識、周辺概念、比較対象、応用先を分解し、
Wikipediaで調査すべき観点を複数抽出してください。

## 厳守するルール
1. JSONのみ出力する
2. seed_terms は Wikipedia で調べるための短い名詞句を 5〜10 個入れる
3. seed_terms は重複させない
4. 具体的すぎる固有名詞だけでなく、上位概念も含める
5. 人名、書籍名、URL、識別子は seed_terms に入れない
6. 文章全体の意図を 1 行で要約する

出力形式：
{{
  "normalized_topic": "入力文を代表する短い題名",
  "intent_summary": "この文章から読み取れる学習意図の要約",
  "study_goal": "最終的に学びたいことの説明",
  "research_angles": [
    "調べるべき観点1",
    "調べるべき観点2"
  ],
  "seed_terms": [
    "Wikipediaで調べるための語1",
    "Wikipediaで調べるための語2"
  ],
  "must_include": [
    "必要なら含めたい語"
  ],
  "must_exclude": [
    "除外したい語"
  ],
  "complexity_hint": "basic | intermediate | advanced"
}}
""".strip()


def build_research_plan_with_llm(
    user_request: str,
    model: str = OLLAMA_MODEL,
    stream_callback: Any | None = None,
) -> dict[str, Any]:
    prompt = _research_plan_prompt(user_request)
    parsed, _ = _call_json_object(prompt, model=model, stream_callback=stream_callback, attempts=3)
    normalized_topic = str(parsed.get("normalized_topic") or user_request).strip()
    intent_summary = str(parsed.get("intent_summary") or "").strip()
    study_goal = str(parsed.get("study_goal") or "").strip()
    research_angles = [str(item).strip() for item in parsed.get("research_angles", []) if str(item).strip()]
    seed_terms = [str(item).strip() for item in parsed.get("seed_terms", []) if str(item).strip()]
    must_include = [str(item).strip() for item in parsed.get("must_include", []) if str(item).strip()]
    must_exclude = [str(item).strip() for item in parsed.get("must_exclude", []) if str(item).strip()]
    complexity_hint = str(parsed.get("complexity_hint") or "intermediate").strip().lower()
    if complexity_hint not in {"basic", "intermediate", "advanced"}:
        complexity_hint = "intermediate"
    if not seed_terms:
        seed_terms = [normalized_topic]
    return {
        "normalized_topic": normalized_topic,
        "intent_summary": intent_summary,
        "study_goal": study_goal,
        "research_angles": research_angles,
        "seed_terms": list(dict.fromkeys(seed_terms))[:10],
        "must_include": list(dict.fromkeys(must_include))[:10],
        "must_exclude": list(dict.fromkeys(must_exclude))[:10],
        "complexity_hint": complexity_hint,
    }


def _build_prompt(
    topic: str,
    candidate_skills: list[str],
    extra_instruction: str = "",
    research_context: dict[str, Any] | None = None,
) -> str:
    prompt = _topic_prompt(topic, candidate_skills, extra_instruction=extra_instruction)
    if not research_context:
        return prompt
    context_block = json.dumps(research_context, ensure_ascii=False, indent=2)
    return (
        prompt
        + "\n\n## 入力文の解釈結果\n"
        + "この情報を優先してグラフを構成してください。\n"
        + context_block
    )


def _node_aliases(node: KnowledgeNode) -> set[str]:
    return {node.node_id, node.label, _normalize_node_id(node.label, 1)}


def _build_graph(parsed: dict[str, Any], topic: str, candidate_skills: list[str], raw_response: str, model: str) -> KnowledgeGraph:
    node_entries = parsed.get("nodes", [])
    edge_entries = parsed.get("edges", [])
    if not isinstance(node_entries, list) or not isinstance(edge_entries, list):
        raise ValueError("invalid graph structure")

    nodes: list[KnowledgeNode] = []
    alias_map: dict[str, str] = {}
    seen_node_ids: set[str] = set()

    for index, item in enumerate(node_entries, start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("node_id") or "").strip()
        if not label:
            continue
        node_id = str(item.get("node_id") or _normalize_node_id(label, index))
        node_id = re.sub(r"[^0-9A-Za-z_]+", "_", node_id).strip("_") or _normalize_node_id(label, index)
        if not re.match(r"^[A-Za-z_]", node_id):
            node_id = f"N{index}_{node_id}"
        if node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        alias_map[node_id] = node_id
        alias_map[label] = node_id

        node = KnowledgeNode(
            node_id=node_id,
            label=label,
            type=_normalize_node_type(item.get("type")),
            layer=_normalize_layer(item.get("layer", 0)),
            description=str(item.get("description") or "")[:50],
            prerequisites=[re.sub(r"[^0-9A-Za-z_]+", "_", str(pid)).strip("_") for pid in item.get("prerequisites", []) if str(pid).strip()],
            mastery=0.0,
            hesitation_score=0.0,
            cognitive_load_history=[],
            next_review=date.today().isoformat(),
            review_count=0,
        )
        nodes.append(node)

    for node in nodes:
        resolved_prereqs: list[str] = []
        for prerequisite in node.prerequisites:
            raw = str(prerequisite or "").strip()
            if not raw:
                continue
            normalized = re.sub(r"[^0-9A-Za-z_]+", "_", raw).strip("_")
            resolved = alias_map.get(raw) or alias_map.get(normalized) or normalized
            if resolved and resolved not in resolved_prereqs:
                resolved_prereqs.append(resolved)
        node.prerequisites = resolved_prereqs

    edges: list[KnowledgeEdge] = []
    seen_edges: set[str] = set()
    node_id_set = {node.node_id for node in nodes}

    def resolve(identifier: Any) -> str:
        raw = str(identifier or "").strip()
        if not raw:
            return ""
        if raw in alias_map:
            return alias_map[raw]
        normalized = re.sub(r"[^0-9A-Za-z_]+", "_", raw).strip("_")
        return alias_map.get(normalized, normalized)

    for item in edge_entries:
        if not isinstance(item, dict):
            continue
        source_id = resolve(item.get("source_id") or item.get("from"))
        target_id = resolve(item.get("target_id") or item.get("to"))
        if not source_id or not target_id:
            continue
        if source_id not in node_id_set or target_id not in node_id_set:
            continue
        edge_id = f"{source_id}__{target_id}"
        if edge_id in seen_edges:
            continue
        seen_edges.add(edge_id)
        edges.append(
            KnowledgeEdge(
                edge_id=edge_id,
                source_id=source_id,
                target_id=target_id,
                relationship=str(item.get("relationship") or "dependency"),
                weight=_clamp_float(item.get("weight", 1.0), 0.0, 1.0, default=1.0),
                description=str(item.get("description") or "")[:120],
            )
        )

    if not nodes:
        raise ValueError("no nodes parsed")

    graph = KnowledgeGraph(
        graph_id=str(uuid4()),
        topic=topic,
        nodes=nodes,
        edges=edges,
        meta={
            "total_skills": len(nodes),
            "layer_0": sum(1 for node in nodes if node.layer == 0),
            "layer_1": sum(1 for node in nodes if node.layer == 1),
            "layer_2": sum(1 for node in nodes if node.layer == 2),
            "layer_3": sum(1 for node in nodes if node.layer == 3),
        },
    )
    return graph


def _serialize_graph(graph: KnowledgeGraph) -> dict[str, Any]:
    nodes = [
        {
            "node_id": node.node_id,
            "label": node.label,
            "type": node.type,
            "layer": node.layer,
            "description": node.description,
            "prerequisites": list(node.prerequisites),
            "mastery": node.mastery,
            "hesitation_score": node.hesitation_score,
            "cognitive_load_history": list(node.cognitive_load_history),
            "next_review": node.next_review,
            "review_count": node.review_count,
        }
        for node in graph.nodes
    ]
    edges = [
        {
            "edge_id": edge.edge_id,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "relationship": edge.relationship,
            "weight": edge.weight,
            "description": edge.description,
        }
        for edge in graph.edges
    ]
    return {
        "graph_id": graph.graph_id,
        "topic": graph.topic,
        "created_at": graph.created_at,
        "updated_at": graph.updated_at,
        "nodes": nodes,
        "edges": edges,
        "meta": dict(graph.meta or {}),
    }


def build_graph_with_llm(
    topic: str,
    candidate_skills: list[str],
    search_volumes: dict[str, int] | None = None,
    model: str = OLLAMA_MODEL,
    stream_callback: Any | None = None,
    extra_instruction: str = "",
    research_context: dict[str, Any] | None = None,
) -> KnowledgeGraph:
    """gemma4 の JSON だけを最終グラフとして採用する。"""
    _ = search_volumes  # retained for compatibility with existing callers
    base_prompt = _build_prompt(
        topic,
        candidate_skills,
        extra_instruction=extra_instruction,
        research_context=research_context,
    )
    parsed, raw_response = _call_json_object(base_prompt, model=model, stream_callback=stream_callback, attempts=3)
    return _build_graph(parsed, topic, candidate_skills, raw_response, model)
