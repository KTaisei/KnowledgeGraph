from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from .pipeline import generate_knowledge_graph
except ImportError:
    from pipeline import generate_knowledge_graph


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = PROJECT_ROOT / "output" / "knowledge_graph.json"
GRAPH_DIR = PROJECT_ROOT / "output" / "graphs"
HOST = "127.0.0.1"
PORT = 8000


HTML = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Knowledge Graph Viewer</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --ink: #17202a;
      --muted: #667085;
      --line: #d9dee7;
      --panel: #ffffff;
      --accent: #1677ff;
      --green: #0f9f6e;
      --orange: #d97706;
      --shadow: 0 14px 42px rgba(20, 32, 48, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      height: 72px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 28px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.9);
      backdrop-filter: blur(14px);
    }
    h1 { margin: 0; font-size: 20px; font-weight: 750; letter-spacing: 0; }
    .topic { color: var(--muted); font-size: 14px; margin-top: 4px; }
    .toolbar { display: flex; gap: 10px; align-items: center; }
    input {
      width: min(34vw, 360px);
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 12px;
      font-size: 14px;
      background: white;
    }
    #topicInput { width: min(28vw, 280px); }
    select {
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 12px;
      font-size: 14px;
      background: white;
      color: var(--ink);
      max-width: min(34vw, 360px);
    }
    button {
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 12px;
      background: white;
      color: var(--ink);
      font-weight: 650;
      cursor: pointer;
    }
    button.primary { background: var(--accent); border-color: var(--accent); color: white; }
    button:disabled { cursor: wait; opacity: 0.62; }
    .status {
      position: absolute;
      left: 18px;
      bottom: 18px;
      max-width: min(520px, calc(100% - 36px));
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      background: rgba(255, 255, 255, 0.94);
      box-shadow: var(--shadow);
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .status strong { color: var(--ink); }
    main {
      display: grid;
      grid-template-columns: 1fr 340px;
      height: calc(100vh - 72px);
      min-height: 560px;
    }
    #canvasWrap { position: relative; overflow: hidden; }
    canvas { width: 100%; height: 100%; display: block; background: #fbfcfe; }
    aside {
      border-left: 1px solid var(--line);
      background: var(--panel);
      padding: 18px;
      overflow: auto;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }
    .stat {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fff;
    }
    .stat b { display: block; font-size: 22px; }
    .stat span { color: var(--muted); font-size: 12px; }
    h2 { font-size: 14px; margin: 18px 0 10px; }
    .layer {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      margin-bottom: 10px;
      background: #fff;
    }
    .layer-title { display: flex; justify-content: space-between; color: var(--muted); font-size: 12px; margin-bottom: 8px; }
    .chip {
      display: inline-block;
      max-width: 100%;
      margin: 3px 4px 3px 0;
      padding: 5px 8px;
      border-radius: 999px;
      background: #eef5ff;
      color: #0f4b8f;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    #details {
      min-height: 96px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fff;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }
    #discussion {
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fff;
      max-height: 260px;
      overflow: auto;
    }
    .discussion-item {
      padding: 8px 0;
      border-bottom: 1px solid #f0f2f5;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.45;
    }
    .discussion-item:last-child { border-bottom: 0; }
    .discussion-item strong { color: var(--ink); }
    #ollamaLive {
      min-height: 96px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fff;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
      white-space: pre-wrap;
      overflow: auto;
      max-height: 240px;
    }
    @media (max-width: 860px) {
      header { height: auto; min-height: 92px; align-items: flex-start; flex-direction: column; gap: 12px; padding: 14px; }
      .toolbar { width: 100%; flex-wrap: wrap; }
      input { flex: 1; width: auto; }
      #topicInput { flex-basis: 100%; width: 100%; }
      main { grid-template-columns: 1fr; height: auto; }
      #canvasWrap { height: 62vh; min-height: 420px; }
      aside { border-left: 0; border-top: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Knowledge Graph Viewer</h1>
      <div class="topic" id="topic">loading...</div>
    </div>
    <div class="toolbar">
      <select id="fileSelect" title="出力JSONを選択"></select>
      <input id="topicInput" placeholder="例: Pythonでデータ分析を学びたい。前提から応用まで知りたい">
      <button class="primary" id="generate">生成</button>
      <input id="search" placeholder="ノードを検索">
      <button id="fit">Fit</button>
      <button class="primary" id="reload">Reload</button>
    </div>
  </header>
  <main>
    <section id="canvasWrap">
      <canvas id="graph"></canvas>
      <div class="status" id="status"><strong>Ready</strong><br>トピックを入力して「生成」を押すと、新しいナレッジグラフを作成します。</div>
    </section>
    <aside>
      <div class="stats">
        <div class="stat"><b id="nodeCount">0</b><span>Nodes</span></div>
        <div class="stat"><b id="edgeCount">0</b><span>Edges</span></div>
      </div>
      <div id="details">ノードをクリックすると詳細を表示します。</div>
      <h2>LLM Discussion</h2>
      <div id="discussion">議論ログはまだありません。</div>
      <h2>LLM Live Output</h2>
      <div id="ollamaLive">Ollama の出力はまだありません。</div>
      <h2>Quiz Evaluation</h2>
      <div id="quizResult">理解度テストの結果はまだありません。</div>
      <h2>Research Plan</h2>
      <div id="researchPlan">調査計画はまだありません。</div>
      <h2>Layers</h2>
      <div id="layers"></div>
    </aside>
  </main>
  <script>
    const canvas = document.getElementById('graph');
    const ctx = canvas.getContext('2d');
    let graph = { topic: '', nodes: [], edges: [] };
    let positions = new Map();
    let selected = null;
    let scale = 1;
    let offset = { x: 0, y: 0 };
    let dragging = false;
    let last = { x: 0, y: 0 };
    let generating = false;
    let currentGraphFile = '';

    function setStatus(title, message) {
      document.getElementById('status').innerHTML = `<strong>${title}</strong><br>${message}`;
    }

    function resize() {
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(320, Math.floor(rect.width * devicePixelRatio));
      canvas.height = Math.max(320, Math.floor(rect.height * devicePixelRatio));
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
      draw();
    }

    function colorFor(node) {
      const layer = Number(node.layer || 0);
      if (layer <= 0) return '#0f9f6e';
      if (layer === 1) return '#1677ff';
      if (layer === 2) return '#d97706';
      return '#7c3aed';
    }

    function layout() {
      const layers = new Map();
      for (const node of graph.nodes) {
        const layer = node.layer || 0;
        if (!layers.has(layer)) layers.set(layer, []);
        layers.get(layer).push(node);
      }
      const width = canvas.getBoundingClientRect().width || 900;
      const height = canvas.getBoundingClientRect().height || 600;
      const sortedLayers = [...layers.keys()].sort((a, b) => a - b);
      positions.clear();
      sortedLayers.forEach((layer, layerIndex) => {
        const nodes = layers.get(layer);
        const x = 90 + layerIndex * Math.max(180, (width - 180) / Math.max(1, sortedLayers.length - 1));
        nodes.forEach((node, index) => {
          const gap = height / (nodes.length + 1);
          positions.set(node.node_id, { x, y: gap * (index + 1), vx: 0, vy: 0 });
        });
      });
      offset = { x: 0, y: 0 };
      scale = 1;
    }

    function transformPoint(point) {
      return { x: point.x * scale + offset.x, y: point.y * scale + offset.y };
    }

    function inversePoint(x, y) {
      return { x: (x - offset.x) / scale, y: (y - offset.y) / scale };
    }

    function drawArrow(from, to) {
      const a = transformPoint(from);
      const b = transformPoint(to);
      const angle = Math.atan2(b.y - a.y, b.x - a.x);
      const radius = 26;
      const end = { x: b.x - Math.cos(angle) * radius, y: b.y - Math.sin(angle) * radius };
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(end.x, end.y);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(end.x, end.y);
      ctx.lineTo(end.x - Math.cos(angle - 0.45) * 10, end.y - Math.sin(angle - 0.45) * 10);
      ctx.lineTo(end.x - Math.cos(angle + 0.45) * 10, end.y - Math.sin(angle + 0.45) * 10);
      ctx.closePath();
      ctx.fill();
    }

    function draw() {
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.lineWidth = 1.3;
      ctx.strokeStyle = '#c7d0dc';
      ctx.fillStyle = '#8b96a8';
      for (const edge of graph.edges) {
        const from = positions.get(edge.source_id || edge.from);
        const to = positions.get(edge.target_id || edge.to);
        if (from && to) drawArrow(from, to);
      }
      for (const node of graph.nodes) {
        const pos = transformPoint(positions.get(node.node_id) || { x: 0, y: 0 });
        const isSelected = selected === node.node_id;
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, isSelected ? 29 : 24, 0, Math.PI * 2);
        ctx.fillStyle = colorFor(node);
        ctx.fill();
        ctx.lineWidth = isSelected ? 4 : 2;
        ctx.strokeStyle = isSelected ? '#17202a' : '#ffffff';
        ctx.stroke();
        ctx.fillStyle = '#17202a';
        ctx.font = '650 13px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const label = node.label.length > 16 ? node.label.slice(0, 15) + '...' : node.label;
        ctx.fillText(label, pos.x, pos.y + 32);
      }
    }

    function renderSidebar() {
      document.getElementById('topic').textContent = graph.topic || 'No topic';
      const discussion = document.getElementById('discussion');
      const quizResult = document.getElementById('quizResult');
      const researchPlan = document.getElementById('researchPlan');
      const refinement = graph.refinement || [];
      discussion.innerHTML = refinement.length
        ? refinement.map(item => `<div class="discussion-item"><strong>${(item.model || 'llm').toUpperCase()}</strong> — ${item.reason || 'refine'}<br>${item.title || ''}</div>`).join('')
        : '議論ログはまだありません。';
      document.getElementById('ollamaLive').textContent = 'Ollama のリアルタイム表示は安定化のため簡略化しました。';
      const quiz = graph.quiz_result || null;
      if (quiz && quiz.score) {
        quizResult.innerHTML = `<strong>Accuracy:</strong> ${(quiz.score.accuracy * 100).toFixed(1)}%<br>${(quiz.score.results || []).map(item => `<div class="discussion-item">Q${item.id}: ${item.score === 1 ? '正解' : '要改善'}</div>`).join('')}`;
      } else {
        quizResult.textContent = '理解度テストの結果はまだありません。';
      }
      const plan = graph.research_plan || null;
      if (plan) {
        const angles = Array.isArray(plan.research_angles) ? plan.research_angles.join(' / ') : '';
        const seeds = Array.isArray(plan.seed_terms) ? plan.seed_terms.join(' / ') : '';
        researchPlan.innerHTML = `
          <strong>${plan.normalized_topic || graph.topic || 'n/a'}</strong><br>
          intent: ${plan.intent_summary || 'n/a'}<br>
          goal: ${plan.study_goal || 'n/a'}<br>
          angles: ${angles || 'n/a'}<br>
          seeds: ${seeds || 'n/a'}<br>
          complexity: ${plan.complexity_hint || 'n/a'}
        `;
      } else {
        researchPlan.textContent = '調査計画はまだありません。';
      }
      document.getElementById('nodeCount').textContent = graph.nodes.length;
      document.getElementById('edgeCount').textContent = graph.edges.length;
      const layers = new Map();
      for (const node of graph.nodes) {
        const layer = node.layer || 0;
        if (!layers.has(layer)) layers.set(layer, []);
        layers.get(layer).push(node);
      }
      document.getElementById('layers').innerHTML = [...layers.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([layer, nodes]) => `
          <div class="layer">
            <div class="layer-title"><strong>Layer ${layer}</strong><span>${nodes.length} skills</span></div>
            ${nodes.map(node => `<span class="chip">${node.label}</span>`).join('')}
          </div>
        `).join('');
    }

    function showDetails(node) {
      const incoming = graph.edges
        .filter(edge => (edge.target_id || edge.to) === node.node_id)
        .map(edge => edge.source_id || edge.from);
      const outgoing = graph.edges
        .filter(edge => (edge.source_id || edge.from) === node.node_id)
        .map(edge => edge.target_id || edge.to);
      document.getElementById('details').innerHTML = `
        <strong>${node.label}</strong><br>
        type: ${node.type || 'concept'}<br>
        layer: ${node.layer || 0}<br>
        mastery: ${Number(node.mastery || 0).toFixed(2)} / hesitation: ${Number(node.hesitation_score || 0).toFixed(2)}<br>
        description: ${node.description || 'n/a'}<br>
        prerequisites: ${incoming.length ? incoming.join(', ') : 'なし'}<br>
        next: ${outgoing.length ? outgoing.join(', ') : 'なし'}
      `;
    }

    function pickNode(x, y) {
      const point = inversePoint(x, y);
      return graph.nodes.find(node => {
        const pos = positions.get(node.node_id);
        return pos && Math.hypot(pos.x - point.x, pos.y - point.y) <= 32;
      });
    }

    async function loadGraph(filePath = '') {
      const url = filePath
        ? '/graph.json?file=' + encodeURIComponent(filePath) + '&ts=' + Date.now()
        : '/graph.json?ts=' + Date.now();
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error('graph.json の読み込みに失敗しました');
      }
      graph = await response.json();
      currentGraphFile = filePath || graph.source_file || '';
      const fileSelect = document.getElementById('fileSelect');
      if (fileSelect && currentGraphFile) {
        fileSelect.value = currentGraphFile;
      }
      selected = null;
      layout();
      renderSidebar();
      draw();
    }

    function displayNameForFile(file) {
      if (!file) return '現在のグラフ';
      const parts = file.split(/[\\/]/);
      return parts[parts.length - 1];
    }

    async function loadGraphFiles() {
      const response = await fetch('/graph-files?ts=' + Date.now());
      if (!response.ok) {
        throw new Error('graph-files の読み込みに失敗しました');
      }
      const files = await response.json();
      const select = document.getElementById('fileSelect');
      const current = currentGraphFile;
      select.innerHTML = files.map(file => {
        const label = file.label || displayNameForFile(file.path || file);
        const path = file.path || file;
        const selected = current && current === path ? ' selected' : '';
        return `<option value="${path}"${selected}>${label}</option>`;
      }).join('');
      if (!select.value && files.length > 0) {
        select.value = files[0].path || files[0];
      }
      if (!currentGraphFile && select.value) {
        currentGraphFile = select.value;
      }
    }

    async function generateGraph() {
      if (generating) return;
      const input = document.getElementById('topicInput');
      const topic = input.value.trim();
      if (!topic) {
        setStatus('Topic required', '作成したいトピックを入力してください。');
        input.focus();
        return;
      }
      generating = true;
      document.getElementById('generate').disabled = true;
      document.getElementById('reload').disabled = true;
      setStatus('Generating', `${topic} のWikipedia候補とGoogle Trendsを取得しています。数十秒かかることがあります。`);
      try {
        const response = await fetch('/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ topic })
        });
        const result = await response.json();
        if (!response.ok || result.error) {
          throw new Error(result.error || '生成に失敗しました');
        }
        graph = result.graph;
        graph.research_plan = result.research_plan || null;
        currentGraphFile = result.output_path || '';
        selected = null;
        layout();
        renderSidebar();
        draw();
        await loadGraphFiles();
        if (result.output_path) {
          await loadGraph(result.output_path);
        }
        selected = null;
        setStatus('Generated', `${graph.topic}: ${graph.nodes.length} nodes / ${graph.edges.length} edges`);
      } catch (error) {
        setStatus('Error', error.message || String(error));
      } finally {
        generating = false;
        document.getElementById('generate').disabled = false;
        document.getElementById('reload').disabled = false;
      }
    }

    canvas.addEventListener('mousedown', event => {
      const rect = canvas.getBoundingClientRect();
      const node = pickNode(event.clientX - rect.left, event.clientY - rect.top);
      if (node) {
        selected = node.node_id;
        showDetails(node);
        draw();
      } else {
        dragging = true;
        last = { x: event.clientX, y: event.clientY };
      }
    });
    window.addEventListener('mouseup', () => dragging = false);
    window.addEventListener('mousemove', event => {
      if (!dragging) return;
      offset.x += event.clientX - last.x;
      offset.y += event.clientY - last.y;
      last = { x: event.clientX, y: event.clientY };
      draw();
    });
    canvas.addEventListener('wheel', event => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.08 : 0.92;
      scale = Math.max(0.35, Math.min(2.8, scale * factor));
      draw();
    }, { passive: false });
    document.getElementById('fit').addEventListener('click', () => { layout(); draw(); });
    document.getElementById('reload').addEventListener('click', () => loadGraph(currentGraphFile));
    document.getElementById('generate').addEventListener('click', generateGraph);
    document.getElementById('topicInput').addEventListener('keydown', event => {
      if (event.key === 'Enter') generateGraph();
    });
    document.getElementById('fileSelect').addEventListener('change', async event => {
      const file = event.target.value;
      if (!file) return;
      try {
        await loadGraph(file);
        setStatus('Loaded', `${displayNameForFile(file)} を表示しています。`);
      } catch (error) {
        setStatus('Error', error.message || String(error));
      }
    });
    document.getElementById('search').addEventListener('input', event => {
      const q = event.target.value.trim().toLowerCase();
      const node = graph.nodes.find(item => item.label.toLowerCase().includes(q));
      if (q && node) {
        selected = node.node_id;
        showDetails(node);
      } else if (!q) {
        selected = null;
      }
      draw();
    });
    window.addEventListener('resize', resize);
    resize();
    Promise.all([loadGraphFiles(), loadGraph()]).then(() => {
      const fileSelect = document.getElementById('fileSelect');
      if (fileSelect && !fileSelect.value && fileSelect.options.length > 0) {
        fileSelect.value = fileSelect.options[0].value;
      }
      if (!currentGraphFile && fileSelect && fileSelect.value) {
        currentGraphFile = fileSelect.value;
      }
    }).catch(error => {
      setStatus('Error', error.message || String(error));
    });
  </script>
</body>
</html>
"""


SAMPLE_GRAPH = {
    "topic": "Sample",
    "nodes": [
        {"node_id": "N1", "label": "変数", "type": "FOUNDATIONAL", "layer": 0, "description": "", "mastery": 0.0, "hesitation_score": 0.0, "cognitive_load_history": [], "next_review": "2026-07-03", "review_count": 0},
        {"node_id": "N2", "label": "関数", "type": "BASIC", "layer": 1, "description": "", "mastery": 0.0, "hesitation_score": 0.0, "cognitive_load_history": [], "next_review": "2026-07-03", "review_count": 0},
        {"node_id": "N3", "label": "クラス", "type": "CORE", "layer": 2, "description": "", "mastery": 0.0, "hesitation_score": 0.0, "cognitive_load_history": [], "next_review": "2026-07-03", "review_count": 0},
    ],
    "edges": [
        {"edge_id": "N1__N2", "source_id": "N1", "target_id": "N2", "relationship": "prerequisite", "weight": 1.0, "description": ""},
        {"edge_id": "N2__N3", "source_id": "N2", "target_id": "N3", "relationship": "prerequisite", "weight": 1.0, "description": ""},
    ],
}


def _safe_relative_path(path_str: str) -> Path | None:
    try:
        candidate = Path(path_str)
        if candidate.is_absolute():
            candidate = candidate.relative_to(PROJECT_ROOT)
        resolved = (PROJECT_ROOT / candidate).resolve()
        if not str(resolved).startswith(str(PROJECT_ROOT.resolve())):
            return None
        return resolved
    except Exception:
        return None


def _resolve_graph_path(request_path: str) -> Path | None:
    parsed = urlparse(request_path)
    params = parse_qs(parsed.query, keep_blank_values=True)
    requested = params.get("file", [""])[0]
    if requested:
        resolved = _safe_relative_path(requested)
        if resolved and resolved.is_file():
            return resolved
    if GRAPH_DIR.exists():
        latest_graphs = sorted(GRAPH_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        if latest_graphs:
            return latest_graphs[0]
    if GRAPH_PATH.exists():
        return GRAPH_PATH
    return None


def _list_graph_files() -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    if GRAPH_DIR.exists():
        for path in sorted(GRAPH_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            files.append(
                {
                    "path": str(path.relative_to(PROJECT_ROOT)),
                    "label": path.name,
                }
            )
    if GRAPH_PATH.exists():
        legacy_rel = str(GRAPH_PATH.relative_to(PROJECT_ROOT))
        if legacy_rel not in {item["path"] for item in files}:
            files.append({"path": legacy_rel, "label": GRAPH_PATH.name})
    return files


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, content: str, content_type: str) -> None:
        encoded = content.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as exc:
            self.close_connection = True
            print(f"[Web][WARN] クライアント切断によりレスポンス送信を中止しました: {exc}")

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, HTML, "text/html; charset=utf-8")
                return
            if path == "/graph-files":
                files = _list_graph_files()
                self._send(200, json.dumps(files, ensure_ascii=False), "application/json; charset=utf-8")
                return
            if path == "/graph.json":
                requested = _resolve_graph_path(self.path)
                if requested is None:
                    content = json.dumps(SAMPLE_GRAPH, ensure_ascii=False)
                else:
                    content = requested.read_text(encoding="utf-8")
                self._send(200, content, "application/json; charset=utf-8")
                return
            self._send(404, "Not found", "text/plain; charset=utf-8")
        except Exception as exc:
            self._send(500, f"Server error: {exc}", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            if path != "/generate":
                self._send(404, json.dumps({"error": "Not found"}), "application/json; charset=utf-8")
                return

            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw_body or "{}")
            topic = str(payload.get("topic", "")).strip()
            if not topic:
                body = json.dumps({"error": "topic is required"}, ensure_ascii=False)
                self._send(400, body, "application/json; charset=utf-8")
                return

            result = generate_knowledge_graph(topic)
            graph = {
                "topic": result["topic"],
                "nodes": result["nodes"],
                "edges": result["edges"],
                "refinement": result.get("refinement", []),
            }
            response = {
            "graph": graph,
            "summary": result.get("summary", {}),
            "refinement": result.get("refinement", []),
            "research_plan": result.get("research_plan", {}),
            "output_path": result.get("output_path", ""),
        }
            if result.get("error"):
                response["error"] = result["error"]
            self._send(200, json.dumps(response, ensure_ascii=False), "application/json; charset=utf-8")
        except Exception as exc:
            body = json.dumps({"error": str(exc)}, ensure_ascii=False)
            self._send(500, body, "application/json; charset=utf-8")


def main() -> None:
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        print(f"[Web] http://{HOST}:{PORT} で起動しました")
        print(f"[Web] 読み込み対象: {GRAPH_PATH}")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Web] 停止しました")
    except Exception as exc:
        print(f"[Web][WARN] 起動に失敗しました: {exc}")


if __name__ == "__main__":
    main()
