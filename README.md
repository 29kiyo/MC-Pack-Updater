# ⛏ MC Mod Updater

Minecraftのmodsフォルダを読み込み、指定バージョン向けに一括ダウンロードするツール。

## ダウンロード

→ **[Releases](../../releases)** から `MC-Mod-Updater.exe` をダウンロード

（pushするたびにGitHub Actionsが自動でEXEをビルドしてReleaseに公開します）

## 使い方

1. `MC-Mod-Updater.exe` を起動
2. **⚙設定タブ** でmodsフォルダ・MCバージョン・Loaderを指定
3. ダウンロードモードを選択
   - `両方（Modrinth優先）` … Modrinthで検索→なければCurseForge（推奨）
   - `Modrinthのみ` … APIキー不要
   - `CurseForgeのみ` … APIキー必須
4. CurseForgeを使う場合はAPIキーを入力（設定は自動保存）
5. **「Modを読み込む」** でJAR一覧を表示
6. **📦Mod一覧タブ** で更新したいModにチェック
7. **「アップデート開始」**

## CurseForge APIキーの取得

1. https://console.curseforge.com/ にアクセス
2. アカウント作成・ログイン
3. 「Create API Key」でキーを生成
4. ツールのAPIキー欄に貼り付け（次回起動時も自動で読み込まれます）

## 対応Mod Loader

- Fabric / Quilt（fabric.mod.json / quilt.mod.json を解析）
- Forge / NeoForge（mods.toml / neoforge.mods.toml を解析）

## 自分でビルドする場合

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "MC-Mod-Updater" mod_updater.py
# dist/MC-Mod-Updater.exe が生成されます
```
