# ナレッジグラフ自動生成システム

入力した文章から学習意図を解釈し、Wikipedia と Google Trends を使って候補を集め、gemma4 でオーダーメイドの学習ナレッジグラフを生成するアプリです。

## できること

- 自然文の入力から「何を調べるべきか」を AI が整理する
- Wikipedia から関連候補を広く収集する
- Google Trends で候補の検索傾向を補助情報として扱う
- gemma4 が最終的なナレッジグラフ JSON を生成する
- Web 画面で生成済み JSON を選択して閲覧する
- ノード、エッジ、Layer 別の構成を可視化する

## アーキテクチャ

- `src/collector/web_app.py`
  - ローカル Web UI
  - 出力済み JSON の一覧表示と切り替え
  - 新しいトピックの生成実行
- `src/collector/pipeline.py`
  - 文章入力を受け取り、調査計画と候補収集を実行
  - 最終 JSON を `output/graphs/` に保存
- `src/collector/gemma_graph_builder.py`
  - gemma4 へのプロンプト生成
  - JSON 解析
  - `KnowledgeGraph` への変換
- `src/collector/wikipedia_collector.py`
  - Wikipedia 候補の取得とフィルタリング
- `src/collector/trends_collector.py`
  - Google Trends の検索ボリューム取得
- `src/models/graph_models.py`
  - ナレッジグラフのデータモデル

## 必要環境

- Python 3.11 以上を推奨
- Ollama
- gemma4 系モデル
- インターネット接続
  - Wikipedia と Google Trends を参照するため

## セットアップ

仮想環境を作成して依存関係を入れます。

```bash
python3 -m venv myenv
source myenv/bin/activate
pip install -r requirements.txt
```

Ollama 側では gemma4 を用意してください。(gemma4以外でも、`OLLAMA_MODEL`の値を変えれば利用可能ですが、軽量かつ、精度もいいのでgemma4はおすすめです。)

```bash
ollama pull gemma4
```

必要に応じて、モデル名や接続先を環境変数で変更できます。

- `OLLAMA_BASE_URL`
  - 既定値: `http://localhost:11434`
- `OLLAMA_MODEL`
  - 既定値: `gemma4:latest`

## 起動方法

### Web アプリ

```bash
python src/collector/web_app.py
```

ブラウザで次を開きます。

```text
http://127.0.0.1:8000
```

### CLI

```bash
python src/collector/main.py "Pythonでデータ分析を学びたい。前提から応用まで知りたい"
```

## 使い方

Web 画面では、検索欄に単語だけでなく自然文を入力できます。

例:

- `Pythonでデータ分析を学びたい。pandas の使い方だけでなく、前提となる統計も含めたい`
- `暗号通信の仕組みを理解したい。公開鍵暗号、証明書、TLS を含めて知りたい`
- `機械学習の全体像を知りたい。基礎から実践まで段階的に学びたい`

入力された文章をもとに、AI が調査計画を作成し、Wikipedia 候補を複数の観点から集めて、最終的な学習グラフを生成します。

## 出力

生成結果は以下に保存されます。

- `output/graphs/{トピック}_{タイムスタンプ}.json`
- 互換用として `output/knowledge_graph.json`

Web 画面では、`output/graphs/` にある JSON をプルダウンで選んで表示できます。

### JSON の内容

保存されるグラフには、主に次の情報が入ります。

- `graph_id`
- `topic`
- `nodes`
- `edges`
- `meta`
- `research_plan`

各ノードには以下のような情報が入ります。

- `node_id`
- `label`
- `type`
- `layer`
- `description`
- `prerequisites`
- `mastery`
- `hesitation_score`
- `cognitive_load_history`
- `next_review`
- `review_count`

各エッジには以下のような情報が入ります。

- `edge_id`
- `source_id`
- `target_id`
- `relationship`
- `weight`
- `description`


## ディレクトリ構成

```text
src/
  collector/
    main.py
    pipeline.py
    gemma_graph_builder.py
    wikipedia_collector.py
    trends_collector.py
    web_app.py
  models/
    graph_models.py
output/
  graphs/
docs/
scripts/
```

## 補足

- Wikipedia の候補収集はラベル中心です
- 最終的なナレッジグラフは gemma4 の出力を基準にしています
- ノード数が多すぎる場合は、再度 gemma4 に絞り込みを依頼します
- Web 画面のリアルタイム生成表示は安定性を優先して簡略化しています

## トラブルシューティング

### Ollama に接続できない

- Ollama が起動しているか確認してください
- `OLLAMA_BASE_URL` が正しいか確認してください
- モデル名が `OLLAMA_MODEL` に存在するか確認してください

### Wikipedia で 429 が出る

- 短時間に大量の取得をしている可能性があります
- アプリ側で再試行はしますが、しばらく待ってから再実行してください

### 生成結果が増えすぎる

- 入力文を少し具体的にしてください
- 必要な学習範囲を明示すると、より絞りやすくなります

