import os, re, sys, json, zipfile, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import urllib.request, urllib.parse

MODRINTH_API = "https://api.modrinth.com/v2"
CONFIG_FILE  = os.path.join(os.path.expanduser("~"), ".mc_pack_updater_config.json")

# プラグインローダー選択肢
# (表示名, Modrinth loaders リスト)
PLUGIN_LOADERS = [
    ("すべて（自動）",          ["spigot", "bukkit", "paper", "purpur",
                                 "sponge", "bungeecord", "bungee", "waterfall", "velocity"]),
    ("Plugin Loader（すべて）", ["spigot", "bukkit", "paper", "purpur", "folia", "sponge"]),
    ("プロキシ（すべて）",      ["bungeecord", "bungee", "waterfall", "velocity"]),
    # ── 複合 ──
    ("Spigot / Bukkit",         ["spigot", "bukkit"]),
    ("Paper / Purpur",          ["paper", "purpur"]),
    ("Spigot / Paper",          ["spigot", "paper"]),
    # ── ローダー ──
    ("Bukkit",                  ["bukkit"]),
    ("Folia",                   ["folia"]),
    ("Paper",                   ["paper"]),
    ("Purpur",                  ["purpur"]),
    ("Spigot",                  ["spigot"]),
    ("Sponge",                  ["sponge"]),
    # ── プラットフォーム（プロキシ）──
    ("BungeeCord",              ["bungeecord", "bungee", "waterfall"]),
    ("Velocity",                ["velocity"]),
    ("Waterfall",               ["waterfall", "bungeecord"]),
]
PLUGIN_LOADER_NAMES = [entry[0] for entry in PLUGIN_LOADERS]
PLUGIN_LOADER_MAP   = {entry[0]: entry[1] for entry in PLUGIN_LOADERS}

THEMES = {
    "light": {
        "BG":       "#f4f4f0",
        "BG2":      "#e8e8e3",
        "BG3":      "#d0d0c8",
        "FG":       "#1e1e1e",
        "ACC":      "#1d4ed8",
        "GRN":      "#15803d",
        "RED":      "#dc2626",
        "YEL":      "#92400e",
        "LOG":      "#ffffff",
        "SEL":      "#bfdbfe",
        "SEL_FG":   "#1e1e1e",
        "BTN_FG":   "#ffffff",
        "BTN_ACT":  "#3b82f6",
        "BTN_DIS":  "#d0d0c8",
        "TREE_SEL": "#bfdbfe",
        "ICON":     "🌙",
    },
    "dark": {
        "BG":       "#1e1e2e",
        "BG2":      "#2a2a3e",
        "BG3":      "#45475a",
        "FG":       "#cdd6f4",
        "ACC":      "#89b4fa",
        "GRN":      "#a6e3a1",
        "RED":      "#f38ba8",
        "YEL":      "#f9e2af",
        "LOG":      "#181825",
        "SEL":      "#313244",
        "SEL_FG":   "#cdd6f4",
        "BTN_FG":   "#1e1e2e",
        "BTN_ACT":  "#74c7ec",
        "BTN_DIS":  "#45475a",
        "TREE_SEL": "#45475a",
        "ICON":     "☀️",
    },
}

# ── ユーティリティ ─────────────────────────────────────────────────────────────

# ── mod_updater.py との後方互換スタブ ──────────────────────────────────────
# mod_updater.py の _build_plugin_tab が動的インポート後に
# mod._apply_theme_globals(theme) を呼ぶため、空実装を用意しておく。
# テーマ状態は PluginUpdaterApp 内で self._theme として管理するため
# グローバル変数は不要だが、呼び出し自体は無害に受け流す。
def _apply_theme_globals(theme):
    pass

def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # 設定ファイルが存在しない・壊れている場合は空dictを返す
        return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:  # 設定保存失敗は起動に影響しないため無視
        pass

def http_get(url):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MC-Plugin-Updater/4.0")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def download_file(url, dest, progress_cb=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MC-Plugin-Updater/4.0")
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        done  = 0
        with open(dest, "wb") as f:
            while chunk := r.read(65536):
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(done / total)

def clean_plugin_name(raw):
    n = re.sub(r'[-_]v?\d+[\.\d]*[a-zA-Z\-]*$', '', raw, flags=re.I)
    n = re.sub(r'[-_](velocity|bukkit|paper|spigot|bungee|fabric|forge|folia)$', '', n, flags=re.I)
    return n.strip("-_ ") or raw

def read_jar_meta(jar_path):
    fname     = os.path.basename(jar_path)
    base_name = clean_plugin_name(os.path.splitext(fname)[0])
    info      = {"filename": fname, "path": jar_path, "name": base_name, "version": "", "depend": [], "loader": "unknown"}
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = zf.namelist()
            # ── Velocity ──
            if "velocity-plugin.json" in names:
                d = json.loads(zf.read("velocity-plugin.json").decode("utf-8", errors="ignore"))
                info["name"]    = d.get("name") or d.get("id") or base_name
                info["version"] = d.get("version", "")
                info["depend"]  = list(d.get("dependencies", {}).keys())
                info["loader"]  = "velocity"
                return info
            # ── Sponge ──
            if "sponge_plugins.json" in names:
                try:
                    d = json.loads(zf.read("sponge_plugins.json").decode("utf-8", errors="ignore"))
                    plugins = d.get("plugins", [d]) if isinstance(d, dict) else d
                    if plugins:
                        p0 = plugins[0]
                        info["name"]    = p0.get("name") or p0.get("id") or base_name
                        info["version"] = p0.get("version", "")
                except Exception:
                    pass
                info["loader"] = "sponge"
                return info
            yml = next((n for n in ("plugin.yml", "paper-plugin.yml", "bungee.yml") if n in names), None)
            if yml:
                raw = zf.read(yml).decode("utf-8", errors="ignore")
                folia_supported = False
                for line in raw.splitlines():
                    line = line.strip()
                    if line.startswith("name:"):
                        info["name"] = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("version:"):
                        info["version"] = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("depend:"):
                        ds = line.split(":", 1)[1].strip().strip("[]")
                        info["depend"] = [d.strip().strip('"\'') for d in ds.split(",") if d.strip()]
                    elif line.startswith("folia-supported:"):
                        folia_supported = line.split(":", 1)[1].strip().lower() == "true"
                if yml == "bungee.yml":
                    # BungeeCord / Waterfall は同じ bungee.yml を使う
                    info["loader"] = "bungeecord_waterfall"
                elif yml == "paper-plugin.yml":
                    # paper-plugin.yml は Paper / Folia 専用新形式
                    info["loader"] = "paper_folia"
                else:
                    # plugin.yml: Bukkit / Spigot / Paper / Purpur / Folia 共通
                    # folia-supported: true があれば Folia 対応を追記
                    info["loader"] = "bukkit_spigot_paper" + ("+folia" if folia_supported else "")
    except Exception:  # ZIPの読み込み失敗時はファイル名から推測したinfoを返す
        pass
    return info

# ── Modrinth API ───────────────────────────────────────────────────────────────

def mr_search_plugin(name):
    try:
        params = urllib.parse.urlencode({
            "query":  name,
            "limit":  5,
            "facets": json.dumps([["project_type:plugin"]]),
        })
        hits = http_get(f"{MODRINTH_API}/search?{params}").get("hits", [])
        if not hits:
            return None
        name_l = name.lower()
        for h in hits:
            if h.get("title", "").lower() == name_l:
                return h["project_id"]
        return hits[0]["project_id"]
    except Exception:  # API取得失敗時はNoneを返し呼び出し元でスキップ
        return None

def mr_get_plugin_versions(pid, loaders=None):
    try:
        if loaders is None:
            loaders = PLUGIN_LOADER_MAP["すべて（自動）"]
        params = urllib.parse.urlencode({
            "loaders": json.dumps(loaders),
        })
        return http_get(f"{MODRINTH_API}/project/{pid}/version?{params}")
    except Exception:  # API取得失敗時は空リストを返す
        return []

def mr_best_file(vo):
    du = df = None
    for fi in vo.get("files", []):
        if fi.get("primary") or not du:
            du, df = fi["url"], fi["filename"]
        if fi.get("primary"):
            break
    return du, df

def find_plugin(name, log_cb, ver_id=None, loaders=None):
    try:
        pid = mr_search_plugin(name)
        if not pid:
            log_cb("  Modrinth: 見つからず", "warn")
            return None, None, None
        if ver_id:
            vs = [http_get(f"{MODRINTH_API}/version/{ver_id}")]
        else:
            vs = mr_get_plugin_versions(pid, loaders)
        if not vs:
            log_cb("  Modrinth: 対応バージョンなし", "warn")
            return None, None, None
        dl_url, dl_fname = mr_best_file(vs[0])
        log_cb(f"  ✓ Modrinth: {dl_fname}", "ok")
        return dl_url, dl_fname, pid
    except Exception as e:
        log_cb(f"  Modrinth エラー: {e}", "err")
        return None, None, None

# ══════════════════════════════════════════════════════════════════════════════
# PluginUpdaterApp
# ══════════════════════════════════════════════════════════════════════════════

class PluginUpdaterApp(ttk.Frame):
    """
    プラグインアップデーター本体。
    - StandaloneApp（スタンドアロン起動）から使う場合も
    - mod_updater.py の App から埋め込みで使う場合も
    どちらでも動作する。

    テーマ切り替えは apply_theme(theme) を呼ぶ。
    tk.Label / tk.Canvas など ttk 管轄外のウィジェットは
    _tk_widgets リストに登録して一括更新する。
    """

    def __init__(self, parent, theme="light", icon_path=None, parent_app=None, **kw):
        super().__init__(parent, **kw)
        self._theme      = theme
        self._icon_path  = icon_path
        self._parent_app = parent_app
        self._running    = False
        self._cancel_flag = False

        # テーマ切り替え時に個別更新が必要な tk.Label / tk.Canvas を収集するリスト
        # 各エントリは (widget, color_key, attr) のタプル
        # color_key: THEMES[theme] のキー ("BG", "FG", …)
        # attr: "bg" / "fg" / "background" など
        self._tk_widgets: list[tuple] = []

        cfg = load_config()
        self.plugins_dir   = tk.StringVar(value=cfg.get("plugins_dir", ""))
        self.delete_old    = tk.BooleanVar(value=cfg.get("plugin_delete_old", False))
        self.delete_failed = tk.BooleanVar(value=cfg.get("plugin_delete_failed", False))
        self.auto_deps     = tk.BooleanVar(value=cfg.get("plugin_auto_deps", True))
        self.plugin_loader = tk.StringVar(value=cfg.get("plugin_loader", "すべて（自動）"))

        self.plugin_list    = []
        self._ver_overrides = {}   # filename -> {"id": ver_id, "label": str} or None
        self._current_iid   = None
        self._versions_cache = []

        # プラグイン検索タブ用
        self._psearch_running     = False
        self._psearch_cancel_flag = False
        self._psearch_items       = []
        self._psearch_ver_cache   = {}
        self._psearch_cur_iid     = None

        self._build()

    # ── ビルド ────────────────────────────────────────────────────────────────

    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        t_set = ttk.Frame(nb); nb.add(t_set, text=" ⚙ 設定 ")
        t_lst = ttk.Frame(nb); nb.add(t_lst, text=" 🔌 プラグイン一覧 ")
        t_log = ttk.Frame(nb); nb.add(t_log, text=" 📋 ログ ")
        t_ins = ttk.Frame(nb); nb.add(t_ins, text=" 🔍 検査 ")
        t_src = ttk.Frame(nb); nb.add(t_src, text=" 🔎 プラグイン検索 ")
        self._nb = nb

        self._build_settings(t_set)
        self._build_list(t_lst)
        self._build_log(t_log)
        self._build_inspect(t_ins)
        self._build_plugin_search(t_src)

    def _build_settings(self, p):
        t = THEMES[self._theme]
        f = ttk.Frame(p)
        f.pack(fill="both", expand=True, padx=2, pady=2)
        PAD = dict(padx=14, pady=(0, 8))

        # Plugins フォルダ
        lf0 = ttk.LabelFrame(f, text="🔌  Pluginsフォルダ")
        lf0.pack(fill="x", padx=14, pady=(8, 8))
        r0 = ttk.Frame(lf0)
        r0.pack(fill="x", padx=10, pady=8)
        ttk.Entry(r0, textvariable=self.plugins_dir).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(r0, text="参照",          command=lambda: self._browse(self.plugins_dir)).pack(side="left", padx=(0, 6))
        ttk.Button(r0, text="📂 読み込む",   command=self._load_plugins).pack(side="left", padx=(0, 6))
        ttk.Button(r0, text="⬇ ダウンロード", command=self._start_update).pack(side="left", padx=(0, 6))
        ttk.Button(r0, text="✕", command=lambda: self.plugins_dir.set(""), width=3).pack(side="left")

        # ダウンロード設定
        lf3 = ttk.LabelFrame(f, text="🌐  ダウンロード設定")
        lf3.pack(fill="x", **PAD)
        dl_info = tk.Label(
            lf3,
            text="  ℹ Modrinthを使用してダウンロードします",
            fg=t["YEL"], bg=t["BG"],
            font=("Yu Gothic UI", 9),
        )
        dl_info.pack(anchor="w", padx=10, pady=(8, 4))
        self._dl_info_label = dl_info
        self._tw(self._tk_widgets, dl_info, ("YEL", "fg"), ("BG", "bg"))

        # Plugin Loader 選択行
        loader_row = ttk.Frame(lf3)
        loader_row.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(loader_row, text="Plugin Loader:").pack(side="left", padx=(0, 8))
        self._loader_combo = ttk.Combobox(
            loader_row,
            textvariable=self.plugin_loader,
            values=PLUGIN_LOADER_NAMES,
            state="readonly",
            width=22,
        )
        self._loader_combo.pack(side="left")
        # マウスホイールでの誤操作を防ぐため後でまとめてバインドする
        # （_disable_combobox_wheel が一括処理）

        # すべて（自動）選択時の注意ラベル
        self._auto_warn_label = tk.Label(
            lf3,
            text="  ⚠ 「すべて（自動）」はPlugin Loader用とプロキシ用が混在する場合があります",
            fg=t["RED"], bg=t["BG"],
            font=("Yu Gothic UI", 9),
        )
        self._tw(self._tk_widgets, self._auto_warn_label, ("RED", "fg"), ("BG", "bg"))
        self._loader_combo.bind("<<ComboboxSelected>>", self._on_loader_change)
        self._on_loader_change()  # 初期表示

        # オプション
        lf4 = ttk.LabelFrame(f, text="⚙  オプション")
        lf4.pack(fill="x", **PAD)
        for txt, var in [
            ("アップデート後に古いファイルを削除する",                    self.delete_old),
            ("ダウンロード失敗したファイルを削除する（壊れたファイル除去）", self.delete_failed),
            ("前提プラグインが足りなければ自動でダウンロードする",          self.auto_deps),
        ]:
            ttk.Checkbutton(lf4, text=txt, variable=var).pack(padx=10, pady=2, anchor="w")

        # 注意
        lf5 = ttk.LabelFrame(f, text="⚠  注意")
        lf5.pack(fill="x", **PAD)
        msg = (
            "このツールはModrinthを使用してプラグインをダウンロードします。\n\n"
            "プラグインのダウンロード・アップデートはできますが、"
            "お使いのMinecraftサーバーのバージョンや"
            "Plugin Loader（Spigot / Paper / Purpur / Velocity等）で"
            "正常に動作するとは限りません。\n\n"
            "アップデート前に必ずバックアップを取り、自己責任でご使用ください。"
        )
        warn = tk.Label(
            lf5, text=msg,
            justify="left", anchor="nw",
            fg=t["RED"], bg=t["BG"],
            font=("Yu Gothic UI", 9),
        )
        warn.pack(padx=10, pady=8, anchor="nw", fill="x", expand=True)
        def _update_plugin_warn_wrap(e, lbl=warn):
            lbl.configure(wraplength=max(100, e.width - 20))
        lf5.bind("<Configure>", _update_plugin_warn_wrap)
        self._warn_label = warn
        self._tw(self._tk_widgets, warn, ("RED", "fg"), ("BG", "bg"))

        ttk.Frame(f, height=10).pack()

    def _build_list(self, p):
        top = ttk.Frame(p)
        top.pack(fill="x", padx=6, pady=(6, 2))
        for text, w, cmd in [
            ("全選択", 6, lambda: self._sel_all(True)),
            ("全解除", 6, lambda: self._sel_all(False)),
        ]:
            ttk.Button(top, text=text, width=w, command=cmd).pack(side="left", padx=(0, 3))
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=(0, 6), pady=2)
        ttk.Button(top, text="📂 読込", width=7, command=self._load_plugins).pack(side="left", padx=(0, 3))
        ttk.Button(top, text="⬇ 更新", width=7, command=self._start_update).pack(side="left")
        self._sel_label = ttk.Label(top, text="0 / 0 件", width=12, anchor="e")
        self._sel_label.pack(side="right", padx=4)

        body = ttk.Frame(p)
        body.pack(fill="both", expand=True)

        # 左: Treeview
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        cols  = ("chk", "name", "version")
        heads = [("chk", "✔", 36), ("name", "プラグイン名", 220), ("version", "バージョン", 90)]
        self._tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="none")
        for cid, lbl, w in heads:
            self._tree.heading(cid, text=lbl)
            self._tree.column(
                cid, width=w,
                minwidth=w if cid != "name" else 80,
                anchor="center" if cid == "chk" else "w",
                stretch=(cid == "name"),
            )
        vsb = ttk.Scrollbar(left, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=(0, 4))
        vsb.pack(side="left", fill="y", pady=(0, 4), padx=(0, 4))
        self._tree.bind("<Button-1>",       self._on_click)
        self._tree.bind("<ButtonRelease-1>", self._on_select)

        # 右: サイドパネル
        self._side = ttk.LabelFrame(body, text="  📋 詳細  ")
        self._side.pack(side="left", fill="y", padx=(4, 4), pady=(0, 4))
        self._side.configure(width=220)
        self._side.pack_propagate(False)

        t = THEMES[self._theme]
        # スクロールなしのシンプルなフレーム
        sf = tk.Frame(self._side, bg=t["BG"])
        sf.pack(fill="both", expand=True)
        # _side_canvas/_side_frame はapply_themeで参照されるため両方sfを指す
        self._side_canvas = sf
        self._side_frame  = sf
        self._tw(self._tk_widgets, sf, ("BG", "bg"))

        # サイドパネル内のラベルは tk.Label で作り bg を直接管理する
        lbl_sel = tk.Label(sf, text="選択中:", font=("Yu Gothic UI", 8),
                           bg=t["BG"], fg=t["FG"])
        lbl_sel.pack(anchor="w", padx=8, pady=(8, 0))
        self._tw(self._tk_widgets, lbl_sel, ("BG", "bg"), ("FG", "fg"))

        self._side_name = tk.Label(sf, text="—", wraplength=195,
                                   font=("Yu Gothic UI", 9, "bold"),
                                   bg=t["BG"], fg=t["FG"], justify="left")
        self._side_name.pack(anchor="w", padx=8, pady=(0, 6))
        self._tw(self._tk_widgets, self._side_name, ("BG", "bg"), ("FG", "fg"))

        # Separator は tk.Frame で代替（ttk.Separator は bg 制御が複雑）
        sep = tk.Frame(sf, height=1, bg=t["BG3"])
        sep.pack(fill="x", padx=8, pady=4)
        self._tw(self._tk_widgets, sep, ("BG3", "bg"))

        lbl_ver = tk.Label(sf, text="バージョン:", font=("Yu Gothic UI", 10),
                           bg=t["BG"], fg=t["FG"])
        lbl_ver.pack(anchor="w", padx=8, pady=(0, 2))
        self._tw(self._tk_widgets, lbl_ver, ("BG", "bg"), ("FG", "fg"))

        self._ver_var   = tk.StringVar(value="最新")
        self._ver_combo = ttk.Combobox(sf, textvariable=self._ver_var, state="readonly", width=24)
        self._ver_combo.pack(padx=8, pady=(0, 2), fill="x")
        self._ver_combo.bind("<<ComboboxSelected>>", self._on_ver_select)

        # バージョン状態ラベル（色は apply_theme / 各操作で動的に設定）
        self._ver_status_side = tk.Label(sf, text="", font=("Yu Gothic UI", 8),
                                         bg=t["BG"], fg=t["FG"])
        self._ver_status_side.pack(anchor="w", padx=8, pady=(0, 4))
        self._tw(self._tk_widgets, self._ver_status_side, ("BG", "bg"))
        # fg は状態に応じて変わるため BG だけ登録し、fg は _refresh_ver_status_color で管理

        ttk.Button(sf, text="🔄 バージョン取得", command=self._fetch_versions_side).pack(padx=8, pady=(0, 8), fill="x")

    def _on_loader_change(self, e=None):
        """「すべて」系選択時のみ混在警告ラベルを表示する"""
        sel = self.plugin_loader.get()
        warn_map = {
            "すべて（自動）":          "  ⚠ Plugin Loader用とプロキシ用が混在する場合があります",
            "Plugin Loader（すべて）": "  ⚠ 複数のPlugin Loaderが混在する場合があります",
            "プロキシ（すべて）":      "  ⚠ 複数のプロキシ用Loaderが混在する場合があります",
        }
        if sel in warn_map:
            self._auto_warn_label.config(text=warn_map[sel])
            self._auto_warn_label.pack(anchor="w", padx=10, pady=(0, 8))
        else:
            self._auto_warn_label.pack_forget()

    # ══════════════════════════════════════════════════════════════
    # プラグイン検索タブ（子タブ構成：設定 / 一覧 / ログ）
    # ══════════════════════════════════════════════════════════════
    def _build_plugin_search(self, p):
        self._psearch_tk_widgets = []

        snb = ttk.Notebook(p)
        snb.pack(fill="both", expand=True)
        self._psearch_nb = snb

        t_cfg = ttk.Frame(snb); snb.add(t_cfg, text=" ⚙ 設定 ")
        t_lst = ttk.Frame(snb); snb.add(t_lst, text=" 📋 一覧 ")
        t_log = ttk.Frame(snb); snb.add(t_log, text=" 📄 ログ ")

        self._psearch_build_settings(t_cfg)
        self._psearch_build_list(t_lst)
        self._psearch_build_log(t_log)

    # ── 設定タブ ──────────────────────────────────────────────────
    def _psearch_build_settings(self, p):
        t = self._t()
        f = ttk.Frame(p); f.pack(fill="both", expand=True, padx=2, pady=2)
        PAD = dict(padx=14, pady=(0,8))

        # 入力エリア
        lf_input = ttk.LabelFrame(f, text="🔎  プラグイン名入力 / ファイル読み込み")
        lf_input.pack(fill="x", padx=14, pady=(8,8))

        ph_lbl = tk.Label(lf_input,
            text=(
                "【入力方法】 プラグイン名をカンマ（,）または改行で区切って入力してください。\n"
                "  ・名前にスペースが含まれる場合は正確に入力してください。\n"
                "    例: EssentialsX → 「EssentialsX」 / LuckPerms → 「LuckPerms」\n"
                "  ・Modrinthのスラッグ（プロジェクトID）を使うと確実です。\n"
                "    例: luckperms, essentialsx, vault, worldedit\n"
                "  ・ファイルから読み込む場合は下のボタンを使用してください。"
            ),
            fg=t["ACC"], bg=t["BG2"],
            font=("Yu Gothic UI",8), anchor="w", justify="left",
            padx=8, pady=4)
        ph_lbl.pack(fill="x", padx=8, pady=(6,2))
        self._tw(self._psearch_tk_widgets, ph_lbl, ("ACC", "fg"), ("BG2", "bg"))

        self._psearch_input = scrolledtext.ScrolledText(
            lf_input,
            bg=t["LOG"], fg=t["FG"],
            selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
            insertbackground=t["FG"],
            font=("Yu Gothic UI",10), relief="flat", height=4, wrap="word")
        self._psearch_input.frame.configure(background=t["LOG"])
        self._psearch_input.pack(fill="x", padx=8, pady=(0,4))

        file_row = ttk.Frame(lf_input); file_row.pack(fill="x", padx=8, pady=(0,4))
        ttk.Button(file_row, text="📄 .txt/.csv 読込", command=self._psearch_load_txt).pack(side="left", padx=(0,4))
        ttk.Button(file_row, text="📋 .json 読込",     command=self._psearch_load_json).pack(side="left", padx=(0,4))
        ttk.Button(file_row, text="🗑 クリア",          command=lambda: self._psearch_input.delete("1.0","end")).pack(side="left", padx=(0,4))
        ttk.Button(file_row, text="📋 リストに追加",    command=self._psearch_add_to_list).pack(side="left")

        note_lbl = tk.Label(lf_input,
            text="  ℹ 対応: .txt（カンマ区切り / 1行1プラグイン）/ .csv / .json（配列 or {\"plugins\":[...]} or キー名をプラグイン名として使用）",
            fg=t["YEL"], bg=t["BG"], font=("Yu Gothic UI",8), anchor="w", justify="left")
        note_lbl.pack(fill="x", padx=8, pady=(0,6))
        self._tw(self._psearch_tk_widgets, note_lbl, ("YEL", "fg"), ("BG", "bg"))

        # 設定
        mid_row = ttk.Frame(f); mid_row.pack(fill="x", **PAD)
        mid_row.columnconfigure(0, weight=1); mid_row.columnconfigure(1, weight=1)

        lf_dl = ttk.LabelFrame(mid_row, text="🎯  ダウンロード先・Loader")
        lf_dl.grid(row=0, column=0, sticky="nsew", padx=(0,6))

        r_dir = ttk.Frame(lf_dl); r_dir.pack(fill="x", padx=10, pady=(8,4))
        ttk.Label(r_dir, text="保存先フォルダ:").pack(side="left")
        self._psearch_dl_dir = tk.StringVar(value=self.plugins_dir.get())
        ttk.Entry(r_dir, textvariable=self._psearch_dl_dir).pack(side="left", padx=(4,4), fill="x", expand=True)
        ttk.Button(r_dir, text="参照", command=lambda: self._psearch_browse(), width=4).pack(side="left", padx=(0,4))
        ttk.Button(r_dir, text="✕", command=lambda: self._psearch_dl_dir.set(""), width=3).pack(side="left")

        r_ldr = ttk.Frame(lf_dl); r_ldr.pack(fill="x", padx=10, pady=(0,8))
        ttk.Label(r_ldr, text="Plugin Loader:").pack(side="left")
        self._psearch_loader_var = tk.StringVar(value=self.plugin_loader.get())
        ldr_cb = ttk.Combobox(r_ldr, textvariable=self._psearch_loader_var,
                               values=PLUGIN_LOADER_NAMES, width=22, state="readonly")
        ldr_cb.pack(side="left", padx=(4,0))

        lf_opt = ttk.LabelFrame(mid_row, text="⚙  オプション")
        lf_opt.grid(row=0, column=1, sticky="nsew")
        self._psearch_auto_deps   = tk.BooleanVar(value=True)
        self._psearch_strict_deps = tk.BooleanVar(value=False)
        ttk.Checkbutton(lf_opt,
            text="前提プラグインが足りなければ自動でダウンロードする",
            variable=self._psearch_auto_deps).pack(padx=10, pady=(8,2), anchor="w")
        ttk.Checkbutton(lf_opt,
            text="前提プラグインのバージョンを厳密に指定する（不安定な場合はOFF）",
            variable=self._psearch_strict_deps).pack(padx=10, pady=(0,8), anchor="w")

        # 注意
        lf_warn = ttk.LabelFrame(f, text="⚠  注意")
        lf_warn.pack(fill="x", **PAD)
        warn_msg = (
            "ここではプラグイン名（またはModrinthスラッグ）を直接指定してModrinthから\n"
            "ダウンロードします。名前が完全一致しない場合、意図しないプラグインがDLされることがあります。\n"
            "Plugin Loaderとの互換性は保証されません。\n"
            "必ずバックアップを取ってから使用してください。"
        )
        warn_lbl = tk.Label(lf_warn, text=warn_msg,
                             justify="left", anchor="nw",
                             fg=t["RED"], bg=t["BG"], font=("Yu Gothic UI",9))
        warn_lbl.pack(padx=10, pady=8, fill="x", expand=True, anchor="nw")
        self._tw(self._psearch_tk_widgets, warn_lbl, ("RED", "fg"), ("BG", "bg"))
        def _upd_wrap(e, lbl=warn_lbl):
            lbl.configure(wraplength=max(100, e.width-20))
        lf_warn.bind("<Configure>", _upd_wrap)
        ttk.Frame(f, height=8).pack()

    # ── 一覧タブ ──────────────────────────────────────────────────
    def _psearch_build_list(self, p):
        t = self._t()

        tb = ttk.Frame(p); tb.pack(fill="x", padx=6, pady=(6,2))
        for text, w, cmd in [("全選択",6,lambda: self._psearch_sel_all(True)),
                               ("全解除",6,lambda: self._psearch_sel_all(False))]:
            ttk.Button(tb, text=text, width=w, command=cmd).pack(side="left", padx=(0,3))
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=(0,6), pady=2)
        ttk.Button(tb, text="📋 リストに追加", command=self._psearch_add_to_list).pack(side="left", padx=(0,3))
        ttk.Button(tb, text="🗑 選択削除",     command=self._psearch_remove_selected).pack(side="left", padx=(0,3))
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=(0,6), pady=2)
        ttk.Button(tb, text="⬇ 選択をDL",     command=self._psearch_start_download).pack(side="left")
        self._psearch_sel_label = ttk.Label(tb, text="0 / 0 件", width=12, anchor="e")
        self._psearch_sel_label.pack(side="right", padx=4)

        body = ttk.Frame(p); body.pack(fill="both", expand=True)

        # 左: Treeview
        left = ttk.Frame(body); left.pack(side="left", fill="both", expand=True)
        cols = ("chk","name","status")
        self._psearch_tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="none")
        self._psearch_tree.heading("chk",    text="✔")
        self._psearch_tree.heading("name",   text="プラグイン名")
        self._psearch_tree.heading("status", text="状態")
        self._psearch_tree.column("chk",    width=36,  minwidth=36,  anchor="center", stretch=False)
        self._psearch_tree.column("name",   width=240, minwidth=80,  anchor="w",      stretch=True)
        self._psearch_tree.column("status", width=160, minwidth=60,  anchor="w",      stretch=False)
        vsb = ttk.Scrollbar(left, orient="vertical", command=self._psearch_tree.yview)
        self._psearch_tree.configure(yscrollcommand=vsb.set)
        self._psearch_tree.pack(side="left", fill="both", expand=True, padx=(4,0), pady=(0,4))
        vsb.pack(side="left", fill="y", pady=(0,4), padx=(0,4))
        self._psearch_tree.bind("<Button-1>",        self._psearch_on_click)
        self._psearch_tree.bind("<<TreeviewSelect>>", self._psearch_on_select)
        self._psearch_tree.bind("<ButtonRelease-1>",  self._psearch_on_select)

        # 右: サイドパネル
        side = ttk.LabelFrame(body, text="  📋 詳細  ")
        side.pack(side="left", fill="y", padx=(4,4), pady=(0,4))
        side.configure(width=220); side.pack_propagate(False)

        sf = tk.Frame(side, bg=t["BG"])
        sf.pack(fill="both", expand=True)
        self._psearch_side_frame = sf
        self._tw(self._psearch_tk_widgets, sf, ("BG", "bg"))

        lbl_sel = tk.Label(sf, text="選択中:", font=("Yu Gothic UI",8), bg=t["BG"], fg=t["FG"])
        lbl_sel.pack(anchor="w", padx=8, pady=(8,0))
        self._tw(self._psearch_tk_widgets, lbl_sel, ("BG", "bg"), ("FG", "fg"))

        self._psearch_side_name = tk.Label(sf, text="—", wraplength=195,
                                            font=("Yu Gothic UI",9,"bold"),
                                            bg=t["BG"], fg=t["FG"], justify="left")
        self._psearch_side_name.pack(anchor="w", padx=8, pady=(0,6))
        self._tw(self._psearch_tk_widgets, self._psearch_side_name, ("BG", "bg"), ("FG", "fg"))

        sep = tk.Frame(sf, height=1, bg=t["BG3"])
        sep.pack(fill="x", padx=8, pady=4)
        self._tw(self._psearch_tk_widgets, sep, ("BG3", "bg"))

        lbl_ver = tk.Label(sf, text="バージョン:", font=("Yu Gothic UI",10), bg=t["BG"], fg=t["FG"])
        lbl_ver.pack(anchor="w", padx=8, pady=(0,2))
        self._tw(self._psearch_tk_widgets, lbl_ver, ("BG", "bg"), ("FG", "fg"))

        self._psearch_ver_var   = tk.StringVar(value="最新")
        self._psearch_ver_combo = ttk.Combobox(sf, textvariable=self._psearch_ver_var,
                                                state="readonly", width=24)
        self._psearch_ver_combo.pack(padx=8, pady=(0,2), fill="x")
        self._psearch_ver_combo.bind("<<ComboboxSelected>>", self._psearch_on_ver_select)

        self._psearch_ver_side_status = tk.Label(sf, text="", fg=t["FG"], bg=t["BG"],
                                                  font=("Yu Gothic UI",8))
        self._psearch_ver_side_status.pack(anchor="w", padx=8, pady=(0,4))
        self._tw(self._psearch_tk_widgets, self._psearch_ver_side_status, ("BG", "bg"))

        ttk.Button(sf, text="🔄 バージョン取得",
                   command=self._psearch_fetch_versions).pack(padx=8, pady=(0,8), fill="x")

    # ── ログタブ ──────────────────────────────────────────────────
    def _psearch_build_log(self, p):
        self._psearch_log_box = self._make_log_box(p)

    # ── ヘルパー ──────────────────────────────────────────────────
    def _psearch_log(self, msg, tag=""):
        def _do():
            at_bottom = self._psearch_log_box.yview()[1] >= 0.999
            self._psearch_log_box.insert("end", msg+"\n", tag)
            if at_bottom: self._psearch_log_box.see("end")
        self.after(0, _do)

    def _psearch_set_status(self, msg):
        app = self._parent_app
        if app and hasattr(app, "_prog_label"):
            self.after(0, lambda: app._prog_label.config(text=msg))

    def _psearch_set_progress(self, v, maximum=None):
        app = self._parent_app
        if app and hasattr(app, "_progress"):
            def _do():
                if maximum is not None: app._progress.configure(maximum=maximum)
                app._progress.configure(value=v)
            self.after(0, _do)

    def _psearch_do_cancel(self):
        self._psearch_cancel_flag = True
        self._psearch_set_status("中止中...")
        app = self._parent_app
        if app and hasattr(app, "_cancel_btn"):
            self.after(0, lambda: app._cancel_btn.config(state="disabled"))

    def _psearch_browse(self):
        d = filedialog.askdirectory()
        if d: self._psearch_dl_dir.set(d)

    def _psearch_parse_names(self, text):
        import re as _re
        return [p.strip() for p in _re.split(r"[,\n]", text) if p.strip()]

    def _psearch_load_txt(self):
        path = filedialog.askopenfilename(
            title="テキスト/CSVファイルを選択",
            filetypes=[("テキスト/CSV","*.txt *.csv"),("すべて","*.*")])
        if not path: return
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                raw = f.read()
            names = self._psearch_parse_names(raw)
            if not names: messagebox.showinfo("情報","プラグイン名が見つかりませんでした"); return
            existing = self._psearch_input.get("1.0","end").strip()
            sep = ", " if existing else ""
            self._psearch_input.insert("end", sep + ", ".join(names))
            self._psearch_log(f"📄 {os.path.basename(path)} から {len(names)} 件読み込み","info")
        except Exception as e:
            messagebox.showerror("読込エラー", str(e))

    def _psearch_load_json(self):
        path = filedialog.askopenfilename(
            title="JSONファイルを選択",
            filetypes=[("JSON","*.json"),("すべて","*.*")])
        if not path: return
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                data = json.load(f)
            names = []
            if isinstance(data, list):
                names = [str(x).strip() for x in data if isinstance(x,str) and x.strip()]
            elif isinstance(data, dict):
                for key in ("plugins","plugin_list","mods","modlist"):
                    if key in data and isinstance(data[key], list):
                        names = [str(x).strip() for x in data[key] if isinstance(x,str) and str(x).strip()]
                        break
                else:
                    names = [str(k).strip() for k in data.keys() if str(k).strip()]
            if not names: messagebox.showinfo("情報","プラグイン名が見つかりませんでした"); return
            existing = self._psearch_input.get("1.0","end").strip()
            sep = ", " if existing else ""
            self._psearch_input.insert("end", sep + ", ".join(names))
            self._psearch_log(f"📄 {os.path.basename(path)} から {len(names)} 件読み込み","info")
        except Exception as e:
            messagebox.showerror("読込エラー", str(e))

    def _psearch_add_to_list(self):
        raw = self._psearch_input.get("1.0","end").strip()
        if not raw: messagebox.showinfo("情報","プラグイン名を入力してください"); return
        names = self._psearch_parse_names(raw)
        if not names: messagebox.showinfo("情報","プラグイン名が見つかりませんでした"); return
        # 既存リストをクリアしてから追加
        for iid in self._psearch_tree.get_children():
            self._psearch_tree.delete(iid)
        self._psearch_items.clear()
        self._psearch_ver_cache.clear()
        self._psearch_cur_iid = None
        self._psearch_side_name.config(text="—")
        self._psearch_ver_var.set("最新")
        self._psearch_ver_combo["values"] = ["最新"]
        self._psearch_ver_side_status.config(text="")
        added = 0
        for n in names:
            iid = f"psrc_{added}_{n}"
            self._psearch_items.append({"iid":iid,"name":n,"status":"待機中","ver_override":None})
            self._psearch_tree.insert("","end", iid=iid, values=("☑",n,"待機中"))
            added += 1
        self._psearch_upd_label()
        if added:
            self._psearch_log(f"✅ {added} 件をリストに追加しました","ok")
            app = self._parent_app
            if app and hasattr(app, "_show_toast"):
                app._show_toast(f"プラグイン検索: {added} 件を一覧に追加しました")
            if app and hasattr(app, "auto_switch_tab"):
                if app.auto_switch_tab.get(): self._psearch_nb.select(1)
            else:
                self._psearch_nb.select(1)
        else:
            self._psearch_log("⚠ 追加するプラグイン名がありませんでした","warn")

    def _psearch_remove_selected(self):
        to_rm = [iid for iid in self._psearch_tree.get_children()
                 if self._psearch_tree.set(iid,"chk") == "☑"]
        for iid in to_rm:
            self._psearch_tree.delete(iid)
            self._psearch_items = [it for it in self._psearch_items if it["iid"]!=iid]
            self._psearch_ver_cache.pop(iid, None)
        if self._psearch_cur_iid in to_rm:
            self._psearch_cur_iid = None
            self._psearch_side_name.config(text="—")
            self._psearch_ver_var.set("最新")
            self._psearch_ver_combo["values"] = ["最新"]
            self._psearch_ver_side_status.config(text="")
        self._psearch_upd_label()

    def _psearch_sel_all(self, v):
        mark = "☑" if v else "☐"
        for row in self._psearch_tree.get_children():
            self._psearch_tree.set(row,"chk",mark)
        self._psearch_upd_label()

    def _psearch_on_click(self, e):
        row = self._psearch_tree.identify_row(e.y)
        if row and self._psearch_tree.identify_column(e.x) == "#1":
            cur = self._psearch_tree.set(row,"chk")
            self._psearch_tree.set(row,"chk","☑" if cur=="☐" else "☐")
            self._psearch_upd_label()
        if row:
            self._psearch_tree.selection_set(row)
            self._psearch_on_select(e)

    def _psearch_on_select(self, e=None):
        rows = self._psearch_tree.selection()
        if not rows: return
        row = rows[0]
        if row == self._psearch_cur_iid: return
        self._psearch_cur_iid = row
        item = next((it for it in self._psearch_items if it["iid"]==row), None)
        if not item: return
        self._psearch_side_name.config(text=item["name"])
        cached = self._psearch_ver_cache.get(row,[])
        self._psearch_ver_combo["values"] = ["最新"] + [v["label"] for v in cached]
        override = item.get("ver_override")
        if override:
            matched = next((v["label"] for v in cached if v["id"]==override), None)
            self._psearch_ver_var.set(matched or "最新")
        else:
            self._psearch_ver_var.set("最新")
        if cached:
            self._psearch_ver_side_status.config(text=f"✅ {len(cached)} 件取得済み",
                                                  fg=self._t()["GRN"])
        else:
            self._psearch_ver_side_status.config(text="← 取得ボタンでバージョン一覧を取得",
                                                  fg=self._t()["FG"])

    def _psearch_upd_label(self):
        rows = self._psearch_tree.get_children()
        sel  = sum(1 for r in rows if self._psearch_tree.set(r,"chk")=="☑")
        self._psearch_sel_label.config(text=f"{sel} / {len(rows)} 件選択")

    def _psearch_set_item_status(self, iid, status):
        def _do():
            if not self._psearch_tree.exists(iid): return
            item = next((it for it in self._psearch_items if it["iid"]==iid), None)
            if item: item["status"] = status
            self._psearch_tree.item(iid, values=(
                self._psearch_tree.set(iid,"chk"),
                self._psearch_tree.set(iid,"name"),
                status))
        self.after(0, _do)

    def _psearch_fetch_versions(self):
        if not self._psearch_cur_iid: return
        item = next((it for it in self._psearch_items if it["iid"]==self._psearch_cur_iid), None)
        if not item: return
        iid = self._psearch_cur_iid
        self._psearch_ver_side_status.config(text="🔄 取得中...", fg=self._t()["YEL"])
        self._psearch_ver_combo.config(state="disabled")
        loader_name = self._psearch_loader_var.get()
        loaders     = PLUGIN_LOADER_MAP.get(loader_name)
        def _fetch():
            results = []
            try:
                pid = mr_search_plugin(item.get("name",""))
                if pid:
                    vs = mr_get_plugin_versions(pid, loaders)
                    results = [{"label":v.get("version_number","?"),"id":v["id"]} for v in vs]
            except Exception: pass
            self.after(0, lambda r=results: self._psearch_ver_cb_done(iid, r))
        threading.Thread(target=_fetch, daemon=True).start()

    def _psearch_ver_cb_done(self, iid, results):
        t = self._t()
        self._psearch_ver_cache[iid] = results
        self._psearch_ver_combo["values"] = ["最新"] + [v["label"] for v in results]
        self._psearch_ver_combo.config(state="readonly")
        item = next((it for it in self._psearch_items if it["iid"]==iid), None)
        override = item.get("ver_override") if item else None
        if override:
            matched = next((v["label"] for v in results if v["id"]==override), None)
            self._psearch_ver_var.set(matched or "最新")
        else:
            self._psearch_ver_var.set("最新")
        if results:
            self._psearch_ver_side_status.config(text=f"✅ {len(results)} 件取得", fg=t["GRN"])
        else:
            self._psearch_ver_side_status.config(text="⚠ バージョンなし", fg=t["RED"])

    def _psearch_on_ver_select(self, e=None):
        if not self._psearch_cur_iid: return
        label = self._psearch_ver_var.get()
        item  = next((it for it in self._psearch_items if it["iid"]==self._psearch_cur_iid), None)
        if not item: return
        t = self._t()
        if label == "最新":
            item["ver_override"] = None
            self._psearch_ver_side_status.config(text="✅ 最新でDL", fg=t["GRN"])
        else:
            cached = self._psearch_ver_cache.get(self._psearch_cur_iid,[])
            ver = next((v for v in cached if v["label"]==label), None)
            item["ver_override"] = ver["id"] if ver else None
            self._psearch_ver_side_status.config(text=f"✅ {label} を選択", fg=t["GRN"])

    def _psearch_start_download(self):
        selected = [it for it in self._psearch_items
                    if self._psearch_tree.exists(it["iid"])
                    and self._psearch_tree.set(it["iid"],"chk") == "☑"]
        if not selected:
            messagebox.showinfo("情報","ダウンロードするプラグインを選択してください"); return
        out_dir = self._psearch_dl_dir.get().strip()
        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showerror("エラー","有効な保存先フォルダを指定してください"); return
        if self._psearch_running:
            messagebox.showwarning("実行中","現在ダウンロード中です"); return
        self._psearch_running     = True
        self._psearch_cancel_flag = False
        self._psearch_set_progress(0, len(selected))
        app = self._parent_app
        if app and hasattr(app, "_cancel_btn"): self.after(0, lambda: app._cancel_btn.config(state="normal"))
        self._psearch_nb.select(2)
        loader_name = self._psearch_loader_var.get()
        loaders     = PLUGIN_LOADER_MAP.get(loader_name)
        threading.Thread(
            target=self._psearch_worker,
            args=(selected, out_dir, loaders, loader_name),
            daemon=True).start()

    def _psearch_worker(self, items, out_dir, loaders, loader_name):
        auto_deps = self._psearch_auto_deps.get()
        done_deps = set()
        ok_list   = []
        fail_list = []
        for i, item in enumerate(items):
            if self._psearch_cancel_flag:
                self._psearch_log("\n⏹ 中止されました","warn"); break
            name       = item["name"]
            ver_id     = item.get("ver_override")
            self._psearch_set_item_status(item["iid"],"🔄 検索中...")
            self._psearch_set_status(f"{i+1}/{len(items)}: {name[:24]}")
            self._psearch_log(f"\n── {name} ──","info")
            def _log(msg, tag=""): self._psearch_log(msg, tag)
            dl_url, dl_fname, pid = find_plugin(name, _log, ver_id, loaders)
            if dl_url and dl_fname:
                dest = os.path.join(out_dir, dl_fname)
                try:
                    self._psearch_log(f"  ⬇ DL中 [{loader_name}]: {dl_fname}","")
                    download_file(dl_url, dest,
                                  lambda prog, n=name: self._psearch_set_status(
                                      f"DL: {n[:18]} {prog*100:.0f}%"))
                    self._psearch_log("  ✅ 完了","ok")
                    self._psearch_set_item_status(item["iid"],"✅ 完了")
                    ok_list.append(name)
                    if auto_deps:
                        for dep_name in []:  # find_plugin はdep情報を返さないため空
                            if not dep_name or dep_name in done_deps: continue
                            done_deps.add(dep_name)
                            du, df, _ = find_plugin(dep_name, _log, loaders=loaders)
                            if du and df and not os.path.exists(os.path.join(out_dir,df)):
                                download_file(du, os.path.join(out_dir,df))
                                self._psearch_log(f"  🔗 前提DL: {df}","ok")
                                ok_list.append(f"[前提] {dep_name}")
                except Exception as e:
                    self._psearch_log(f"  ❌ DL失敗: {e}","err")
                    if os.path.exists(dest):
                        try: os.remove(dest)
                        except Exception: pass
                    self._psearch_set_item_status(item["iid"],"❌ 失敗")
                    fail_list.append(name)
            else:
                self._psearch_set_item_status(item["iid"],"❌ 見つからず")
                fail_list.append(name)
            self._psearch_set_progress(i+1)

        self._psearch_log(f"\n{'═'*40}","info")
        self._psearch_log(f"✅ 成功: {len(ok_list)} 件","ok")
        for n in ok_list: self._psearch_log(f"   ✓ {n}","ok")
        if fail_list:
            self._psearch_log(f"❌ 失敗: {len(fail_list)} 件","err")
            for n in fail_list: self._psearch_log(f"   ✗ {n}","err")
        else:
            self._psearch_log("🎉 全て完了！","ok")
        self._psearch_set_status("完了" if not self._psearch_cancel_flag else "中止")
        self._psearch_running = False
        app2 = self._parent_app
        if app2 and hasattr(app2, "_cancel_btn"): self.after(0, lambda: app2._cancel_btn.config(state="disabled"))
        msg = f"✅ 成功: {len(ok_list)} 件\n❌ 失敗: {len(fail_list)} 件"
        if fail_list:
            msg += "\n\n失敗:\n" + "\n".join(f"  • {n}" for n in fail_list)
        self.after(0, lambda: messagebox.showinfo("完了", msg))

    def _build_inspect(self, p):
        """検査タブ: JAR を読み込み各プラグインの対応loaderをModrinthで確認する"""
        t = THEMES[self._theme]

        # ── フォルダ指定行 ──
        top = ttk.Frame(p)
        top.pack(fill="x", padx=10, pady=(8, 4))
        self._inspect_dir = tk.StringVar()
        ttk.Entry(top, textvariable=self._inspect_dir).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(top, text="参照", command=lambda: self._inspect_browse()).pack(side="left", padx=(0, 6))
        ttk.Button(top, text="🔍 検査", command=self._start_inspect).pack(side="left")

        # 凡例
        legend = ttk.Frame(p)
        legend.pack(fill="x", padx=10, pady=(0, 4))
        for color_key, label in [("GRN", "✅ Plugin Loader（Spigot/Paper系）"),
                                   ("ACC", "🔷 プロキシ（Velocity/BungeeCord系）"),
                                   ("RED", "❌ 判定不明")]:
            lbl = tk.Label(legend, text=label, fg=t[color_key], bg=t["BG"],
                           font=("Yu Gothic UI", 8))
            lbl.pack(side="left", padx=(0, 12))
            self._tw(self._tk_widgets, lbl, (color_key, "fg"), ("BG", "bg"))
        legend_bg = legend
        self._tw(self._tk_widgets, legend_bg, ("BG", "bg"))

        # ── Treeview ──
        cols = ("name", "loaders", "judge")
        self._ins_tree = ttk.Treeview(p, columns=cols, show="headings", selectmode="none")
        for cid, lbl, w, stretch in [
            ("name",    "プラグイン名",   200, True),
            ("loaders", "対応Loader",     280, True),
            ("judge",   "判定",            90, False),
        ]:
            self._ins_tree.heading(cid, text=lbl)
            self._ins_tree.column(cid, width=w, minwidth=60, anchor="w", stretch=stretch)

        # 判定ごとのタグ色（後でテーマ更新時も _refresh_inspect_tags で再設定）
        self._refresh_inspect_tags()

        vsb = ttk.Scrollbar(p, orient="vertical", command=self._ins_tree.yview)
        self._ins_tree.configure(yscrollcommand=vsb.set)
        self._ins_tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 8))
        vsb.pack(side="left", fill="y", pady=(0, 8), padx=(0, 10))

        self._inspect_running = False

    def _inspect_browse(self):
        d = filedialog.askdirectory()
        if d:
            self._inspect_dir.set(d)

    def _refresh_inspect_tags(self):
        """検査Treeviewのタグ色を現在テーマで更新"""
        t = self._t()
        self._ins_tree.tag_configure("plugin",  foreground=t["GRN"])
        self._ins_tree.tag_configure("proxy",   foreground=t["ACC"])
        self._ins_tree.tag_configure("unknown", foreground=t["RED"])

    def _start_inspect(self):
        if self._inspect_running:
            return
        d = self._inspect_dir.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror("エラー", "有効なフォルダを指定してください")
            return
        jars = sorted(f for f in os.listdir(d) if f.lower().endswith(".jar"))
        if not jars:
            messagebox.showinfo("情報", "JARファイルが見つかりませんでした")
            return
        for row in self._ins_tree.get_children():
            self._ins_tree.delete(row)
        self._inspect_running = True
        threading.Thread(target=self._inspect_worker, args=(d, jars), daemon=True).start()

    # Plugin Loader 系とプロキシ系の識別セット
    _PROXY_LOADERS  = {"velocity", "bungeecord_waterfall"}
    _PLUGIN_LOADERS = {"bukkit_spigot_paper", "bukkit_spigot_paper+folia", "paper_folia", "sponge"}

    def _inspect_worker(self, folder, jars):
        for fname in jars:
            info   = read_jar_meta(os.path.join(folder, fname))
            name   = info.get("name", fname)
            loader = info.get("loader", "unknown")

            # 表示文字列
            label_map = {
                "velocity":               "Velocity",
                "bungeecord_waterfall":   "BungeeCord / Waterfall",
                "paper_folia":            "Paper / Folia",
                "bukkit_spigot_paper":    "Bukkit / Spigot / Paper / Purpur",
                "bukkit_spigot_paper+folia": "Bukkit / Spigot / Paper / Purpur / Folia",
                "sponge":                 "Sponge",
            }
            loader_str = label_map.get(loader, "—")

            if loader in self._PROXY_LOADERS:
                tag = "proxy"
            elif loader in self._PLUGIN_LOADERS:
                tag = "plugin"
            else:
                tag = "unknown"

            self.after(0, lambda n=name, f=fname, ls=loader_str, tg=tag:
                       self._ins_insert(n, f, ls, tg))

        self._inspect_running = False

    def _ins_insert(self, name, iid, loaders_str, tag):
        judge_map = {
            "plugin":  "✅ Plugin Loader",
            "proxy":   "🔷 プロキシ",
            "unknown": "❌ 不明",
        }
        # iid が重複しないよう fname にサフィックスを付ける
        safe_iid = iid + "_ins"
        if self._ins_tree.exists(safe_iid):
            safe_iid = iid + f"_ins_{id(name)}"
        self._ins_tree.insert("", "end", iid=safe_iid,
                              values=(name, loaders_str, judge_map.get(tag, tag)),
                              tags=(tag,))

    def _build_log(self, p):
        self._log_box = self._make_log_box(p)
        self._tw(self._tk_widgets, self._log_box.frame, ("LOG", "bg"))
        self._refresh_log_tags()

    # ── テーマ取得ヘルパー ────────────────────────────────────────────────────

    def _make_log_box(self, parent):
        """ScrolledText ログボックスを生成して parent にパックし返す"""
        t = self._t()
        box = scrolledtext.ScrolledText(
            parent, bg=t["LOG"], fg=t["FG"],
            selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
            insertbackground=t["FG"],
            font=("Consolas",9), relief="flat", wrap="word")
        box.frame.configure(background=t["LOG"])
        box.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, key in [("ok","GRN"),("err","RED"),("info","ACC"),("warn","YEL")]:
            box.tag_config(tag, foreground=t[key])
        ttk.Button(parent, text="クリア",
                   command=lambda b=box: b.delete("1.0","end")).pack(pady=(0,8))
        return box

    def _t(self):
        """現在のテーマ辞書を返す"""
        return THEMES[self._theme]

    def _tw(self, wlist, widget, *pairs):
        """(color_key, attr) のペアを wlist に一括登録するヘルパー"""
        for color_key, attr in pairs:
            wlist.append((widget, color_key, attr))

    def _refresh_log_tags(self):
        """ログボックスのタグ色を現在のテーマで更新"""
        t = self._t()
        for tag, key in [("ok", "GRN"), ("err", "RED"), ("info", "ACC"), ("warn", "YEL")]:
            self._log_box.tag_config(tag, foreground=t[key])

    # ── テーマ適用 ─────────────────────────────────────────────────────────────

    def apply_theme(self, theme):
        """外部から呼ばれるテーマ切り替えエントリポイント"""
        self._theme = theme
        t = self._t()

        # 1) tk.Label / tk.Canvas など ttk 管轄外の登録済みウィジェットを一括更新
        for widget, color_key, attr in self._tk_widgets:
            try:
                widget.config(**{attr: t[color_key]})
            except Exception:  # 破棄済みウィジェットへのアクセスは無視
                pass

        # 2) ログボックス本体 と ScrolledText.frame（外側tk.Frame）
        self._log_box.config(
            bg=t["LOG"], fg=t["FG"],
            selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
            insertbackground=t["FG"],
        )
        # frame は _tk_widgets に登録済みなので上の一括更新で処理済み
        self._refresh_log_tags()

        # 3) Treeview の色は ttk.Style 側（_apply_style）で制御されるため
        #    ここでは何もしない（configure で background 等を渡すと TclError になる）

        # 4) バージョン状態ラベルの色を現在の状態に合わせてリセット
        #    （選択中のアイテムがあれば再描画、なければニュートラル表示）
        self._refresh_ver_status_color()

        # 5) 検査タブのTreeviewタグ色を更新
        self._refresh_inspect_tags()

        # 6) プラグイン検索タブの tk.Label 等を更新
        if hasattr(self, "_psearch_tk_widgets"):
            for widget, color_key, attr in self._psearch_tk_widgets:
                try:
                    widget.config(**{attr: t[color_key]})
                except Exception:
                    pass
        if hasattr(self, "_psearch_log_box"):
            self._psearch_log_box.config(
                bg=t["LOG"], fg=t["FG"],
                selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
                insertbackground=t["FG"])
            self._psearch_log_box.frame.configure(background=t["LOG"])
            for tag, key in [("ok","GRN"),("err","RED"),("info","ACC"),("warn","YEL")]:
                self._psearch_log_box.tag_config(tag, foreground=t[key])
        if hasattr(self, "_psearch_input"):
            self._psearch_input.config(
                bg=t["LOG"], fg=t["FG"],
                selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
                insertbackground=t["FG"])
            self._psearch_input.frame.configure(background=t["LOG"])
        if hasattr(self, "_psearch_ver_side_status"):
            txt = self._psearch_ver_side_status.cget("text")
            if txt.startswith("✅"):   self._psearch_ver_side_status.config(fg=t["GRN"])
            elif txt.startswith("⚠"): self._psearch_ver_side_status.config(fg=t["RED"])
            elif txt.startswith("🔄"): self._psearch_ver_side_status.config(fg=t["YEL"])
            else:                       self._psearch_ver_side_status.config(fg=t["FG"])

    def _refresh_ver_status_color(self):
        """バージョン状態ラベルの fg を現在テーマで正しく設定しなおす"""
        t = self._t()
        text = self._ver_status_side.cget("text")
        if text.startswith("✅"):
            self._ver_status_side.config(fg=t["GRN"])
        elif text.startswith("⚠"):
            self._ver_status_side.config(fg=t["RED"])
        elif text.startswith("🔄"):
            self._ver_status_side.config(fg=t["YEL"])
        else:
            self._ver_status_side.config(fg=t["FG"])

    # ── ヘルパー ──────────────────────────────────────────────────────────────

    def _log(self, msg, tag=""):
        def _do():
            # ユーザーが一番下付近にいる時だけ自動スクロール
            at_bottom = self._log_box.yview()[1] >= 0.999
            self._log_box.insert("end", msg + "\n", tag)
            if at_bottom:
                self._log_box.see("end")
        self.after(0, _do)

    def _set_status(self, msg):
        app = self._parent_app
        if app and hasattr(app, "_prog_label"):
            self.after(0, lambda: app._prog_label.config(text=msg))

    def _set_progress(self, v, maximum=None):
        app = self._parent_app
        if app and hasattr(app, "_progress"):
            def _do():
                if maximum is not None:
                    app._progress.configure(maximum=maximum)
                app._progress.configure(value=v)
            self.after(0, _do)

    def _cancel(self):
        self._cancel_flag = True
        self._set_status("中止中...")
        app = self._parent_app
        if app and hasattr(app, "_cancel_btn"):
            self.after(0, lambda: app._cancel_btn.config(state="disabled"))

    def _browse(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    def _disable_combobox_wheel(self):
        def _block(e): return "break"
        def _bind(w):
            if isinstance(w, ttk.Combobox):
                for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    w.bind(ev, _block)
            for c in w.winfo_children():
                _bind(c)
        _bind(self)

    # ── プラグイン一覧操作 ────────────────────────────────────────────────────

    def _on_click(self, e):
        row = self._tree.identify_row(e.y)
        if row and self._tree.identify_column(e.x) == "#1":
            cur = self._tree.set(row, "chk")
            self._tree.set(row, "chk", "☑" if cur == "☐" else "☐")
            self._upd_label()
        if row:
            self._tree.selection_set(row)
            self._on_select(e)

    def _on_select(self, e=None):
        rows = self._tree.selection()
        if not rows:
            return
        row = rows[0]
        if row == self._current_iid:
            return
        self._current_iid = row
        item = next((it for it in self.plugin_list if it["filename"] == row), None)
        if not item:
            return
        self._side_name.config(text=item.get("name", row))
        self._versions_cache = []

        override = self._ver_overrides.get(row)
        if override:
            cached_label = override.get("label", "最新")
            vals = ["最新"] if cached_label == "最新" else ["最新", cached_label]
            self._ver_combo["values"] = vals
            self._ver_var.set(cached_label)
            self._ver_status_side.config(
                text=f"✅ {cached_label} を選択中",
                fg=self._t()["GRN"],
            )
        else:
            self._ver_combo["values"] = ["最新"]
            self._ver_var.set("最新")
            self._ver_status_side.config(
                text="← バージョン取得ボタンで一覧を取得",
                fg=self._t()["FG"],
            )

    def _fetch_versions_side(self):
        if not self._current_iid:
            return
        item = next((it for it in self.plugin_list if it["filename"] == self._current_iid), None)
        if not item:
            return
        self._ver_status_side.config(text="🔄 取得中...", fg=self._t()["YEL"])
        self._ver_combo.config(state="disabled")

        def _fetch():
            results = []
            try:
                pid = mr_search_plugin(item.get("name", ""))
                if pid:
                    loader_name = self.plugin_loader.get()
                    loaders = PLUGIN_LOADER_MAP.get(loader_name)
                    vs = mr_get_plugin_versions(pid, loaders)
                    results = [{"label": v.get("version_number", "?"), "id": v["id"]} for v in vs]
            except Exception:  # バージョン取得失敗時は空リストのままコールバックを呼ぶ
                pass
            self.after(0, lambda r=results: self._update_ver_combo(r))

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_ver_combo(self, results):
        self._versions_cache = results
        labels = ["最新"] + [r["label"] for r in results]
        self._ver_combo["values"] = labels
        self._ver_combo.config(state="readonly")

        override = self._ver_overrides.get(self._current_iid)
        self._ver_var.set(override.get("label", "最新") if override else "最新")

        if results:
            self._ver_status_side.config(text=f"✅ {len(results)} 件取得", fg=self._t()["GRN"])
        else:
            self._ver_status_side.config(text="⚠ バージョンなし", fg=self._t()["RED"])

    def _on_ver_select(self, e=None):
        if not self._current_iid:
            return
        label = self._ver_var.get()
        if label == "最新":
            self._ver_overrides.pop(self._current_iid, None)
            self._ver_status_side.config(text="✅ 最新でDL", fg=self._t()["GRN"])
        else:
            ver = next((v for v in self._versions_cache if v["label"] == label), None)
            if ver:
                self._ver_overrides[self._current_iid] = {"id": ver["id"], "label": label}
            self._ver_status_side.config(text=f"✅ {label} を選択", fg=self._t()["GRN"])

    def _sel_all(self, v):
        mark = "☑" if v else "☐"
        for row in self._tree.get_children():
            self._tree.set(row, "chk", mark)
        self._upd_label()

    def _upd_label(self):
        rows = self._tree.get_children()
        sel  = sum(1 for r in rows if self._tree.set(r, "chk") == "☑")
        self._sel_label.config(text=f"{sel} / {len(rows)} 件選択")

    # ── 読み込み ──────────────────────────────────────────────────────────────

    def _load_plugins(self):
        d = self.plugins_dir.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror("エラー", "有効なpluginsフォルダを指定してください")
            return
        jars = sorted(f for f in os.listdir(d) if f.lower().endswith(".jar"))
        if not jars:
            messagebox.showinfo("情報", "JARファイルが見つかりませんでした")
            return

        for row in self._tree.get_children():
            self._tree.delete(row)
        self.plugin_list    = []
        self._ver_overrides = {}
        self._current_iid   = None
        self._side_name.config(text="—")
        self._ver_combo["values"] = ["最新"]
        self._ver_var.set("最新")
        self._ver_status_side.config(text="", fg=self._t()["FG"])

        self._log(f"📂 {len(jars)} 個のJARを解析中...", "info")
        for fname in jars:
            info = read_jar_meta(os.path.join(d, fname))
            self.plugin_list.append(info)
        self.plugin_list.sort(key=lambda x: x.get("name", "").lower())

        for it in self.plugin_list:
            self._tree.insert(
                "", "end", iid=it["filename"],
                values=("☑", it.get("name", it["filename"]), it.get("version", "?")),
            )
        self._upd_label()
        self._log(f"✅ {len(jars)} 件読み込み完了", "ok")

        app = self._parent_app
        if app and hasattr(app, "auto_switch_tab"):
            if app.auto_switch_tab.get():
                self._nb.select(1)
        else:
            self._nb.select(1)
        if app and hasattr(app, "_show_toast"):
            app._show_toast("プラグインを読み込みました。")

    # ── アップデート ──────────────────────────────────────────────────────────

    def _start_update(self):
        selected = [
            it for it in self.plugin_list
            if self._tree.exists(it["filename"]) and self._tree.set(it["filename"], "chk") == "☑"
        ]
        if not selected:
            messagebox.showinfo("情報", "プラグインが選択されていません")
            return
        if self._running:
            messagebox.showwarning("実行中", "現在アップデート中です")
            return
        self._running     = True
        self._cancel_flag = False
        self._set_progress(0, len(selected))
        self._nb.select(2)
        app = self._parent_app
        if app and hasattr(app, "_cancel_btn"):
            self.after(0, lambda: app._cancel_btn.config(state="normal"))
        threading.Thread(target=self._worker, args=(selected,), daemon=True).start()

    def _worker(self, plugins):
        delete_old  = self.delete_old.get()
        delete_fail = self.delete_failed.get()
        auto_deps   = self.auto_deps.get()
        out_dir     = self.plugins_dir.get()
        loader_name = self.plugin_loader.get()
        loaders     = PLUGIN_LOADER_MAP.get(loader_name)
        done_deps   = set()
        ok_list     = []
        fail_list   = []

        # バックアップモード
        import datetime
        app         = self._parent_app
        backup_on   = app.backup_mode.get() if (app and hasattr(app, "backup_mode")) else False
        backup_base = app.backup_dir.get().strip() if (app and hasattr(app, "backup_dir")) else ""
        _backup_ts  = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        _backup_dir = None  # 初回DL時に作成

        if backup_on:
            if not backup_base or not os.path.isdir(backup_base):
                self.after(0, lambda: messagebox.showerror(
                    "バックアップモードエラー",
                    "バックアップ出力先フォルダが設定されていないか存在しません。\n"
                    "全体設定タブで有効なフォルダを指定してください。"))
                self._running = False
                return
            _backup_dir = os.path.join(backup_base, f"plugin_{_backup_ts}")
            os.makedirs(_backup_dir, exist_ok=True)
            self._log(f"💾 バックアップモード ON → plugin_{_backup_ts}", "info")

        def _resolve_out(filename):
            """バックアップONのときはバックアップフォルダ、OFFは通常フォルダ"""
            return _backup_dir if backup_on else out_dir

        for i, plugin in enumerate(plugins):
            if self._cancel_flag:
                self._log("\n⏹ 中止されました", "warn")
                break
            name     = plugin.get("name", plugin["filename"])
            override = self._ver_overrides.get(plugin["filename"])
            ver_id   = override["id"] if override else None
            self._set_status(f"{i + 1}/{len(plugins)}: {name[:24]}")
            self._log(f"\n── {name} ──", "info")

            def _log(msg, tag=""): self._log(msg, tag)

            dl_url, dl_fname, pid = find_plugin(name, _log, ver_id, loaders)

            if dl_url and dl_fname:
                actual_dir  = _resolve_out(plugin["filename"])
                dest        = os.path.join(actual_dir, dl_fname)
                do_del_old  = delete_old  and not backup_on
                do_del_fail = delete_fail and not backup_on
                old_path    = None if backup_on else plugin.get("path")
                if self._do_download(dl_url, dest, name, old_path, do_del_old, do_del_fail, loader_name):
                    ok_list.append(name)
                    if auto_deps:
                        for dep_name in plugin.get("depend", []):
                            if not dep_name or dep_name in done_deps:
                                continue
                            done_deps.add(dep_name)
                            if any(p.get("name", "").lower() == dep_name.lower() for p in self.plugin_list):
                                self._log(f"  🔗 前提プラグイン既存: {dep_name}", "ok")
                                continue
                            self._log(f"  🔗 前提プラグイン DL: {dep_name}", "info")
                            du, df, _ = find_plugin(dep_name, _log, loaders=loaders)
                            if du and df and not os.path.exists(os.path.join(actual_dir, df)):
                                self._do_download(du, os.path.join(actual_dir, df), dep_name, None, False, do_del_fail, loader_name)
                                ok_list.append(f"[前提] {dep_name}")
                else:
                    fail_list.append(name)
            else:
                fail_list.append(name)
                self._log("  ❌ スキップ", "err")
                if delete_fail and not backup_on and plugin.get("path") and os.path.exists(plugin["path"]):
                    try:
                        os.remove(plugin["path"])
                        self._log("  🗑 失敗ファイル削除", "warn")
                    except Exception:  # 削除失敗は処理継続に影響しないため無視
                        pass

            self._set_progress(i + 1)

        self._log(f"\n{'═' * 40}", "info")
        self._log(f"✅ 成功: {len(ok_list)} 件", "ok")
        for n in ok_list:
            self._log(f"   ✓ {n}", "ok")
        if fail_list:
            self._log(f"❌ 失敗: {len(fail_list)} 件", "err")
            for n in fail_list:
                self._log(f"   ✗ {n}", "err")
        else:
            self._log("🎉 全て完了！", "ok")

        self._set_status("完了" if not self._cancel_flag else "中止")
        self._running = False
        app = self._parent_app
        if app and hasattr(app, "_cancel_btn"):
            self.after(0, lambda: app._cancel_btn.config(state="disabled"))

        msg = f"✅ 成功: {len(ok_list)} 件\n❌ 失敗: {len(fail_list)} 件"
        if fail_list:
            msg += "\n\n失敗:\n" + "\n".join(f"  • {n}" for n in fail_list)
        self.after(0, lambda: messagebox.showinfo("完了", msg))

    def _do_download(self, url, dest, name, old_path, delete_old, delete_fail, loader_name="Modrinth"):
        try:
            self._log(f"  ⬇ DL中 [{loader_name}]: {os.path.basename(dest)}")
            download_file(url, dest, lambda p: self._set_status(f"DL: {name[:18]} {p * 100:.0f}%"))
            if delete_old and old_path and os.path.exists(old_path):
                if os.path.abspath(dest) != os.path.abspath(old_path):
                    os.remove(old_path)
                    self._log(f"  🗑 旧ファイル削除: {os.path.basename(old_path)}", "warn")
            self._log("  ✅ 完了", "ok")
            return True
        except Exception as e:
            self._log(f"  ❌ DL失敗: {e}", "err")
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except Exception:  # 一時ファイル削除失敗は無視
                    pass
            if delete_fail and old_path and os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    self._log("  🗑 失敗ファイル削除", "warn")
                except Exception:  # 削除失敗は処理継続に影響しないため無視
                    pass
            return False

    # ── 設定保存 ──────────────────────────────────────────────────────────────

    def save_config(self):
        cfg = load_config()
        cfg.update({
            "plugins_dir":          self.plugins_dir.get(),
            "plugin_delete_old":    self.delete_old.get(),
            "plugin_delete_failed": self.delete_failed.get(),
            "plugin_auto_deps":     self.auto_deps.get(),
            "plugin_loader":        self.plugin_loader.get(),
        })
        save_config(cfg)


# ══════════════════════════════════════════════════════════════════════════════
# StandaloneApp（plugin_updater.py 単体起動時）
# ══════════════════════════════════════════════════════════════════════════════

class StandaloneApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🔌 MC Plugin Updater")
        self.geometry("900x700")
        self.resizable(True, True)

        cfg          = load_config()
        self._theme  = cfg.get("theme", "light")

        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MCPluginUpdater.App.1.0")
        except Exception:  # Windows専用API。非Windows環境では失敗するが問題なし
            pass

        try:
            base            = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            ip              = os.path.join(base, "icon.ico")
            self._icon_path = ip if os.path.exists(ip) else None
            if self._icon_path:
                self.iconbitmap(default=self._icon_path)
        except Exception:  # アイコン設定失敗はUIに影響しないため無視
            self._icon_path = None

        self._apply_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_style(self):
        t = THEMES[self._theme]
        B, B2, B3, F, A = t["BG"], t["BG2"], t["BG3"], t["FG"], t["ACC"]
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",            background=B)
        s.configure("TLabel",            background=B, foreground=F, font=("Yu Gothic UI", 10))
        s.configure("Hdr.TLabel",        background=B, foreground=A, font=("Yu Gothic UI", 13, "bold"))
        s.configure("Sub.TLabel",        background=B, foreground=F, font=("Yu Gothic UI", 9))
        s.configure("TButton",           background=A, foreground=t["BTN_FG"],
                     font=("Yu Gothic UI", 10, "bold"), relief="flat", padding=(8, 5))
        s.map("TButton",                 background=[("active", t["BTN_ACT"]), ("disabled", t["BTN_DIS"])],
                                         foreground=[("disabled", "#6c7086")])
        s.configure("TEntry",            fieldbackground=B2, foreground=F, insertcolor=F, relief="flat", padding=4)
        s.configure("TCheckbutton",      background=B, foreground=F, font=("Yu Gothic UI", 10))
        s.map("TCheckbutton",            background=[("active", B)])
        s.configure("TCombobox",         fieldbackground=B2, foreground=F,
                     selectbackground=B2, selectforeground=F, padding=4)
        s.map("TCombobox",
              fieldbackground=[("readonly", B2), ("disabled", B3)],
              foreground=[("readonly", F), ("disabled", "#6c7086")],
              selectbackground=[("readonly", B2)],
              selectforeground=[("readonly", F)])
        s.configure("Treeview",          background=B2, foreground=F, fieldbackground=B2,
                     rowheight=26, font=("Yu Gothic UI", 9))
        s.configure("Treeview.Heading",  background=B, foreground=A,
                     font=("Yu Gothic UI", 9, "bold"), relief="flat")
        s.map("Treeview",                background=[("selected", t["TREE_SEL"])],
                                         foreground=[("selected", t["SEL_FG"])])
        s.map("Treeview.Heading",        background=[("active", B2), ("pressed", B2)],
                                         foreground=[("active", A), ("pressed", A)],
                                         relief=[("active", "flat"), ("pressed", "flat")])
        s.configure("TProgressbar",      troughcolor=B2, background=A, thickness=8)
        s.configure("TNotebook",         background=B, tabmargins=0)
        s.configure("TNotebook.Tab",     background=B2, foreground=F, padding=[14, 7], font=("Yu Gothic UI", 10))
        s.map("TNotebook.Tab",           background=[("selected", B)], foreground=[("selected", A)])
        s.configure("TLabelframe",       background=B, relief="solid", borderwidth=1, bordercolor=B3)
        s.configure("TLabelframe.Label", background=B, foreground=A, font=("Yu Gothic UI", 10, "bold"))
        s.configure("TSeparator",        background=B3)
        self.configure(bg=B)

    def _build_ui(self):
        t = THEMES[self._theme]
        hdr = ttk.Frame(self)
        hdr.pack(fill="x", padx=12, pady=(12, 0))
        hdr.columnconfigure(0, weight=1)
        hdr.columnconfigure(1, weight=1)
        hdr.columnconfigure(2, weight=1)
        ttk.Label(hdr, text="🔌  MC Plugin Updater", style="Hdr.TLabel").grid(row=0, column=1)
        self._theme_btn = ttk.Button(hdr, text=t["ICON"], command=self._toggle_theme, width=3)
        self._theme_btn.grid(row=0, column=2, sticky="e")
        ttk.Label(
            self,
            text="Spigot / Paper / Bukkit プラグインを一括アップデート（Modrinth使用）",
            style="Sub.TLabel",
        ).pack(pady=(2, 8))

        self._plugin_app = PluginUpdaterApp(self, theme=self._theme, icon_path=self._icon_path,
                                             parent_app=self)
        self._plugin_app.pack(fill="both", expand=True, padx=12, pady=(0, 0))
        self._plugin_app._disable_combobox_wheel()

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=(0, 6))
        self._progress   = ttk.Progressbar(bar, mode="determinate")
        self._progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._prog_label = ttk.Label(bar, text="", width=30)
        self._prog_label.pack(side="left")
        self._cancel_btn = ttk.Button(bar, text="⏹ 中止", command=self._plugin_app._cancel, state="disabled")
        self._cancel_btn.pack(side="left", padx=(6, 0))

    def _toggle_theme(self):
        self._theme = "dark" if self._theme == "light" else "light"
        # 1) ttk スタイルを先に更新（Treeview・Notebook・Button 等）
        self._apply_style()
        # 2) テーマボタンのアイコンを更新
        self._theme_btn.config(text=THEMES[self._theme]["ICON"])
        # 3) PluginUpdaterApp 内の tk.Label / Canvas 等を更新
        self._plugin_app.apply_theme(self._theme)

    def _on_close(self):
        self._plugin_app.save_config()
        cfg = load_config()
        cfg["theme"] = self._theme
        save_config(cfg)
        self.destroy()


if __name__ == "__main__":
    app = StandaloneApp()
    app.mainloop()
