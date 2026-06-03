# Contributing to MC Pack Updater

Minecraft の Mod / ResourcePack / Shader / Plugin を一括アップデートするツールへの
コントリビューションガイドです。

---

## 目次

1. [開発環境の構築](#開発環境の構築)
2. [プロジェクト構成](#プロジェクト構成)
3. [ローカルでの実行](#ローカルでの実行)
4. [EXE ビルド手順](#exe-ビルド手順)
5. [API・動作テスト](#api動作テスト)
6. [CI / GitHub Actions](#ci--github-actions)
7. [コーディング規約](#コーディング規約)

---

## 開発環境の構築

### 必要なもの

| ツール | バージョン | 備考 |
|---|---|---|
| Python | **3.11** 推奨 | GitHub Actions と合わせる |
| pip | 最新版 | Python に同梱 |
| Git | 任意 | クローン・PR に必要 |

> **Windows が必須です。**  
> GUI に `tkinter`、ビルドに `PyInstaller (Windows)` を使用しているため、
> macOS / Linux では実行・ビルドができません。

### セットアップ手順

```bash
# 1. リポジトリをクローン
git clone https://github.com/<your-fork>/MC-Pack-Updater.git
cd MC-Pack-Updater

# 2. 依存パッケージをインストール
pip install -r requirements.txt
```

`requirements.txt` の内容：

```
pyinstaller   # EXEビルド用（開発時に動作確認する際は不要）
pymupdf       # PDF表示用（assets/API Key Guide.pdf の読み込みに使用）
Pillow        # 画像処理用（全体設定タブのGitHubボタン画像の読み込みに使用）
```

> **注意：** `pyinstaller` は EXE ビルドに必要ですが、
> スクリプトをそのまま実行する場合はインストールしなくても動作します。

---

## プロジェクト構成

```
MC-Pack-Updater/
├── src/
│   ├── mod_updater.py      # メイン（Mod/ResourcePack/Shader のUI・ロジック）
│   └── plugin_updater.py   # プラグインタブのUI・ロジック
├── assets/
│   ├── icon.ico                  # アプリアイコン
│   ├── API Key Guide.pdf         # CurseForge APIキー取得ガイド
│   ├── GitHub_Lockup_Black.ico   # 全体設定タブのGitHubボタン画像（ライトモード用）
│   ├── GitHub_Lockup_White.ico   # 全体設定タブのGitHubボタン画像（ダークモード用）
│   ├── lightmode.png             # READMEスクリーンショット（ライトモード）
│   ├── darkmode.png              # READMEスクリーンショット（ダークモード）
│   └── version_info.txt          # PyInstaller 用バージョン情報
├── .github/
│   └── workflows/
│       ├── build.yml           # EXEビルド & リリース CI
│       ├── codeql.yml          # CodeQL セキュリティスキャン
│       ├── delete-releases.yml # 古いリリースの自動削除
│       └── delete-runs.yml     # 古いワークフロー実行の自動削除
├── requirements.txt
├── LICENSE
├── CONTRIBUTING.md
└── README.md
```

### アーキテクチャ概要

- **`mod_updater.py`** ― アプリのエントリポイント。`tkinter` で GUI を構築し、
  Modrinth / CurseForge API を `urllib` で直接叩く。GitHubボタンの画像表示に `Pillow` を使用。
  PyInstaller でのバンドルを容易にするため外部ライブラリの使用は最小限にしている。
- **`plugin_updater.py`** ― プラグインタブの実装。EXE ビルド時に
  `--add-data` でバンドルされ、`mod_updater.py` から動的に読み込まれる。
  埋め込み時は `parent_app` 経由で `mod_updater.py` の進捗バー・中止ボタンを共有する。

### バックアップモードの仕組み

バックアップモードは **全体設定タブ** で管理される全体設定です。

- 設定値は `App.backup_mode`（`BooleanVar`）・`App.backup_dir`（`StringVar`）で保持。
- `mod_updater.py` の `_worker` では `_backup_ts`（実行開始時のタイムスタンプ）を一度だけ生成し、
  同一実行内の全タイプ（mods / resourcepacks / shaderpacks）で共有します。
- `plugin_updater.py` の `_worker` では `parent_app.backup_mode` / `parent_app.backup_dir` / `parent_app.target_version` を参照してバックアップフォルダを決定します。
- バックアップモードON時は `delete_old` / `delete_failed` / `old_path` をすべて無効化し、元ファイルへの変更を一切行いません。

出力フォルダ構造：
```
[出力先]/
  └─ v{MCバージョン}_{YYYY-MM-DD}_{HH-MM-SS}/
       ├─ mods
       ├─ resourcepacks
       ├─ shaderpacks
       └─ plugins
```

---

## ローカルでの実行

```bash
python src/mod_updater.py
```

GUI ウィンドウが起動します。  
初回起動時に設定ファイル `~/.mc_pack_updater_config.json` が自動生成されます。

---

## EXE ビルド手順

### onedir（推奨・フォルダ形式）

```powershell
pyinstaller --onedir --windowed --noupx --name "MC-Pack-Updater" `
  --icon assets\icon.ico `
  --add-data "assets\icon.ico;." `
  --add-data "assets\API Key Guide.pdf;." `
  --add-data "assets\GitHub_Lockup_Black.ico;." `
  --add-data "assets\GitHub_Lockup_White.ico;." `
  --add-data "src\plugin_updater.py;." `
  --version-file assets\version_info.txt `
  --hidden-import PIL `
  --hidden-import PIL `
  src\mod_updater.py

# ZIP化
Compress-Archive -Path dist\MC-Pack-Updater -DestinationPath dist\MC-Pack-Updater.zip
```

### onefile（単体 EXE）

```powershell
pyinstaller --onefile --windowed --noupx --name "MC-Pack-Updater" `
  --icon assets\icon.ico `
  --add-data "assets\icon.ico;." `
  --add-data "assets\API Key Guide.pdf;." `
  --add-data "assets\GitHub_Lockup_Black.ico;." `
  --add-data "assets\GitHub_Lockup_White.ico;." `
  --add-data "src\plugin_updater.py;." `
  --version-file assets\version_info.txt `
  src\mod_updater.py
```

成果物は `dist/` フォルダに出力されます。

> `--noupx` は UPX 圧縮を無効化するオプションです。UPX はセキュリティソフトの
> 誤検知を増やすため、このプロジェクトでは使用しません。

---

## API・動作テスト

本プロジェクトが使用する外部 API のエンドポイントです。
Modrinth API はキー不要で利用できます。

### Modrinth API

| 目的 | エンドポイント |
|---|---|
| MCバージョン一覧 | `GET /v2/tag/game_version` |
| Mod 検索 | `GET /v2/search?query=...&facets=...` |
| バージョン一覧 | `GET /v2/project/{id}/version` |
| ハッシュ照合 | `GET /v2/version_file/{hash}?algorithm=sha512` |

**User-Agent の設定が必須です。**  
本ツールでは `MC-Pack-Updater/6.0` を送信しています。
未設定だと Modrinth から `403 Forbidden` が返ります。

簡易テストスクリプト：

```python
import urllib.request, json

def http_get(url):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MC-Pack-Updater/6.0")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

# MCバージョン一覧
tags = http_get("https://api.modrinth.com/v2/tag/game_version")
releases = [t["version"] for t in tags if t.get("version_type") == "release"][:5]
print("最新MCバージョン:", releases)

# Sodium を検索
import urllib.parse
facets = json.dumps([["project_type:mod"],["categories:fabric"],["versions:1.21.4"]])
result = http_get(f"https://api.modrinth.com/v2/search?query=sodium&facets={urllib.parse.quote(facets)}&limit=3")
for h in result["hits"]:
    print(h["title"], h["project_id"], f"DL:{h['downloads']:,}")
```

### CurseForge API

[https://console.curseforge.com/](https://console.curseforge.com/) で APIキーを取得し、
設定タブに入力してください。テスト時は環境変数などで管理することを推奨します。

---

## CI / GitHub Actions

### `build.yml` ― EXEビルド & リリース

| トリガー | 動作 |
|---|---|
| `main` ブランチへの push（README.md 以外） | EXE をビルドして Artifact としてアップロード（7日保持） |
| `workflow_dispatch`（手動実行） | EXE をビルドして GitHub Release を作成。直前のリリースをプレリリースに降格。 |

**実行環境：** `windows-2025-vs2026` / Python 3.11

### `delete-releases.yml` / `delete-runs.yml`

古いリリース・ワークフロー実行を自動削除してリポジトリをクリーンに保ちます。

---

## コーディング規約

- 標準ライブラリのみを使用（`urllib`・`tkinter`・`json` 等）。
  外部ライブラリの追加は `requirements.txt` と `--add-data` の両方への追記が必要です。
- GUI コードと API ロジックは同一ファイル内で分離せずに記述しています
  （小規模ツールのためシンプルさを優先）。
- テーマ（ライト / ダーク）は `THEMES` 辞書で一元管理しています。
  色の追加・変更はここのみを編集してください。
- 設定の永続化は `~/.mc_pack_updater_config.json` に JSON 形式で行います。
  新しい設定項目を追加する場合は `load_config()` / `save_config()` を利用してください。
- `plugin_updater.py` の `PluginUpdaterApp` は埋め込み時に `parent_app` 引数で `mod_updater.py` の `App` インスタンスを受け取ります。
  進捗バー・中止ボタン・バックアップモード設定など共有リソースはすべて `parent_app` 経由でアクセスしてください。
  `parent_app` が `None`（スタンドアロン起動）のケースも考慮し、`hasattr` でガードを入れてください。
