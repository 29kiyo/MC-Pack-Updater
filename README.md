# ⛏ MC Pack Updater

Minecraft の Mod / ResourcePack / Shader / Plugin を一括アップデートするツール。

## ダウンロード

→ **[Releases](../../releases)** から最新版をダウンロード

| ファイル | 説明 |
|---|---|
| `MC-Pack-Updater.zip` | 推奨。解凍してフォルダ内の `MC-Pack-Updater.exe` を実行 |
| `MC-Pack-Updater.exe` | 単体EXE。SmartScreenの警告が出る場合あり |

## 使い方

### Mod / ResourcePack / Shader

1. `MC-Pack-Updater.exe` を起動
2. **⚙ 設定タブ** で起動構成フォルダ or 個別フォルダを指定
3. MCバージョン・Mod Loaderを選択
4. ダウンロードモードを選択
5. **「📂 全て読み込む」** で一覧に表示
6. **📦 一覧タブ** で更新したいものにチェック
7. 必要に応じてバージョンを個別指定（右サイドパネル）
8. **「⬇ アップデート」** または **「🔄 全て一括アップデート」**

> ⚠ 起動構成フォルダを直接読み込んで使えますが、その起動構成がそのまま使えるとは限りません。念のためバックアップを取った後にアップデートしましょう。

### Plugin

1. **🔌 プラグインタブ** を開く
2. **⚙ 設定** で `plugins` フォルダを指定
3. **「📂 読み込む」** でプラグイン一覧を表示
4. 更新したいプラグインにチェック
5. 必要に応じて右サイドパネルでバージョンを指定
6. **「⬇ ダウンロード」**

> ⚠ プラグインはModrinthからダウンロードします。お使いのMinecraftサーバーのバージョンやPlugin Loader（Spigot / Paper / Purpur / Velocity等）で正常に動作するとは限りません。必ずバックアップを取ってからご使用ください。

## 起動構成フォルダについて

`.minecraft` 内の起動構成フォルダ（例: `C:\Users\owner\AppData\Roaming\.minecraft\fabric\1.21.4`）を指定すると `mods/` `resourcepacks/` `shaderpacks/` を自動検出して一括読み込みできます。

## 対応ダウンロード元

| コンテンツ | サービス | APIキー |
|---|---|---|
| Mod / ResourcePack / Shader | Modrinth | 不要 |
| Mod / ResourcePack / Shader | CurseForge | 必要 |
| Plugin | Modrinth | 不要 |

### CurseForge APIキーの取得

設定タブの「取得方法 ↗」ボタンを押すと案内が表示されます。または [https://console.curseforge.com/](https://console.curseforge.com/) から取得してください。

## 対応 Mod Loader

| Loader | 最小MCバージョン |
|---|---|
| Fabric | 1.14 |
| Forge | 1.1 |
| NeoForge | 1.20.1 |

## 機能一覧

- 起動構成フォルダを1つ指定で全自動検出
- Mod / ResourcePack / Shader それぞれ個別または一括アップデート
- プラグインの一括アップデート（Modrinth）
- バージョン個別指定（サイドパネル）
- 前提Mod・前提プラグインの自動ダウンロード
- ダウンロード失敗ファイルの自動削除オプション
- A-Z順表示
- ダウンロード中止ボタン
- ライト / ダークモード切り替え
- トースト通知（読み込み完了時）
- 設定の自動保存

## 免責事項

本ツールの使用によって生じたいかなる損害についても、作者は一切の責任を負いません。自己責任でご使用ください。本ツールはMinecraftおよび各Modの公式ツールではありません。Mojang Studios、CurseForge、Modrinthとは一切関係ありません。

## 開発について

このツールのコードはすべてAI（Claude）に書いてもらいました。
