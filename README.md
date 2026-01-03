# Unity AI Reviewer

Claude CLI を使用した自動PRレビュー＆修正システム

## 概要

Unity AI Reviewer は、Pull Request のコードを自動でレビューし、問題を検出して修正PRを作成するツールです。Unity C# プロジェクト向けに最適化されており、9種類の専門レビュワーが並列で分析を行います。

[サンプルはこちらから](https://github.com/2RiniaR/unity-ai-reviewer/pull/7)

### 主な特徴

- **自動レビュー**: 9つの観点から並列でコードレビューを実行
- **自動修正PR作成**: 検出した問題に対する修正を自動で適用し、PRを作成
- **ローカルレビュー**: GitHub連携なしでローカルブランチのレビューも可能
- **Unity対応**: Unity C# プロジェクトに特化したレビュー観点
- **カスタマイズ可能**: レビュワーの有効/無効、テンプレート設定が可能

### レビュー観点

| レビュワー | 説明 |
|-----------|------|
| `runtime_error` | NullReference、OutOfRange、例外発生の可能性 |
| `security` | トークン漏洩、危険なコードパターン |
| `gc_allocation` | 回避可能なヒープアロケーション |
| `resource_management` | Dispose漏れ、イベント解除漏れ、メモリリーク |
| `efficiency` | 非効率なアルゴリズム、不要なループ |
| `convention` | 命名規則、プロジェクト慣習への違反 |
| `unused_code` | 未使用の実装やコード |
| `wheel_reinvention` | 既存Util等との重複実装 |
| `impact_analysis` | 他機能への影響、類似機能の変更漏れ |

## クイックスタート

### 前提条件

- Python 3.11+
- [Claude CLI](https://github.com/anthropics/claude-code) がインストール済み
- [GitHub CLI (gh)](https://cli.github.com/) がインストール済み（GitHub連携時）

### インストール

```bash
git clone https://github.com/your-repo/unity-ai-reviewer.git
cd unity-ai-reviewer
pip install -e .
```

### 設定

```bash
cp config.example.yaml config.yaml
```

`config.yaml` を編集:

```yaml
project:
  unity_project_path: ~/path/to/unity-project  # Unityプロジェクトのパス

github:
  repo: owner/repo  # GitHubリポジトリ (owner/repo形式)
```

### 実行

```bash
# GitHub PRをレビュー
pr-review review --pr 123

# ローカルブランチをレビュー
pr-review local --base main
```

## 詳細な使用方法

### GitHub PRレビュー

```bash
# 基本的な使用法（PR #123 をレビューして修正PRを作成）
pr-review review --pr 123

# デバッグ出力付き
pr-review review --pr 123 --debug

# 分析のみ（修正PR作成なし）
pr-review review --pr 123 --no-pr
```

### ローカルブランチレビュー

GitHub連携なしで、現在のブランチをベースブランチと比較してレビュー:

```bash
# mainブランチと比較してレビュー＆修正
pr-review local --base main

# 分析のみ（修正適用なし）
pr-review local --base main --no-fix

# デバッグ出力付き
pr-review local --base main --debug
```

ローカルレビューでは:
- PRは作成されず、ローカルにコミットが作成される
- `reviews/` 配下に `report.md`（Markdownレポート）が生成される

### 出力例

```
PR #34 の情報を取得中...
PR: 機能追加: カード回収アニメーション
2 個のファイルが変更されています

╭──────────────── Phase: Deep Analysis ────────────────╮
│ 深層分析フェーズを開始（並列実行）                    │
╰──────────────────────────────────────────────────────╯
9 個のレビュワーを並列実行中...
  ✓ security 完了 (0 件)
  ✓ gc_allocation 完了 (3 件)
  ✓ runtime_error 完了 (1 件)
  ...
分析完了。4 件の問題を検出しました。

Phase 2: Draft Fix PR を作成中...
✓ Draft Fix PR を作成しました
  URL: https://github.com/owner/repo/pull/50

Phase 3: 修正を順次適用中...
  ✓ (1) 未使用パラメータ: targetPlayer - コミット: abc1234
  ✓ (2) List<UniTask>のGCアロケーション - コミット: def5678
  ...
✓ 修正適用完了 (4 件)
```

## 設定

### config.yaml

```yaml
project:
  unity_project_path: ~/path/to/unity-project  # 必須

github:
  repo: owner/repo  # 必須
  # Fix PRのテンプレート（任意）
  # プレースホルダー: ($Branch), ($Timestamp), ($Number), ($Title)
  fix_branch_template: "($Branch)_fix_($Timestamp)"
  fix_pr_title_template: "[自動修正] #($Number)「($Title)」"

review:
  enabled_reviewers:  # 有効にするレビュワー
    - runtime_error
    - security
    - gc_allocation
    - resource_management
    - efficiency
    - convention
    - unused_code
    - wheel_reinvention
    - impact_analysis
  report_only_reviewers:  # 報告のみで修正を行わないレビュワー
    - impact_analysis

claude:
  model: opus  # sonnet または opus
```

### テンプレートのプレースホルダー

| プレースホルダー | 説明 |
|-----------------|------|
| `($Branch)` | 対象PRのブランチ名 |
| `($Timestamp)` | タイムスタンプ (YYYYMMDD-HHMMSS) |
| `($Number)` | 対象PRの番号 |
| `($Title)` | 対象PRのタイトル |

## 仕組み

### 3フェーズ

Unity AI Reviewer は3つのフェーズでレビューから修正PRの作成までを実行します:

```
[Phase 1: 並列分析] → [Phase 2: Draft PR作成] → [Phase 3: 順次修正適用]
```

#### Phase 1: 並列分析

- 9個のレビュワーが **並列実行**（ThreadPoolExecutor）
- 各レビュワーは問題を検出し、修正計画（fix_plan）と修正方法の要約（fix_summary）を出力
- この段階ではファイル編集は行わない（分析のみ）
- Claude CLI を `--tools Read` モードで実行

```
出力:
- source_file: 問題のファイル
- source_line: 問題の行番号
- title: 問題のタイトル
- description: 問題の説明
- scenario: 問題が発生するシナリオ
- fix_plan: 修正計画（詳細）
- fix_summary: 修正方法の要約（1-2文、PRコメント表示用）
```

#### Phase 2: Draft PR 作成

- 検出された問題に連番を割り当て: (1), (2), (3)...
- Fix用ブランチを作成・プッシュ
- Draft PR を作成（サマリーテーブル付き）
- 元PRに Fix PR へのリンクをコメント

#### Phase 3: 順次修正適用

- 各問題を **順番に** 処理（行ズレ防止のため並列不可）
- Claude CLI にツールを有効化して修正を実行:
  1. ファイル読み込み（Read）
  2. 修正適用（Edit）
  3. コミット・プッシュ
- 各修正完了後に PR コメントを投稿
- PR body のサマリーテーブルを更新（commit hash リンク付き）

### ディレクトリ構成

```
unity-ai-reviewer/
├── config.example.yaml      # 設定ファイルのテンプレート
├── config.yaml              # 設定ファイル（git管理外）
├── pyproject.toml           # Python プロジェクト設定
├── src/
│   ├── main.py              # エントリーポイント
│   ├── config.py            # 設定管理
│   ├── models/              # データモデル（Pydantic）
│   ├── orchestrator/        # レビュー実行エンジン
│   │   └── engine.py        # 3フェーズ実行エンジン
│   ├── claude/              # Claude CLI 連携
│   │   ├── client.py        # CLI クライアント
│   │   └── reviewers/       # レビュワー別プロンプト
│   ├── github/              # GitHub 連携
│   │   ├── client.py        # gh CLI 経由の API 操作
│   │   ├── fix_pr_creator.py # Fix PR 作成
│   │   └── git_operations.py # git 操作
└── reviews/                 # レビュー結果保存
    └── {PR番号}-{タイムスタンプ}/
        ├── metadata.json    # レビューメタデータ
        ├── context/         # コンテキストファイル
        ├── debug/           # デバッグ出力
        └── report.md        # レポート（ローカルレビュー時）
```

### 技術スタック

- **Python+**: メイン言語
- **Claude CLI**: AI レビュー実行
- **GitHub CLI (gh)**: GitHub API 操作
- **Pydantic**: データモデル/バリデーション
- **Rich**: ターミナル出力

## コントリビュート

### 開発環境のセットアップ

```bash
# リポジトリをクローン
git clone https://github.com/your-repo/unity-ai-reviewer.git
cd unity-ai-reviewer

# 開発用依存関係をインストール
pip install -e ".[dev]"
```

### コードスタイル

- Ruff を使用してフォーマット・リント
- 行長: 100文字

```bash
# リント
ruff check .

# フォーマット
ruff format .
```

### 新しいレビュワーの追加

1. `src/claude/reviewers/` に新しいレビュワーファイルを作成
2. `src/models/reviewer_type.py` に新しいタイプを追加
3. `src/claude/base_prompt.py` でレビュワーを登録
4. `config.example.yaml` の `enabled_reviewers` リストを更新

### プルリクエスト

1. フォークしてブランチを作成
2. 変更をコミット
3. プルリクエストを作成

## ライセンス

MIT License

## 関連リンク

- [Claude CLI (Claude Code)](https://github.com/anthropics/claude-code)
- [GitHub CLI](https://cli.github.com/)
