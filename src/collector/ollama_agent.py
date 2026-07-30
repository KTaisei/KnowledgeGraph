from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from collections import Counter

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from .wikipedia_collector import get_related_skills, get_semantic_enrichment
except ImportError:  # pragma: no cover
    from wikipedia_collector import get_related_skills, get_semantic_enrichment


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_MODELS = ["llama3.2:latest"]


def _import_wikipedia_helpers() -> tuple[Any, Any, Any]:
    try:
        from .wikipedia_collector import _create_wiki, _page_text, _resolve_page
        return _create_wiki, _page_text, _resolve_page
    except ImportError:
        from wikipedia_collector import _create_wiki, _page_text, _resolve_page
        return _create_wiki, _page_text, _resolve_page


def call_ollama(prompt: str, model: str = "llama3.2", stream_callback: Any | None = None) -> str:
    """Ollama のローカル API を呼び出す。タイムアウトなしでストリーミング受信する。"""
    try:
        chunks: list[str] = []
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": True, "options": {"temperature": 0.2, "num_predict": 100}},
            stream=True,
        )
        response.raise_for_status()
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
    except requests.exceptions.ConnectionError as exc:
        print(f"[Ollama][WARN] Ollamaサーバーに接続できませんでした: {exc}")
        return ""
    except Exception as exc:
        print(f"[Ollama][WARN] 呼び出しに失敗しました: {exc}")
        return ""


def build_refinement_plan(raw_response: str) -> dict[str, Any]:
    """Ollama の応答から検索語・対象ノード・理由を抽出する。"""
    try:
        parsed = json.loads(raw_response)
        if isinstance(parsed, dict):
            return {
                "search_terms": [str(term).strip() for term in parsed.get("search_terms", []) if str(term).strip()],
                "focus_nodes": [str(term).strip() for term in parsed.get("focus_nodes", []) if str(term).strip()],
                "reason": str(parsed.get("reason", "refine graph")),
            }
    except Exception:
        pass

    try:
        terms = re.findall(r'"([^"]+)"', raw_response)
        return {"search_terms": terms[:3], "focus_nodes": [], "reason": raw_response[:100]}
    except Exception:
        return {"search_terms": [], "focus_nodes": [], "reason": "refine graph"}


def search_wikipedia_terms(search_terms: list[str]) -> list[tuple[str, str]]:
    """Wikipedia API への検索を行い、候補ページと要約を返す。"""
    results: list[tuple[str, str]] = []
    for term in search_terms:
        try:
            _create_wiki, _page_text, _resolve_page = _import_wikipedia_helpers()
            wiki = _create_wiki()
            page = _resolve_page(wiki, term)
            if page.exists():
                results.append((page.title, _page_text(page)))
        except Exception as exc:
            print(f"[Ollama][WARN] Wikipedia検索に失敗しました: {term} ({exc})")
    return results


def _build_prompt(topic: str, nodes: list[dict], edges: list[dict], skills: list[str]) -> str:
    return f"""
あなたは学習ロードマップ作成のためのナレッジグラフ設計者です。
トピック: {topic}
既存ノード: {', '.join(node.get('node_id', '') for node in nodes[:15])}
候補スキル: {', '.join(skills[:15])}

学習の順番を考えるために、まず最初に理解すべき前提単元・関連単元を提案してください。
できるだけ一般的で中核的な概念を優先し、人物名・地名・組織名・歴史的出来事の追加は最小限にしてください。
次のJSONだけを返してください。
{{"search_terms": ["追加したい検索語の一覧"], "focus_nodes": ["関連付けたい既存ノード名"], "reason": "理由"}}
"""


def build_learning_roadmap(topic: str, nodes: list[dict], edges: list[dict], skills: list[str] | None = None) -> dict[str, Any]:
    """学習ロードマップ向けに前提知識ノードを追加したグラフを返す。"""
    base_nodes = [dict(node) for node in nodes]
    base_edges = [dict(edge) for edge in edges]
    skill_candidates = skills or [node.get("node_id") for node in base_nodes if node.get("node_id")]

    prerequisite_map = {
        "微分積分": ["関数", "極限", "導関数", "積分", "微分方程式"],
        "線形代数": ["行列", "ベクトル", "連立方程式", "次元", "固有値"],
        "機械学習": ["線形代数", "確率統計", "最適化", "微分積分", "プログラミング"],
        "統計学": ["確率", "データ分析", "仮説検定", "回帰分析", "確率分布"],
        "プログラミング": ["変数", "関数", "制御構文", "データ構造", "アルゴリズム"],
    }

    prereq_terms = prerequisite_map.get(topic, [])
    if not prereq_terms:
        prereq_terms = [term for term in skill_candidates if term and term != topic][:3]

    seen = {node["node_id"] for node in base_nodes if node.get("node_id")}
    for term in prereq_terms:
        if term in seen:
            continue
        seen.add(term)
        base_nodes.append({
            "node_id": term,
            "label": term,
            "difficulty_score": 0.35,
            "mastery": 0.0,
            "layer": 0,
            "semantic": {
                "page_type": "concept",
                "topic_similarity": 0.35,
                "relevance_label": "high",
                "summary": f"{topic} の学習に必要な前提単元として推奨される内容",
                "reason": "learning-roadmap",
            },
        })
        if topic not in seen:
            base_edges.append({
                "from": term,
                "to": topic,
                "weight": 1.4,
                "semantic": {"relatedness": 0.35, "relevance_label": "high", "source": "roadmap"},
            })
        else:
            base_edges.append({
                "from": term,
                "to": topic,
                "weight": 1.4,
                "semantic": {"relatedness": 0.35, "relevance_label": "high", "source": "roadmap"},
            })

    return {"nodes": base_nodes, "edges": base_edges, "refinement": [{"model": "roadmap-rule", "title": term, "summary": f"{topic} 学習前提", "reason": "prerequisite"} for term in prereq_terms]}


def refine_graph_with_ollama(
    topic: str,
    nodes: list[dict],
    edges: list[dict],
    skills: list[str] | None = None,
    models: list[str] | None = None,
    stream_callback: Any | None = None,
) -> dict[str, Any]:
    """複数のローカル LLM で議論し、検索語候補と新規ノードを提案する。"""
    models = models or DEFAULT_MODELS
    existing_nodes = list(nodes)
    existing_edges = list(edges)
    skill_candidates = skills or [node.get("node_id") for node in existing_nodes if node.get("node_id")]

    if not skill_candidates:
        return {"nodes": existing_nodes, "edges": existing_edges, "refinement": []}

    all_proposals: list[dict[str, Any]] = []
    for model in models:
        prompt = _build_prompt(topic, existing_nodes, existing_edges, skill_candidates)
        raw_response = call_ollama(prompt, model=model, stream_callback=stream_callback)
        if not raw_response:
            continue
        plan = build_refinement_plan(raw_response)
        if not plan.get("search_terms"):
            continue
        discovered = search_wikipedia_terms(plan["search_terms"])
        for title, summary in discovered:
            all_proposals.append({
                "model": model,
                "title": title,
                "summary": summary,
                "reason": plan.get("reason", "refine graph"),
                "focus_nodes": plan.get("focus_nodes", []),
            })

    seen_nodes = {node["node_id"] for node in existing_nodes if node.get("node_id")}
    refined_nodes = [dict(node) for node in existing_nodes]
    refined_edges = [dict(edge) for edge in existing_edges]

    for proposal in all_proposals:
        title = proposal["title"]
        if title in seen_nodes:
            continue
        seen_nodes.add(title)
        refined_nodes.append({
            "node_id": title,
            "label": title,
            "difficulty_score": 0.5,
            "mastery": 0.0,
            "layer": 0,
            "semantic": {
                "page_type": "concept",
                "topic_similarity": 0.2,
                "relevance_label": "medium",
                "summary": proposal["summary"][:150],
                "refined_by": proposal["model"],
                "reason": proposal["reason"],
            },
        })
        for focus_node in proposal.get("focus_nodes") or []:
            if focus_node in {node["node_id"] for node in refined_nodes}:
                refined_edges.append({
                    "from": focus_node,
                    "to": title,
                    "weight": 1.2,
                    "semantic": {
                        "relatedness": 0.2,
                        "relevance_label": "medium",
                        "source": "ollama-refinement",
                    },
                })

    return {"nodes": refined_nodes, "edges": refined_edges, "refinement": all_proposals}


def prune_graph_for_learning(topic: str, nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """LLM の提案を元に、学習用途で不要そうなノードを削除し、必要な前提ノードを残す。"""
    filtered_nodes = []
    filtered_edges = []
    node_ids = {node.get("node_id") for node in nodes if node.get("node_id")}
    for node in nodes:
        node_id = node.get("node_id")
        if not node_id:
            continue
        label = str(node.get("label") or node_id)
        text = f"{topic} {label}".lower()
        should_keep = True
        if any(keyword in text for keyword in ["年", "年代", "人物", "数学者", "名前", "生誕", "没"]):
            if topic in {"微分積分", "線形代数", "統計学", "機械学習", "プログラミング"}:
                should_keep = False
        if should_keep:
            filtered_nodes.append(dict(node))

    kept_ids = {node.get("node_id") for node in filtered_nodes if node.get("node_id")}
    for edge in edges:
        source = edge.get("from")
        target = edge.get("to")
        if source in kept_ids and target in kept_ids:
            filtered_edges.append(dict(edge))

    return {"nodes": filtered_nodes, "edges": filtered_edges, "refinement": [{"model": "pruner", "title": topic, "summary": "不要ノードを除去して学習に直結する構造へ整理", "reason": "prune"}]}


def iteratively_refine_graph(
    topic: str,
    nodes: list[dict],
    edges: list[dict],
    skills: list[str] | None = None,
    iterations: int = 1,
    stream_callback: Any | None = None,
) -> dict[str, Any]:
    """既存グラフを再評価し、除去と追加を行って改善する。"""
    current_nodes = [dict(node) for node in nodes]
    current_edges = [dict(edge) for edge in edges]
    all_refinements: list[dict[str, Any]] = []

    for _ in range(max(1, iterations)):
        pruned = prune_graph_for_learning(topic, current_nodes, current_edges)
        current_nodes = [dict(node) for node in pruned.get("nodes", current_nodes)]
        current_edges = [dict(edge) for edge in pruned.get("edges", current_edges)]
        all_refinements.extend(pruned.get("refinement", []))

        roadmap = build_learning_roadmap(topic, current_nodes, current_edges, skills=skills)
        current_nodes = [dict(node) for node in roadmap.get("nodes", current_nodes)]
        current_edges = [dict(edge) for edge in roadmap.get("edges", current_edges)]
        all_refinements.extend(roadmap.get("refinement", []))

        ollama_refinement = refine_graph_with_ollama(
            topic,
            current_nodes,
            current_edges,
            skills=skills,
            models=DEFAULT_MODELS,
            stream_callback=stream_callback,
        )
        current_nodes = [dict(node) for node in ollama_refinement.get("nodes", current_nodes)]
        current_edges = [dict(edge) for edge in ollama_refinement.get("edges", current_edges)]
        all_refinements.extend(ollama_refinement.get("refinement", []))

    return {"nodes": current_nodes, "edges": current_edges, "refinement": all_refinements}


def _normalize_text(text: str) -> str:
    return re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+", " ", str(text).lower()).strip()


def _classify_difficulty(node: dict[str, Any], index: int, total: int) -> str:
    difficulty_score = float(node.get("difficulty_score", 0.0) or 0.0)
    layer = int(node.get("layer", 0) or 0)
    if difficulty_score >= 0.7 or layer >= 2:
        return "advanced"
    if difficulty_score < 0.35 and layer <= 0 and index == 0:
        return "basic"
    return "intermediate"


def _estimate_required_nodes(target_node_id: str, nodes: list[dict], edges: list[dict]) -> list[str]:
    node_map = {str(node.get("node_id") or ""): node for node in nodes if node.get("node_id")}
    prerequisite_ids = [str(edge.get("from") or "") for edge in edges if str(edge.get("to") or "") == target_node_id and edge.get("from")]
    prerequisite_ids = [node_id for node_id in prerequisite_ids if node_id in node_map and node_id != target_node_id]
    if prerequisite_ids:
        return prerequisite_ids[:2]

    target_node = node_map.get(target_node_id, {})
    target_layer = int(target_node.get("layer", 0) or 0)
    target_difficulty = float(target_node.get("difficulty_score", 0.0) or 0.0)
    candidates = []
    for node in nodes:
        node_id = str(node.get("node_id") or "")
        if not node_id or node_id == target_node_id:
            continue
        node_layer = int(node.get("layer", 0) or 0)
        node_difficulty = float(node.get("difficulty_score", 0.0) or 0.0)
        if node_layer < target_layer or node_difficulty < target_difficulty:
            candidates.append(node_id)
    if not candidates:
        return [str(node.get("node_id") or "") for node in nodes if str(node.get("node_id") or "") and str(node.get("node_id") or "") != target_node_id][:2]
    return candidates[:2]


def generate_understanding_quiz(topic: str, nodes: list[dict], edges: list[dict], stream_callback: Any | None = None) -> dict[str, Any]:
    """ナレッジグラフをもとに、学習内容を測る理解度テストを作る。LLMを利用して問題文を生成する。"""
    quiz_nodes = [node for node in nodes if node.get("node_id")]
    quiz_nodes = sorted(
        quiz_nodes,
        key=lambda node: (
            int(node.get("layer", 0) or 0),
            float(node.get("difficulty_score", 0.0) or 0.0),
            str(node.get("label") or node.get("node_id") or ""),
        ),
    )[:3]

    target_labels = [str(node.get("label") or node.get("node_id") or "") for node in quiz_nodes]
    
    prompt = f"""あなたは学習支援AIです。トピック「{topic}」について、以下のキーワードに関する理解度テストの問題を作成してください。
キーワード: {', '.join(target_labels)}

各問題は、指定されたキーワードを理解しているかを問う内容にし、答えが1つの単語になるような短い問題文にしてください。
出力は必ず以下のJSONフォーマットのみにしてください。
{{"questions": ["キーワード1の問題文", "キーワード2の問題文", "キーワード3の問題文"]}}"""

    raw_response = call_ollama(prompt, model=DEFAULT_MODELS[0], stream_callback=stream_callback)
    
    generated_questions = []
    try:
        parsed = json.loads(raw_response)
        generated_questions = parsed.get("questions", [])
    except Exception:
        pass

    quiz_items = []
    for idx, node in enumerate(quiz_nodes, start=1):
        node_id = str(node.get("node_id") or "")
        label = str(node.get("label") or node_id)
        required_nodes = _estimate_required_nodes(node_id, nodes, edges)
        difficulty = _classify_difficulty(node, idx - 1, len(quiz_nodes))
        
        # フォールバック: LLMの生成が失敗したか足りない場合は固定テンプレートを使う
        question_text = f"{topic}の関連語として「{label}」がありますが、これに関連する重要なキーワードを1つだけ答えてください。"
        if idx - 1 < len(generated_questions) and isinstance(generated_questions[idx - 1], str):
            question_text = generated_questions[idx - 1].strip()

        quiz_items.append({
            "id": idx,
            "question": question_text,
            "expected_keywords": [label] + required_nodes,
            "target_node": node_id,
            "required_nodes": required_nodes,
            "difficulty": difficulty,
        })
    return {"topic": topic, "items": quiz_items}


def score_quiz_answers(quiz: dict[str, Any], answers: list[str]) -> dict[str, Any]:
    """回答を簡易的に採点し、正答率と弱点ノードを返す。"""
    total = max(1, len(quiz.get("items", [])))
    scored = []
    for item, answer in zip(quiz.get("items", []), answers[:total]):
        keywords = [str(keyword) for keyword in item.get("expected_keywords", []) if str(keyword)]
        normalized_answer = _normalize_text(answer)
        matched_keywords = [keyword for keyword in keywords if _normalize_text(keyword) and _normalize_text(keyword) in normalized_answer]
        score = 1.0 if matched_keywords else 0.0
        weak_nodes = []
        if score < 1.0:
            weak_nodes = [str(item.get("target_node") or "")] + [str(node) for node in item.get("required_nodes", []) if str(node)]
        scored.append({
            "id": item.get("id"),
            "score": score,
            "answer": answer,
            "weak_nodes": weak_nodes,
            "difficulty": item.get("difficulty", "basic"),
        })
    accuracy = round(sum(item["score"] for item in scored) / total, 4)
    return {"accuracy": accuracy, "results": scored}


def evaluate_graph_with_quiz(topic: str, nodes: list[dict], edges: list[dict], quiz_model: str = "llama3.2", stream_callback: Any | None = None) -> dict[str, Any]:
    """別モデルに理解度テストを受験させ、点数と依存情報を返す。"""
    quiz = generate_understanding_quiz(topic, nodes, edges, stream_callback=stream_callback)
    prompt = f"次のテストに回答してください。\nトピック: {topic}\n\n" + "\n".join(f"Q{item['id']}: {item['question']}" for item in quiz.get("items", [])) + "\n\n必ず各問ごとにキーワードを1つだけ答えてください。"
    response = call_ollama(prompt, model=quiz_model, stream_callback=stream_callback)
    answers = [line.strip() for line in response.splitlines() if line.strip()]
    if len(answers) < len(quiz.get("items", [])):
        answers = answers + [""] * (len(quiz.get("items", [])) - len(answers))
    score = score_quiz_answers(quiz, answers)

    dependency_scores = []
    for item in quiz.get("items", []):
        target_node = item.get("target_node")
        if not target_node:
            continue
        result = next((entry for entry in score.get("results", []) if entry.get("id") == item.get("id")), None)
        if result and result.get("score", 0.0) < 1.0:
            importance = 0.55
        else:
            importance = 1.0
        dependency_scores.append({"node_id": target_node, "importance": importance})

    return {"quiz": quiz, "score": score, "dependency_scores": dependency_scores}


def refine_graph_using_quiz_results(topic: str, nodes: list[dict], edges: list[dict], quiz_result: dict[str, Any]) -> dict[str, Any]:
    """テスト結果から弱いノードを見つけ、グラフを改善する。"""
    current_nodes = [dict(node) for node in nodes]
    current_edges = [dict(edge) for edge in edges]
    accuracy = quiz_result.get("score", {}).get("accuracy", 0.0)

    if accuracy >= 0.7:
        return {"nodes": current_nodes, "edges": current_edges, "refinement": [{"model": "quiz-evaluator", "title": topic, "summary": "理解度テストで十分な点数を獲得したため、現状維持", "reason": "quiz-pass"}]}

    weak_nodes = []
    for result in quiz_result.get("score", {}).get("results", []):
        weak_nodes.extend(result.get("weak_nodes", []))
    weak_nodes = list(dict.fromkeys([node_id for node_id in weak_nodes if str(node_id)]))

    if weak_nodes:
        for node in current_nodes:
            node_id = str(node.get("node_id") or "")
            if node_id in weak_nodes:
                node.setdefault("semantic", {})["quiz_priority"] = "high"
                node["difficulty_score"] = min(0.99, float(node.get("difficulty_score", 0.0)) + 0.15)

    return {"nodes": current_nodes, "edges": current_edges, "refinement": [{"model": "quiz-evaluator", "title": topic, "summary": f"理解度テストの結果に基づき、弱いノードを優先して強化: {', '.join(weak_nodes)}", "reason": "quiz-improve"}]}


def enhance_graph_with_ollama(
    topic: str,
    nodes: list[dict],
    edges: list[dict],
    skills: list[str] | None = None,
    stream_callback: Any | None = None,
) -> dict[str, Any]:
    """既存のノード・エッジに Ollama 由来の候補をマージし、学習用途で不要なノードを削減し、理解度テストの結果を反映する。"""
    refined = iteratively_refine_graph(topic, nodes, edges, skills=skills, iterations=1, stream_callback=stream_callback)
    quiz_result = evaluate_graph_with_quiz(
        topic,
        refined.get("nodes", nodes),
        refined.get("edges", edges),
        quiz_model="llama3.2",
        stream_callback=stream_callback,
    )
    improved = refine_graph_using_quiz_results(topic, refined.get("nodes", nodes), refined.get("edges", edges), quiz_result)
    improved["refinement"] = refined.get("refinement", []) + improved.get("refinement", []) + [{"model": "quiz-evaluator", "title": topic, "summary": f"理解度テストの正答率: {quiz_result.get('score', {}).get('accuracy', 0.0)}", "reason": "quiz-score"}]
    return improved
