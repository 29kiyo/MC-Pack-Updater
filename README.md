# ⛏ MC Pack Updater

Minecraft の Mod / ResourcePack / Shader を一括アップデートするツール。

## ダウンロード

→ **[Releases](../../releases)** から最新版をダウンロード

| ファイル | 説明 |
|---|---|
| `MC-Pack-Updater.zip` | 推奨。解凍してフォルダ内の `MC-Pack-Updater.exe` を実行 |
| `MC-Pack-Updater.exe` | 単体EXE。SmartScreenの警告が出る場合あり |

## 使い方

1. `MC-Pack-Updater.exe` を起動
2. **⚙ 設定タブ** で起動構成フォルダ or 個別フォルダを指定
3. MCバージョン・Mod Loaderを選択
4. ダウンロードモードを選択
5. **「📂 全て読み込む」** か個別で読み込むを押すと一覧に表示
6. **📦 一覧タブ** で更新したいものにチェック
7. **「⬇ アップデート」** または **「🔄 全て一括アップデート」**

基本的に読み込んだ後にアップデートです。

## 起動構成フォルダについて

`.minecraft` 内の起動構成フォルダ（例: `C:\Users\user\AppData\Roaming\.minecraft\fabric\1.21.4`）を指定すると `mods/` `resourcepacks/` `shaderpacks/` を自動検出して一括読み込みできます。

## 対応ダウンロード元

| サービス | APIキー | 対応コンテンツ |
|---|---|---|
| Modrinth | 不要 | Mod / ResourcePack / Shader |
| CurseForge | 必要 | Mod / ResourcePack / Shader |

## CurseForge APIキーの取得

設定タブの「取得方法 ↗」ボタンを押すと案内が表示されます。または [https://console.curseforge.com/](https://console.curseforge.com/) から取得してください。

## 対応 Mod Loader

| Loader | 最小MCバージョン |
|---|---|
| Fabric | 1.14 |
| Forge | 1.1 |
| Quilt | 1.16 |
| NeoForge | 1.20.1 |

## 機能一覧

- 起動構成フォルダを1つ指定で全自動検出
- Mod / ResourcePack / Shader それぞれ個別または一括アップデート
- 前提Modの自動ダウンロード
- 古いファイル削除オプション
- ダウンロード失敗ファイルの自動削除オプション
- 設定の自動保存

## 使用上の注意点
起動構成フォルダを直接開いて使えますが、その起動構成がそのまま使えるとは限りません。念のためバックアップを取った後にアップデートしましょう。

## 免責事項
本ツールの使用によって生じたいかなる損害についても、作者は一切の責任を負いません。自己責任でご使用ください。
また、本ツールはMinecraftおよび各Modの公式ツールではありません。Mojang Studios、CurseForge、Modrinthとは一切関係ありません。

## 開発について
このツールのコードはすべてAI(Claude)を使って作成されています。
