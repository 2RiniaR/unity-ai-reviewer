# PR Reviewer System - 設計メモ

## 概要

PythonからClaudeを呼び出し、Pull Requestに対して反復的にコード探索・レビューを行うシステム

## レビュー観点（動的生成）

レビュワーは `reviewers/` ディレクトリのMarkdownファイルから**動的に生成**される。
ファイル名がレビュワーID、フロントマターの `title` が日本語表示名となる。

### レビュワーの追加方法

1. `reviewers/` に新しいMarkdownファイルを作成（例: `new_reviewer.md`）
2. ファイルの先頭にYAMLフロントマターで `title` を定義：
   ```markdown
   ---
   title: 新しいレビュワー
   ---

   ## 責務
   ...
   ```
3. `config.yaml` の `enabled_reviewers` に追加
4. システムを再起動すると自動的に認識される

### 現在のレビュワー一覧

| ID | 日本語名 | 説明 |
|---|---|---|
| runtime_error | 実行時エラー | NullReference、OutOfRange、例外発生の可能性 |
| security | セキュリティ | tokenが含まれていたり、危険なコードがないか |
| gc_allocation | GCアロケーション | 回避可能なヒープアロケーションがないか |
| resource_management | リソース管理 | Dispose漏れ、イベント解除漏れ、メモリリーク |
| efficiency | 効率性 | 非効率なアルゴリズム、不要なループ |
| convention | コーディング規約 | 命名規則、名前空間などプロジェクトの慣習 |
| unused_code | 未使用コード | 余計な実装や未使用コードが残っていないか |
| wheel_reinvention | 車輪の再発明 | Util系など既存実装との重複がないか |
| impact_analysis | 影響範囲分析 | 他機能への影響検出、類似機能の変更漏れ検出 |
| semantic_placement | 実装箇所 | 実装箇所が意味的に適切かどうかの検証 |

## システム要件

### 基本動作

- Pythonスクリプトから Claude CLI (`claude -p`) を呼び出す（コスト削減のためAPIではなくCLI経由）
- `--json-schema` オプションで構造化出力を強制（findings配列を確実に取得）
- 反復的探索：メタデータファイルで探索状態を管理
- 出力は日本語、問題の「なぜ（reason）」も説明する

### GitHub連携

- PR open をトリガーに発動（GitHub Actions）
- レビュー結果をPRコメントとして投稿
- 修正案は GitHub Suggested Changes 形式で提示（画面から即適用可能）

### 探索パラメータ

- 対象プロジェクト: config.yaml の `unity_project_path` で指定 (Unity C#)
- 影響範囲の探索深度: 最大5階層

## 実装済みアーキテクチャ

### 3フェーズ Fix PR アーキテクチャ

PR レビューから修正 PR 作成までを3つのフェーズで実行：

```
[Phase 1: 並列分析] → [Phase 2: Draft PR作成] → [Phase 3: 順次修正適用]
```

#### Phase 1: 並列分析（deep_analysis）
- 9個のレビュワーが並列実行（ThreadPoolExecutor）
- 各レビュワーは問題を検出し、`fix_plan`（修正計画）と`fix_summary`（修正方法の要約）を出力
- **ツール使用なし**（分析のみ、ファイル編集なし）
- 出力: `source_file`, `source_line`, `title`, `description`, `scenario`, `fix_plan`, `fix_summary`

#### Phase 2: Draft PR 作成（fix_pr_creation）
- 検出された問題に連番を割り当て: (1), (2), (3)...
- 空コミットでfix用ブランチを作成・プッシュ
- Draft PRを作成（サマリーテーブル付き）
- オリジナルPRにFix PRへのリンクをコメント

#### Phase 3: 順次修正適用（fix_application）
- 各findingを**順番に**処理（行ズレ防止のため並列不可）
- Claude CLIにツールを有効化して修正を実行:
  1. ファイル読み込み（Read）
  2. 修正適用（Edit）
  3. コミット・プッシュ（`git add`, `git commit -m "[PR Review] (N) タイトル"`, `git push`）
- 各修正完了後にPRコメントを投稿（修正理由、シナリオ）
- PR bodyのサマリーテーブルを更新（commit hashリンク付き）
- 全完了後、DraftをOpenに変更

### ディレクトリ構成

```
reviewer/
├── config.example.yaml      # 設定ファイルのテンプレート
├── config.yaml              # 設定ファイル（git管理外）
├── pyproject.toml           # Python プロジェクト設定
├── reviewers/               # レビュワー別プロンプト（Markdown、動的読み込み）
│   ├── runtime_error.md     # フロントマターでtitleを定義
│   ├── security.md
│   ├── gc_allocation.md
│   ├── resource_management.md
│   ├── efficiency.md
│   ├── convention.md
│   ├── unused_code.md
│   ├── wheel_reinvention.md
│   └── impact_analysis.md
├── src/
│   ├── main.py              # エントリーポイント
│   ├── config.py            # 設定管理
│   ├── models/              # データモデル（Pydantic）
│   ├── reviewer_registry/   # レビュワー動的生成
│   │   ├── __init__.py      # API: get_reviewer_type(), get_display_name()
│   │   ├── loader.py        # Markdownスキャン・フロントマター解析
│   │   └── registry.py      # 動的Enum生成
│   ├── orchestrator/        # 反復探索エンジン
│   │   └── engine.py        # 3フェーズ実行エンジン
│   ├── claude/              # Claude CLI連携
│   │   ├── client.py        # CLIクライアント
│   │   ├── base_prompt.py   # ベースプロンプト
│   │   ├── prompt_loader.py # プロンプトローダー
│   │   └── reviewers/       # 後方互換性用モジュール
│   ├── github/              # GitHub連携
│   │   ├── client.py        # gh CLI経由のAPI操作
│   │   ├── fix_pr_creator.py # Fix PR作成・コメント投稿
│   │   └── git_operations.py # git操作
└── reviews/                 # レビュー結果保存（デバッグ出力含む）
```

### メタデータ構造

- PR情報、変更ファイル一覧
- フェーズ管理（初期化 → 探索 → 分析 → PR作成 → 修正適用 → 投稿）
- 各レビュワーの状態
- 探索キュー（優先度付き）
- 発見した問題（findings）: Phase 1〜3の出力を統合管理

### Finding データ構造

```python
class Finding:
    # Phase 1 出力（問題の検出）
    source_file: str        # 問題が発見されたファイル
    source_line: int        # 問題が発見された行
    title: str              # 問題のタイトル
    description: str        # 問題の説明
    scenario: str           # 問題が発生するシナリオ
    fix_plan: str           # 修正計画（詳細）
    fix_summary: str        # 修正方法の要約（1-2文、PRコメント表示用）

    # Phase 2 出力（番号割り当て）
    number: int             # 連番 (1), (2), (3)...

    # Phase 3 出力（修正適用結果）
    file: str               # 修正を適用したファイル
    line: int               # 修正を適用した行
    commit_hash: str        # コミットハッシュ
```

## 使用方法

### インストール

```bash
pip install -e .
```

### ローカルブランチレビュー（GitHub連携なし）

```bash
# 現在のブランチをmainと比較してレビュー（修正も適用）
pr-review local --base main

# デバッグ出力付き
pr-review local --base main --debug

# 分析のみ（修正適用なし）
pr-review local --base main --no-fix
```

ローカルレビューでは:
- PRを作成せず、ローカルでファイル修正を適用
- `reviews/` 配下に `report.md` を生成（Markdownレポート）

### GitHub PRレビュー（推奨）

```bash
# PRをレビューしてFix PRを自動作成（3フェーズ実行）
pr-review review --pr 36

# デバッグ出力付き
pr-review review --pr 36 --debug

# Fix PR作成なし（分析のみ）
pr-review review --pr 36 --no-pr
```

## レビュワー設定

### report_only_reviewers

`config.yaml` の `report_only_reviewers` で指定したレビュワーは、問題検出のみで自動修正を行わない。

```yaml
review:
  report_only_reviewers:
    - impact_analysis  # 影響範囲分析は報告のみ
```

### デバッグ出力

`--debug` オプションで、各レビュワーのプロンプトとレスポンスを保存：

```
reviews/{PR番号}-{タイムスタンプ}/debug/
├── {reviewer}_system_prompt.txt
├── {reviewer}_user_message.txt
└── {reviewer}_response.json
```

---

*最終更新: 2026-01-03*
