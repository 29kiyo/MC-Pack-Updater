import os, re, sys, json, zipfile, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import urllib.request, urllib.parse

MODRINTH_API = "https://api.modrinth.com/v2"
CONFIG_FILE  = os.path.join(os.path.expanduser("~"), ".mc_plugin_updater_config.json")

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

def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
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
    info      = {"filename": fname, "path": jar_path, "name": base_name, "version": "", "depend": []}
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = zf.namelist()
            if "velocity-plugin.json" in names:
                d = json.loads(zf.read("velocity-plugin.json").decode("utf-8", errors="ignore"))
                info["name"]    = d.get("name") or d.get("id") or base_name
                info["version"] = d.get("version", "")
                info["depend"]  = list(d.get("dependencies", {}).keys())
                return info
            yml = next((n for n in ("plugin.yml", "paper-plugin.yml", "bungee.yml") if n in names), None)
            if yml:
                raw = zf.read(yml).decode("utf-8", errors="ignore")
                for line in raw.splitlines():
                    line = line.strip()
                    if line.startswith("name:"):
                        info["name"] = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("version:"):
                        info["version"] = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("depend:"):
                        ds = line.split(":", 1)[1].strip().strip("[]")
                        info["depend"] = [d.strip().strip('"\'') for d in ds.split(",") if d.strip()]
    except Exception:
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
    except Exception:
        return None

def mr_get_plugin_versions(pid):
    try:
        params = urllib.parse.urlencode({
            "loaders": json.dumps(["paper", "spigot", "bukkit", "purpur", "folia", "waterfall", "velocity"]),
        })
        return http_get(f"{MODRINTH_API}/project/{pid}/version?{params}")
    except Exception:
        return []

def mr_best_file(vo):
    du = df = None
    for fi in vo.get("files", []):
        if fi.get("primary") or not du:
            du, df = fi["url"], fi["filename"]
        if fi.get("primary"):
            break
    return du, df

def find_plugin(name, log_cb, ver_id=None):
    try:
        pid = mr_search_plugin(name)
        if not pid:
            log_cb("  Modrinth: 見つからず", "warn")
            return None, None, None
        if ver_id:
            vs = [http_get(f"{MODRINTH_API}/version/{ver_id}")]
        else:
            vs = mr_get_plugin_versions(pid)
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

        self.plugin_list    = []
        self._ver_overrides = {}   # filename -> {"id": ver_id, "label": str} or None
        self._current_iid   = None
        self._versions_cache = []

        self._build()

    # ── ビルド ────────────────────────────────────────────────────────────────

    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        t_set = ttk.Frame(nb); nb.add(t_set, text=" ⚙ 設定 ")
        t_lst = ttk.Frame(nb); nb.add(t_lst, text=" 🔌 プラグイン一覧 ")
        t_log = ttk.Frame(nb); nb.add(t_log, text=" 📋 ログ ")
        self._nb = nb

        self._build_settings(t_set)
        self._build_list(t_lst)
        self._build_log(t_log)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(0, 6))
        self._progress   = ttk.Progressbar(bar, mode="determinate")
        self._progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._prog_label = ttk.Label(bar, text="", width=30)
        self._prog_label.pack(side="left")
        self._cancel_btn = ttk.Button(bar, text="⏹ 中止", command=self._cancel, state="disabled")
        self._cancel_btn.pack(side="left", padx=(6, 0))

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
        dl_info.pack(anchor="w", padx=10, pady=8)
        self._dl_info_label = dl_info
        self._tk_widgets.append((dl_info, "YEL", "fg"))
        self._tk_widgets.append((dl_info, "BG",  "bg"))

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
            "このツールはModrinthを使用してプラグインをダウンロードします。\n"
            "プラグインのダウンロード・アップデートはできますが、"
            "お使いのMinecraftサーバーのバージョンやPlugin Loader（Spigot / Paper / Purpur / Velocity等）"
            "で正常に動作するとは限りません。\n"
            "アップデート前に必ずバックアップを取り、自己責任でご使用ください。"
        )
        warn = tk.Label(
            lf5, text=msg,
            wraplength=560, justify="left",
            fg=t["RED"], bg=t["BG"],
            font=("Yu Gothic UI", 9),
        )
        warn.pack(padx=10, pady=8, anchor="w")
        self._warn_label = warn
        self._tk_widgets.append((warn, "RED", "fg"))
        self._tk_widgets.append((warn, "BG",  "bg"))

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
        sc = tk.Canvas(self._side, highlightthickness=0, bg=t["BG"])
        sv = ttk.Scrollbar(self._side, orient="vertical", command=sc.yview)
        sc.configure(yscrollcommand=sv.set)
        sv.pack(side="right", fill="y")
        sc.pack(side="left", fill="both", expand=True)
        sf  = ttk.Frame(sc)
        sw  = sc.create_window((0, 0), window=sf, anchor="nw")
        sf.bind("<Configure>",  lambda e: sc.configure(scrollregion=sc.bbox("all")))
        sc.bind("<Configure>",  lambda e: sc.itemconfig(sw, width=e.width))
        sc.bind("<MouseWheel>", lambda e: sc.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self._side_canvas = sc
        self._tk_widgets.append((sc, "BG", "bg"))

        ttk.Label(sf, text="選択中:", font=("Yu Gothic UI", 8)).pack(anchor="w", padx=8, pady=(8, 0))
        self._side_name = ttk.Label(sf, text="—", wraplength=195, font=("Yu Gothic UI", 9, "bold"))
        self._side_name.pack(anchor="w", padx=8, pady=(0, 6))

        ttk.Separator(sf, orient="horizontal").pack(fill="x", padx=8, pady=4)

        ttk.Label(sf, text="バージョン:").pack(anchor="w", padx=8, pady=(0, 2))
        self._ver_var   = tk.StringVar(value="最新")
        self._ver_combo = ttk.Combobox(sf, textvariable=self._ver_var, state="readonly", width=24)
        self._ver_combo.pack(padx=8, pady=(0, 2), fill="x")
        self._ver_combo.bind("<<ComboboxSelected>>", self._on_ver_select)

        # バージョン状態ラベル（色は apply_theme で動的に設定）
        self._ver_status_side = ttk.Label(sf, text="", font=("Yu Gothic UI", 8))
        self._ver_status_side.pack(anchor="w", padx=8, pady=(0, 4))

        ttk.Button(sf, text="🔄 バージョン取得", command=self._fetch_versions_side).pack(padx=8, pady=(0, 8), fill="x")

    def _build_log(self, p):
        t = self._t()
        self._log_box = scrolledtext.ScrolledText(
            p,
            bg=t["LOG"], fg=t["FG"],
            selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
            insertbackground=t["FG"],
            font=("Consolas", 9), relief="flat", wrap="word",
        )
        try:
            self._log_box.frame.configure(background=t["LOG"])
        except Exception:
            pass
        self._log_box.pack(fill="both", expand=True, padx=8, pady=8)
        self._refresh_log_tags()
        ttk.Button(p, text="クリア", command=lambda: self._log_box.delete("1.0", "end")).pack(pady=(0, 8))

    # ── テーマ取得ヘルパー ────────────────────────────────────────────────────

    def _t(self):
        """現在のテーマ辞書を返す"""
        return THEMES[self._theme]

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
            except Exception:
                pass

        # 2) ログボックス
        self._log_box.config(
            bg=t["LOG"], fg=t["FG"],
            selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
            insertbackground=t["FG"],
        )
        try:
            self._log_box.frame.configure(background=t["LOG"])
        except Exception:
            pass
        self._refresh_log_tags()

        # 3) Treeview（fieldbackground は ttk.Style 側で制御されるが念のため）
        self._tree.configure(
            background=t["BG2"],
            foreground=t["FG"],
            fieldbackground=t["BG2"],
        )

        # 4) バージョン状態ラベルの色を現在の状態に合わせてリセット
        #    （選択中のアイテムがあれば再描画、なければニュートラル表示）
        self._refresh_ver_status_color()

    def _refresh_ver_status_color(self):
        """バージョン状態ラベルの foreground を現在テーマで正しく設定しなおす"""
        t = self._t()
        text = self._ver_status_side.cget("text")
        if text.startswith("✅"):
            self._ver_status_side.config(foreground=t["GRN"])
        elif text.startswith("⚠"):
            self._ver_status_side.config(foreground=t["RED"])
        elif text.startswith("🔄"):
            self._ver_status_side.config(foreground=t["YEL"])
        else:
            self._ver_status_side.config(foreground=t["FG"])

    # ── ヘルパー ──────────────────────────────────────────────────────────────

    def _log(self, msg, tag=""):
        def _do():
            self._log_box.insert("end", msg + "\n", tag)
            self._log_box.see("end")
        self.after(0, _do)

    def _set_status(self, msg):
        self.after(0, lambda: self._prog_label.config(text=msg))

    def _set_progress(self, v, maximum=None):
        def _do():
            if maximum is not None:
                self._progress.configure(maximum=maximum)
            self._progress.configure(value=v)
        self.after(0, _do)

    def _browse(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    def _cancel(self):
        self._cancel_flag = True
        self._set_status("中止中...")
        self._cancel_btn.config(state="disabled")

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
                foreground=self._t()["GRN"],
            )
        else:
            self._ver_combo["values"] = ["最新"]
            self._ver_var.set("最新")
            self._ver_status_side.config(
                text="← バージョン取得ボタンで一覧を取得",
                foreground=self._t()["FG"],
            )

    def _fetch_versions_side(self):
        if not self._current_iid:
            return
        item = next((it for it in self.plugin_list if it["filename"] == self._current_iid), None)
        if not item:
            return
        self._ver_status_side.config(text="🔄 取得中...", foreground=self._t()["YEL"])
        self._ver_combo.config(state="disabled")

        def _fetch():
            results = []
            try:
                pid = mr_search_plugin(item.get("name", ""))
                if pid:
                    vs = mr_get_plugin_versions(pid)
                    results = [{"label": v.get("version_number", "?"), "id": v["id"]} for v in vs]
            except Exception:
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
            self._ver_status_side.config(text=f"✅ {len(results)} 件取得", foreground=self._t()["GRN"])
        else:
            self._ver_status_side.config(text="⚠ バージョンなし", foreground=self._t()["RED"])

    def _on_ver_select(self, e=None):
        if not self._current_iid:
            return
        label = self._ver_var.get()
        if label == "最新":
            self._ver_overrides.pop(self._current_iid, None)
            self._ver_status_side.config(text="✅ 最新でDL", foreground=self._t()["GRN"])
        else:
            ver = next((v for v in self._versions_cache if v["label"] == label), None)
            if ver:
                self._ver_overrides[self._current_iid] = {"id": ver["id"], "label": label}
            self._ver_status_side.config(text=f"✅ {label} を選択", foreground=self._t()["GRN"])

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
        self._ver_status_side.config(text="", foreground=self._t()["FG"])

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
        self.after(0, lambda: self._cancel_btn.config(state="normal"))
        threading.Thread(target=self._worker, args=(selected,), daemon=True).start()

    def _worker(self, plugins):
        delete_old  = self.delete_old.get()
        delete_fail = self.delete_failed.get()
        auto_deps   = self.auto_deps.get()
        out_dir     = self.plugins_dir.get()
        done_deps   = set()
        ok_list     = []
        fail_list   = []

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

            dl_url, dl_fname, pid = find_plugin(name, _log, ver_id)

            if dl_url and dl_fname:
                dest = os.path.join(out_dir, dl_fname)
                if self._do_download(dl_url, dest, name, plugin.get("path"), delete_old, delete_fail):
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
                            du, df, _ = find_plugin(dep_name, _log)
                            if du and df and not os.path.exists(os.path.join(out_dir, df)):
                                self._do_download(du, os.path.join(out_dir, df), dep_name, None, False, delete_fail)
                                ok_list.append(f"[前提] {dep_name}")
                else:
                    fail_list.append(name)
            else:
                fail_list.append(name)
                self._log("  ❌ スキップ", "err")
                if delete_fail and plugin.get("path") and os.path.exists(plugin["path"]):
                    try:
                        os.remove(plugin["path"])
                        self._log("  🗑 失敗ファイル削除", "warn")
                    except Exception:
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
        self.after(0, lambda: self._cancel_btn.config(state="disabled"))

        msg = f"✅ 成功: {len(ok_list)} 件\n❌ 失敗: {len(fail_list)} 件"
        if fail_list:
            msg += "\n\n失敗:\n" + "\n".join(f"  • {n}" for n in fail_list)
        self.after(0, lambda: messagebox.showinfo("完了", msg))

    def _do_download(self, url, dest, name, old_path, delete_old, delete_fail):
        try:
            self._log(f"  ⬇ DL中 [Modrinth]: {os.path.basename(dest)}")
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
                except Exception:
                    pass
            if delete_fail and old_path and os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    self._log("  🗑 失敗ファイル削除", "warn")
                except Exception:
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
        except Exception:
            pass

        try:
            base            = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            ip              = os.path.join(base, "icon.ico")
            self._icon_path = ip if os.path.exists(ip) else None
            if self._icon_path:
                self.iconbitmap(default=self._icon_path)
        except Exception:
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

        self._plugin_app = PluginUpdaterApp(self, theme=self._theme, icon_path=self._icon_path)
        self._plugin_app.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self._plugin_app._disable_combobox_wheel()

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
