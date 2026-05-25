import os, re, sys, json, zipfile, hashlib, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import urllib.request, urllib.parse, webbrowser

SPIGET_API   = "https://api.spiget.org/v2"
MODRINTH_API = "https://api.modrinth.com/v2"
CONFIG_FILE  = os.path.join(os.path.expanduser("~"), ".mc_plugin_updater_config.json")

DL_BOTH_MR  = "両方（Modrinth優先）"
DL_BOTH_SP  = "両方（Spiget優先）"
DL_MR       = "Modrinthのみ"
DL_SP       = "Spigetのみ"
DL_MODES    = [DL_BOTH_MR, DL_BOTH_SP, DL_MR, DL_SP]

MC_VERSIONS_FALLBACK = [
    "1.21.4","1.21.3","1.21.1","1.21","1.20.6","1.20.4","1.20.2","1.20.1","1.20",
    "1.19.4","1.19.3","1.19.2","1.19.1","1.19","1.18.2","1.18.1","1.18",
    "1.17.1","1.17","1.16.5","1.16.4","1.16.3","1.16.2","1.16.1","1.15.2","1.12.2",
]

THEMES = {
    "light": {
        "BG":"#f4f4f0","BG2":"#e8e8e3","BG3":"#d0d0c8",
        "FG":"#1e1e1e","ACC":"#1d4ed8",
        "GRN":"#15803d","RED":"#dc2626","YEL":"#92400e",
        "LOG":"#ffffff","SEL":"#bfdbfe","SEL_FG":"#1e1e1e",
        "BTN_FG":"#ffffff","BTN_ACT":"#3b82f6","BTN_DIS":"#d0d0c8",
        "TREE_SEL":"#bfdbfe","ICON":"🌙",
    },
    "dark": {
        "BG":"#1e1e2e","BG2":"#2a2a3e","BG3":"#45475a",
        "FG":"#cdd6f4","ACC":"#89b4fa",
        "GRN":"#a6e3a1","RED":"#f38ba8","YEL":"#f9e2af",
        "LOG":"#181825","SEL":"#313244","SEL_FG":"#cdd6f4",
        "BTN_FG":"#1e1e2e","BTN_ACT":"#74c7ec","BTN_DIS":"#45475a",
        "TREE_SEL":"#45475a","ICON":"☀️",
    },
}

BG = BG2 = BG3 = FG = ACC = GRN = RED = YEL = ""

def _apply_theme_globals(theme):
    global BG, BG2, BG3, FG, ACC, GRN, RED, YEL
    t = THEMES[theme]
    BG,BG2,BG3 = t["BG"],t["BG2"],t["BG3"]
    FG,ACC = t["FG"],t["ACC"]
    GRN,RED,YEL = t["GRN"],t["RED"],t["YEL"]

def _current_theme():
    return "dark" if BG == THEMES["dark"]["BG"] else "light"

_apply_theme_globals("light")

# ── 設定 ──────────────────────────────────────────────────────
def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def save_config(data):
    try:
        with open(CONFIG_FILE,"w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
    except Exception: pass

# ── HTTP ──────────────────────────────────────────────────────
def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent","MC-Plugin-Updater/1.0")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def download_file(url, dest, progress_cb=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent","MC-Plugin-Updater/1.0")
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length",0))
        done  = 0
        with open(dest,"wb") as f:
            while chunk := r.read(65536):
                f.write(chunk); done += len(chunk)
                if progress_cb and total: progress_cb(done/total)

# ── MCバージョン ──────────────────────────────────────────────
def fetch_mc_versions():
    try:
        data = http_get(f"{MODRINTH_API}/tag/game_version")
        releases = [v["version"] for v in data
                    if v.get("version_type")=="release" and "." in v.get("version","")]
        releases.sort(key=lambda v: tuple(int(x) if x.isdigit() else 0
                                          for x in re.split(r"[.\-]",v)), reverse=True)
        return releases or MC_VERSIONS_FALLBACK
    except Exception: return MC_VERSIONS_FALLBACK

# ── JAR解析 ───────────────────────────────────────────────────
def read_jar_meta(jar_path):
    info = {"filename":os.path.basename(jar_path),"path":jar_path,
            "name":os.path.basename(jar_path),"version":""}
    try:
        with zipfile.ZipFile(jar_path) as zf:
            if "plugin.yml" in zf.namelist():
                raw = zf.read("plugin.yml").decode("utf-8",errors="ignore")
                for line in raw.splitlines():
                    line = line.strip()
                    if line.startswith("name:"):
                        info["name"] = line.split(":",1)[1].strip()
                    elif line.startswith("version:"):
                        info["version"] = line.split(":",1)[1].strip()
    except Exception: pass
    return info

# ── Spiget API ────────────────────────────────────────────────
def spiget_search(name, size=5):
    """プラグイン名でSpigetを検索"""
    try:
        params = urllib.parse.urlencode({
            "size": size, "sort": "-downloads",
            "fields": "id,name,tag,version,external,file,dependencies",
        })
        results = http_get(f"{SPIGET_API}/resources/search/{urllib.parse.quote(name)}?{params}")
        if not results: return None
        name_lower = name.lower()
        for r in results:
            if r.get("name","").lower() == name_lower: return r
        return results[0]
    except Exception: return None

def spiget_get_versions(resource_id, size=10):
    """バージョン一覧を取得"""
    try:
        params = urllib.parse.urlencode({"size":size,"sort":"-releaseDate"})
        return http_get(f"{SPIGET_API}/resources/{resource_id}/versions?{params}")
    except Exception: return []

def spiget_get_latest_version(resource_id):
    """最新バージョン情報を取得"""
    try:
        return http_get(f"{SPIGET_API}/resources/{resource_id}/versions/latest")
    except Exception: return None

def spiget_get_download_url(resource_id):
    """ダウンロードURL（リダイレクト先）を取得"""
    return f"{SPIGET_API}/resources/{resource_id}/download"

def spiget_get_deps(resource):
    """依存プラグインのリストを返す（名前のリスト）"""
    deps = resource.get("dependencies", [])
    if isinstance(deps, list):
        return [d.get("name","") if isinstance(d,dict) else str(d) for d in deps if d]
    return []

# ── Modrinth API ──────────────────────────────────────────────
def mr_search_plugin(name, mc_ver):
    try:
        params = urllib.parse.urlencode({
            "query": name, "limit": 5,
            "facets": json.dumps([
                ["project_type:plugin"],
                ["game_versions:" + mc_ver],
            ]),
        })
        hits = http_get(f"{MODRINTH_API}/search?{params}").get("hits",[])
        if not hits: return None
        name_lower = name.lower()
        for h in hits:
            if h.get("title","").lower() == name_lower: return h["project_id"]
        return hits[0]["project_id"]
    except Exception: return None

def mr_get_versions(pid, mc_ver):
    try:
        params = urllib.parse.urlencode({
            "game_versions": json.dumps([mc_ver]),
            "loaders": json.dumps(["paper","spigot","bukkit","purpur","folia"]),
        })
        return http_get(f"{MODRINTH_API}/project/{pid}/version?{params}")
    except Exception: return []

def mr_best_file(version_obj):
    du = df = None
    for fi in version_obj.get("files",[]):
        if fi.get("primary") or not du:
            du,df = fi["url"],fi["filename"]
            if fi.get("primary"): break
    return du,df

# ── 統合検索 ──────────────────────────────────────────────────
def find_plugin(name, mc_ver, mode, log_cb, target_ver=None):
    """
    プラグインを検索してDL情報を返す。
    target_ver: 特定バージョンを指定（Noneなら最新）
    戻り値: (url, filename, source, resource_info)
    """
    do_mr = mode in (DL_BOTH_MR, DL_BOTH_SP, DL_MR)
    do_sp = mode in (DL_BOTH_MR, DL_BOTH_SP, DL_SP)
    sp_first = mode == DL_BOTH_SP
    dl_url = dl_fname = source = resource_info = None

    def _try_mr():
        nonlocal dl_url, dl_fname, source, resource_info
        try:
            pid = mr_search_plugin(name, mc_ver)
            if not pid: log_cb("  Modrinth: 見つからず","warn"); return
            if target_ver:
                # 特定バージョンを検索
                all_vs = http_get(f"{MODRINTH_API}/project/{pid}/version")
                vs = [v for v in all_vs if v.get("version_number","").startswith(target_ver)]
                if not vs:
                    log_cb(f"  Modrinth: v{target_ver} 見つからず","warn"); return
            else:
                vs = mr_get_versions(pid, mc_ver)
                if not vs:
                    log_cb(f"  Modrinth: {mc_ver} 対応なし","warn"); return
            dl_url,dl_fname = mr_best_file(vs[0])
            source = "Modrinth"
            resource_info = {"type":"modrinth","id":pid,"version_obj":vs[0]}
            log_cb(f"  ✓ Modrinth: {dl_fname}","ok")
        except Exception as e: log_cb(f"  Modrinth エラー: {e}","err")

    def _try_spiget():
        nonlocal dl_url, dl_fname, source, resource_info
        try:
            res = spiget_search(name)
            if not res: log_cb("  Spiget: 見つからず","warn"); return
            rid = res["id"]

            # 外部ホスト（GitHub等）はDL不可
            if res.get("external"):
                log_cb(f"  Spiget: 外部ホスト（直接DL不可）","warn"); return

            if target_ver:
                # 特定バージョンを検索
                versions = spiget_get_versions(rid, size=50)
                matched = [v for v in versions if target_ver in v.get("name","")]
                if not matched:
                    log_cb(f"  Spiget: v{target_ver} 見つからず","warn"); return
                ver_name = matched[0].get("name","")
            else:
                latest = spiget_get_latest_version(rid)
                ver_name = latest.get("name","") if latest else ""

            dl_url   = spiget_get_download_url(rid)
            dl_fname = f"{res.get('name',name)}-{ver_name}.jar".replace(" ","_")
            source   = "Spiget"
            resource_info = {"type":"spiget","id":rid,"resource":res}
            log_cb(f"  ✓ Spiget: {res.get('name',name)} v{ver_name}","ok")
        except Exception as e: log_cb(f"  Spiget エラー: {e}","err")

    if sp_first:
        if do_sp: _try_spiget()
        if do_mr and not dl_url: _try_mr()
    else:
        if do_mr: _try_mr()
        if do_sp and not dl_url: _try_spiget()

    return dl_url, dl_fname, source, resource_info

# ══════════════════════════════════════════════════════════════
# Plugin Updater App（スタンドアロン or 埋め込み用）
# ══════════════════════════════════════════════════════════════
class PluginUpdaterApp(ttk.Frame):
    """
    tk.Tk または ttk.Notebook に埋め込み可能なプラグイン管理ウィジェット。
    """
    def __init__(self, parent, theme="light", icon_path=None, **kw):
        super().__init__(parent, **kw)
        self._theme     = theme
        self._icon_path = icon_path
        self._running   = False
        self._cancel_flag = False

        _apply_theme_globals(theme)

        cfg = load_config()
        self.plugins_dir   = tk.StringVar(value=cfg.get("plugins_dir",""))
        self.target_version= tk.StringVar(value=cfg.get("target_version","1.21.4"))
        self.dl_mode       = tk.StringVar(value=cfg.get("dl_mode",DL_BOTH_MR))
        self.delete_old    = tk.BooleanVar(value=cfg.get("delete_old",False))
        self.delete_failed = tk.BooleanVar(value=cfg.get("delete_failed",False))
        self.auto_deps     = tk.BooleanVar(value=cfg.get("auto_deps",True))

        self.plugin_list = []
        self._build()
        threading.Thread(target=self._fetch_versions_bg, daemon=True).start()

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

        bar = ttk.Frame(self); bar.pack(fill="x", padx=8, pady=(0,6))
        self._progress   = ttk.Progressbar(bar, mode="determinate")
        self._progress.pack(side="left", fill="x", expand=True, padx=(0,8))
        self._prog_label = ttk.Label(bar, text="", width=30)
        self._prog_label.pack(side="left")
        self._cancel_btn = ttk.Button(bar, text="⏹ 中止",
                                       command=self._cancel, state="disabled")
        self._cancel_btn.pack(side="left", padx=(6,0))

    # ── 設定タブ ──────────────────────────────────────────────
    def _build_settings(self, p):
        t = THEMES[self._theme]
        canvas = tk.Canvas(p, bg=t["BG"], highlightthickness=0)
        vsb    = ttk.Scrollbar(p, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
        self._settings_canvas = canvas

        f = ttk.Frame(canvas)
        wid = canvas.create_window((0,0), window=f, anchor="nw")
        f.bind("<Configure>",      lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        def _wheel(e):
            if isinstance(e.widget, ttk.Combobox): return
            try:
                if e.widget.winfo_toplevel() != self.winfo_toplevel(): return
            except Exception: return
            canvas.yview_scroll(int(-1*(e.delta/120)),"units")
        canvas.bind_all("<MouseWheel>", _wheel)

        PAD = dict(padx=12, pady=(0,8))

        # pluginsフォルダ
        lf0 = ttk.LabelFrame(f, text="🔌  Pluginsフォルダ"); lf0.pack(fill="x", **PAD)
        r0 = ttk.Frame(lf0); r0.pack(fill="x", padx=10, pady=8)
        ttk.Entry(r0, textvariable=self.plugins_dir).pack(
            side="left", fill="x", expand=True, padx=(0,6))
        ttk.Button(r0, text="参照",
                    command=lambda: self._browse(self.plugins_dir)).pack(side="left", padx=(0,6))
        ttk.Button(r0, text="📂 読み込む",
                    command=self._load_plugins).pack(side="left", padx=(0,6))
        ttk.Button(r0, text="⬇ ダウンロード",
                    command=self._start_update).pack(side="left", padx=(0,6))
        ttk.Button(r0, text="✕",
                    command=lambda: self.plugins_dir.set(""), width=3).pack(side="left")

        # MCバージョン
        lf2 = ttk.LabelFrame(f, text="🎯  対象MCバージョン"); lf2.pack(fill="x", **PAD)
        r2 = ttk.Frame(lf2); r2.pack(fill="x", padx=10, pady=8)
        ttk.Label(r2, text="MCバージョン:").pack(side="left")
        self._ver_cb = ttk.Combobox(r2, textvariable=self.target_version,
                                     values=MC_VERSIONS_FALLBACK, width=12, state="readonly")
        self._ver_cb.pack(side="left", padx=(4,4))
        self._ver_status = ttk.Label(r2, text="🔄 取得中...",
                                      foreground=t["YEL"], background=t["BG"],
                                      font=("Yu Gothic UI",8))
        self._ver_status.pack(side="left", padx=(0,10))
        ttk.Button(r2, text="✕ リセット",
                    command=lambda: self.target_version.set("")).pack(side="left")

        # DLモード
        lf3 = ttk.LabelFrame(f, text="🌐  ダウンロード設定"); lf3.pack(fill="x", **PAD)
        r3 = ttk.Frame(lf3); r3.pack(fill="x", padx=10, pady=(8,4))
        ttk.Label(r3, text="モード:").pack(side="left")
        self._dl_cb = ttk.Combobox(r3, textvariable=self.dl_mode,
                                    values=DL_MODES, width=24, state="readonly")
        self._dl_cb.pack(side="left", padx=(4,0))
        self._dl_cb.bind("<<ComboboxSelected>>", lambda _: self._update_mode_ui())
        self._mode_desc = ttk.Label(lf3, text="", foreground=t["YEL"],
                                     background=t["BG"], font=("Yu Gothic UI",9))
        self._mode_desc.pack(anchor="w", padx=10, pady=(0,8))
        self._update_mode_ui()

        # オプション
        lf4 = ttk.LabelFrame(f, text="⚙  オプション"); lf4.pack(fill="x", **PAD)
        for txt, var in [
            ("アップデート後に古いファイルを削除する",                    self.delete_old),
            ("ダウンロード失敗したファイルを削除する（壊れたファイル除去）", self.delete_failed),
            ("前提プラグインが足りなければ自動でダウンロードする",          self.auto_deps),
        ]:
            ttk.Checkbutton(lf4, text=txt, variable=var).pack(padx=10, pady=2, anchor="w")

        ttk.Frame(f, height=10).pack()

    # ── プラグイン一覧タブ ────────────────────────────────────
    def _build_list(self, p):
        top = ttk.Frame(p); top.pack(fill="x", padx=6, pady=(6,2))
        for text, w, cmd in [("全選択",6,lambda:self._sel_all(True)),
                               ("全解除",6,lambda:self._sel_all(False))]:
            ttk.Button(top, text=text, width=w, command=cmd).pack(side="left", padx=(0,3))
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=(0,6), pady=2)
        ttk.Button(top, text="📂 読込", width=7,
                    command=self._load_plugins).pack(side="left", padx=(0,3))
        ttk.Button(top, text="⬇ 更新", width=7,
                    command=self._start_update).pack(side="left")
        self._sel_label = ttk.Label(top, text="0 / 0 件", width=12, anchor="e")
        self._sel_label.pack(side="right", padx=4)

        # バージョン指定入力欄
        ver_row = ttk.Frame(p); ver_row.pack(fill="x", padx=6, pady=(0,4))
        ttk.Label(ver_row, text="バージョン指定（空欄で最新）:").pack(side="left")
        self._target_ver_var = tk.StringVar()
        ttk.Entry(ver_row, textvariable=self._target_ver_var, width=20).pack(
            side="left", padx=(6,6))
        ttk.Label(ver_row, text="例: 2.21.0", foreground=YEL,
                   background=BG, font=("Yu Gothic UI",8)).pack(side="left")

        cols  = ("chk","name","version","source")
        heads = [("chk","✔",36),("name","プラグイン名",260),
                 ("version","バージョン",100),("source","認識元",100)]
        self._tree = ttk.Treeview(p, columns=cols, show="headings", selectmode="none")
        for cid, lbl, w in heads:
            self._tree.heading(cid, text=lbl)
            self._tree.column(cid, width=w, minwidth=w if cid!="name" else 80,
                               anchor="center" if cid=="chk" else "w",
                               stretch=(cid=="name"))
        vsb = ttk.Scrollbar(p, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(6,0), pady=(0,6))
        vsb.pack(side="left", fill="y", pady=(0,6), padx=(0,6))
        self._tree.bind("<Button-1>", self._on_click)

    # ── ログタブ ──────────────────────────────────────────────
    def _build_log(self, p):
        t = THEMES[self._theme]
        self._log_box = scrolledtext.ScrolledText(
            p, bg=t["LOG"], fg=t["FG"],
            selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
            insertbackground=t["FG"], font=("Consolas",9), relief="flat", wrap="word")
        self._log_box.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, color in [("ok",t["GRN"]),("err",t["RED"]),("info",t["ACC"]),("warn",t["YEL"])]:
            self._log_box.tag_config(tag, foreground=color)
        ttk.Button(p, text="クリア",
                    command=lambda: self._log_box.delete("1.0","end")).pack(pady=(0,8))

    # ── ヘルパー ──────────────────────────────────────────────
    def _log(self, msg, tag=""):
        def _do():
            self._log_box.insert("end", msg+"\n", tag)
            self._log_box.see("end")
        self.after(0, _do)

    def _set_status(self, msg): self.after(0, lambda: self._prog_label.config(text=msg))
    def _set_progress(self, v, maximum=None):
        def _do():
            if maximum is not None: self._progress.configure(maximum=maximum)
            self._progress.configure(value=v)
        self.after(0, _do)

    def _update_mode_ui(self):
        mode = self.dl_mode.get()
        desc = {
            DL_BOTH_MR: "Modrinthで検索 → なければSpigetも",
            DL_BOTH_SP: "Spigetで検索 → なければModrinthも",
            DL_MR:      "Modrinthのみ",
            DL_SP:      "Spigetのみ",
        }.get(mode,"")
        self._mode_desc.config(text=f"  ℹ {desc}")

    def _browse(self, var):
        d = filedialog.askdirectory()
        if d: var.set(d)

    def _cancel(self):
        self._cancel_flag = True
        self._set_status("中止中...")
        self._cancel_btn.config(state="disabled")

    def _on_click(self, e):
        row = self._tree.identify_row(e.y)
        if row and self._tree.identify_column(e.x) == "#1":
            cur = self._tree.set(row,"chk")
            self._tree.set(row,"chk","☑" if cur=="☐" else "☐")
            self._upd_label()

    def _sel_all(self, v):
        mark = "☑" if v else "☐"
        for row in self._tree.get_children(): self._tree.set(row,"chk",mark)
        self._upd_label()

    def _upd_label(self):
        rows = self._tree.get_children()
        sel  = sum(1 for r in rows if self._tree.set(r,"chk")=="☑")
        self._sel_label.config(text=f"{sel} / {len(rows)} 件選択")

    def _disable_combobox_wheel(self):
        def _block(e): return "break"
        def _bind(w):
            if isinstance(w, ttk.Combobox):
                for ev in ("<MouseWheel>","<Button-4>","<Button-5>"): w.bind(ev, _block)
            for c in w.winfo_children(): _bind(c)
        _bind(self)

    # ── 読み込み ──────────────────────────────────────────────
    def _load_plugins(self):
        d = self.plugins_dir.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror("エラー","有効なpluginsフォルダを指定してください"); return
        jars = sorted(f for f in os.listdir(d) if f.lower().endswith(".jar"))
        if not jars:
            messagebox.showinfo("情報","JARファイルが見つかりませんでした"); return

        for row in self._tree.get_children(): self._tree.delete(row)
        self.plugin_list = []
        self._log(f"📂 {len(jars)} 個のJARを解析中...", "info")

        for fname in jars:
            path = os.path.join(d, fname)
            info = read_jar_meta(path)
            self.plugin_list.append(info)
            self._tree.insert("","end", iid=fname,
                               values=("☑", info.get("name",fname),
                                       info.get("version","?"), "plugin.yml"))
        self.plugin_list.sort(key=lambda x: x.get("name","").lower())
        # ソート後に再描画
        rows = list(self._tree.get_children())
        items = [(self._tree.item(r,"values"), r) for r in rows]
        for row in rows: self._tree.delete(row)
        for vals, iid in sorted(items, key=lambda x: x[0][1].lower()):
            self._tree.insert("","end", iid=iid, values=vals)

        self._upd_label()
        self._log(f"✅ {len(jars)} 件読み込み完了", "ok")
        self._nb.select(1)

    # ── アップデート ──────────────────────────────────────────
    def _start_update(self):
        selected = [it for it in self.plugin_list
                    if self._tree.exists(it["filename"]) and
                       self._tree.set(it["filename"],"chk")=="☑"]
        if not selected:
            messagebox.showinfo("情報","プラグインが選択されていません"); return
        if self._running:
            messagebox.showwarning("実行中","現在アップデート中です"); return

        self._running = True
        self._cancel_flag = False
        self._set_progress(0, len(selected))
        self._nb.select(2)
        self.after(0, lambda: self._cancel_btn.config(state="normal"))

        target_ver = self._target_ver_var.get().strip() or None
        threading.Thread(target=self._worker,
                          args=(selected, self.target_version.get(),
                                self.dl_mode.get(), target_ver),
                          daemon=True).start()

    # ── ワーカー ──────────────────────────────────────────────
    def _worker(self, plugins, mc_ver, mode, target_ver):
        delete_old  = self.delete_old.get()
        delete_fail = self.delete_failed.get()
        auto_deps   = self.auto_deps.get()
        out_dir     = self.plugins_dir.get()
        done_deps   = set()
        ok_list = []; fail_list = []

        for i, plugin in enumerate(plugins):
            if self._cancel_flag:
                self._log("\n⏹ 中止されました","warn"); break
            name = plugin.get("name", plugin["filename"])
            self._set_status(f"{i+1}/{len(plugins)}: {name[:24]}")
            self._log(f"\n── {name} ──","info")

            def _log(msg, tag=""): self._log(msg, tag)

            dl_url, dl_fname, source, res_info = find_plugin(
                name, mc_ver, mode, _log, target_ver)

            if dl_url and dl_fname:
                dest = os.path.join(out_dir, dl_fname)
                if self._do_download(dl_url, dest, name, source,
                                      plugin.get("path"), delete_old, delete_fail):
                    ok_list.append(name)
                    # 前提プラグイン
                    if auto_deps and res_info and res_info.get("type") == "spiget":
                        deps = spiget_get_deps(res_info.get("resource",{}))
                        for dep_name in deps:
                            if not dep_name or dep_name in done_deps: continue
                            done_deps.add(dep_name)
                            self._log(f"  🔗 依存プラグイン: {dep_name}","info")
                            # 既に存在するか確認
                            exists = any(
                                p.get("name","").lower() == dep_name.lower()
                                for p in self.plugin_list
                            )
                            if exists:
                                self._log(f"  🔗 既存: {dep_name}","ok"); continue
                            du, df, src, _ = find_plugin(dep_name, mc_ver, mode, _log, None)
                            if du and df:
                                ddest = os.path.join(out_dir, df)
                                if not os.path.exists(ddest):
                                    self._do_download(du, ddest, dep_name, src,
                                                       None, False, delete_fail)
                                    ok_list.append(f"[依存] {dep_name}")
                            else:
                                self._log(f"  🔗 依存プラグイン: 見つからず","warn")
                else:
                    fail_list.append(name)
            else:
                fail_list.append(name)
                self._log("  ❌ スキップ（対応バージョンなし）","err")
                if delete_fail and plugin.get("path") and os.path.exists(plugin["path"]):
                    try: os.remove(plugin["path"]); self._log(f"  🗑 失敗ファイル削除","warn")
                    except Exception: pass
            self._set_progress(i+1)

        self._log(f"\n{'═'*40}","info")
        self._log(f"✅ 成功: {len(ok_list)} 件","ok")
        for n in ok_list: self._log(f"   ✓ {n}","ok")
        if fail_list:
            self._log(f"❌ 失敗: {len(fail_list)} 件","err")
            for n in fail_list: self._log(f"   ✗ {n}","err")
        else:
            self._log("🎉 全て完了！","ok")

        self._set_status("完了" if not self._cancel_flag else "中止")
        self._running = False
        self.after(0, lambda: self._cancel_btn.config(state="disabled"))
        msg = f"✅ 成功: {len(ok_list)} 件\n❌ 失敗: {len(fail_list)} 件"
        if fail_list:
            msg += "\n\n失敗:\n" + "\n".join(f"  • {n}" for n in fail_list)
        self.after(0, lambda: messagebox.showinfo("完了", msg))

    def _do_download(self, url, dest, name, source, old_path, delete_old, delete_fail):
        try:
            self._log(f"  ⬇ DL中 [{source}]: {os.path.basename(dest)}")
            download_file(url, dest, lambda p: self._set_status(f"DL: {name[:18]} {p*100:.0f}%"))
            if delete_old and old_path and os.path.exists(old_path):
                if os.path.abspath(dest) != os.path.abspath(old_path):
                    os.remove(old_path)
                    self._log(f"  🗑 旧ファイル削除: {os.path.basename(old_path)}","warn")
            self._log("  ✅ 完了","ok"); return True
        except Exception as e:
            self._log(f"  ❌ DL失敗: {e}","err")
            if os.path.exists(dest):
                try: os.remove(dest)
                except Exception: pass
            if delete_fail and old_path and os.path.exists(old_path):
                try: os.remove(old_path); self._log(f"  🗑 失敗ファイル削除","warn")
                except Exception: pass
            return False

    def _fetch_versions_bg(self):
        versions = fetch_mc_versions()
        def _upd():
            cur = self.target_version.get()
            self._ver_cb["values"] = versions
            self._ver_cb.set(cur if cur in versions else versions[0])
            self.target_version.set(self._ver_cb.get())
            t = THEMES[self._theme]
            if versions == MC_VERSIONS_FALLBACK:
                self._ver_status.config(text="⚠ オフライン", foreground=t["YEL"])
            else:
                self._ver_status.config(text=f"✅ {len(versions)} 件", foreground=t["GRN"])
        self.after(0, _upd)

    # ── テーマ適用（外部から呼ぶ） ────────────────────────────
    def apply_theme(self, theme):
        self._theme = theme
        t = THEMES[theme]
        self._settings_canvas.config(bg=t["BG"])
        self._log_box.config(bg=t["LOG"], fg=t["FG"],
                              selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
                              insertbackground=t["FG"])
        for tag, color in [("ok",t["GRN"]),("err",t["RED"]),("info",t["ACC"]),("warn",t["YEL"])]:
            self._log_box.tag_config(tag, foreground=color)
        self._tree.configure(background=t["BG2"], foreground=t["FG"], fieldbackground=t["BG2"])
        self._mode_desc.config(foreground=t["YEL"], background=t["BG"])
        self._ver_status.config(background=t["BG"])

    def save_config(self):
        save_config({
            "plugins_dir":    self.plugins_dir.get(),
            "target_version": self.target_version.get(),
            "dl_mode":        self.dl_mode.get(),
            "delete_old":     self.delete_old.get(),
            "delete_failed":  self.delete_failed.get(),
            "auto_deps":      self.auto_deps.get(),
        })

# ── スタンドアロン起動 ────────────────────────────────────────
class StandaloneApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🔌 MC Plugin Updater")
        self.geometry("900x700"); self.configure(bg=BG); self.resizable(True, True)
        cfg = load_config()
        self._theme = cfg.get("theme","light")
        _apply_theme_globals(self._theme)
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MCPluginUpdater.App.1.0")
        except Exception: pass
        try:
            base = getattr(sys,"_MEIPASS",os.path.dirname(os.path.abspath(__file__)))
            ip   = os.path.join(base,"icon.ico")
            self._icon_path = ip if os.path.exists(ip) else None
            if self._icon_path: self.iconbitmap(default=self._icon_path)
        except Exception: self._icon_path = None
        self._apply_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_style(self):
        t = THEMES[self._theme]
        BG,BG2,BG3 = t["BG"],t["BG2"],t["BG3"]
        FG,ACC = t["FG"],t["ACC"]
        s = ttk.Style(self); s.theme_use("clam")
        s.configure("TFrame",            background=BG)
        s.configure("TLabel",            background=BG, foreground=FG, font=("Yu Gothic UI",10))
        s.configure("Hdr.TLabel",        background=BG, foreground=ACC, font=("Yu Gothic UI",13,"bold"))
        s.configure("Sub.TLabel",        background=BG, foreground=FG, font=("Yu Gothic UI",9))
        s.configure("TButton",           background=ACC, foreground=t["BTN_FG"],
                     font=("Yu Gothic UI",10,"bold"), relief="flat", padding=(8,5))
        s.map("TButton",                 background=[("active",t["BTN_ACT"]),("disabled",t["BTN_DIS"])],
                                         foreground=[("disabled","#6c7086")])
        s.configure("TEntry",            fieldbackground=BG2, foreground=FG, insertcolor=FG, relief="flat", padding=4)
        s.configure("TCheckbutton",      background=BG, foreground=FG, font=("Yu Gothic UI",10))
        s.map("TCheckbutton",            background=[("active",BG)])
        s.configure("TCombobox",         fieldbackground=BG2, foreground=FG,
                     selectbackground=BG2, selectforeground=FG, padding=4)
        s.map("TCombobox",
              fieldbackground=[("readonly",BG2),("disabled",BG3)],
              foreground=[("readonly",FG),("disabled","#6c7086")],
              selectbackground=[("readonly",BG2)], selectforeground=[("readonly",FG)])
        s.configure("Treeview",          background=BG2, foreground=FG, fieldbackground=BG2,
                     rowheight=26, font=("Yu Gothic UI",9))
        s.configure("Treeview.Heading",  background=BG, foreground=ACC,
                     font=("Yu Gothic UI",9,"bold"), relief="flat")
        s.map("Treeview",                background=[("selected",t["TREE_SEL"])],
                                         foreground=[("selected",t["SEL_FG"])])
        s.map("Treeview.Heading",        background=[("active",BG2),("pressed",BG2)],
                                         foreground=[("active",ACC),("pressed",ACC)],
                                         relief=[("active","flat"),("pressed","flat")])
        s.configure("TProgressbar",      troughcolor=BG2, background=ACC, thickness=8)
        s.configure("TNotebook",         background=BG, tabmargins=0)
        s.configure("TNotebook.Tab",     background=BG2, foreground=FG, padding=[14,7], font=("Yu Gothic UI",10))
        s.map("TNotebook.Tab",           background=[("selected",BG)], foreground=[("selected",ACC)])
        s.configure("TLabelframe",       background=BG, relief="solid", borderwidth=1, bordercolor=BG3)
        s.configure("TLabelframe.Label", background=BG, foreground=ACC, font=("Yu Gothic UI",10,"bold"))
        s.configure("TSeparator",        background=BG3)
        self.configure(bg=BG)

    def _build_ui(self):
        t = THEMES[self._theme]
        hdr = ttk.Frame(self); hdr.pack(fill="x", padx=12, pady=(12,0))
        hdr.columnconfigure(0, weight=1); hdr.columnconfigure(1, weight=1); hdr.columnconfigure(2, weight=1)
        ttk.Label(hdr, text="🔌  MC Plugin Updater", style="Hdr.TLabel").grid(row=0, column=1)
        self._theme_btn = ttk.Button(hdr, text=t["ICON"], command=self._toggle_theme, width=3)
        self._theme_btn.grid(row=0, column=2, sticky="e")
        ttk.Label(self, text="Spigot / Paper / Bukkit プラグインを一括アップデート",
                   style="Sub.TLabel").pack(pady=(2,8))
        self._plugin_app = PluginUpdaterApp(self, theme=self._theme,
                                             icon_path=self._icon_path)
        self._plugin_app.pack(fill="both", expand=True, padx=12, pady=(0,4))
        self._plugin_app._disable_combobox_wheel()

    def _toggle_theme(self):
        self._theme = "dark" if self._theme == "light" else "light"
        _apply_theme_globals(self._theme)
        self._apply_style()
        t = THEMES[self._theme]
        self._theme_btn.config(text=t["ICON"])
        self._plugin_app.apply_theme(self._theme)

    def _on_close(self):
        self._plugin_app.save_config()
        save_config({**load_config(), "theme": self._theme})
        self.destroy()

if __name__ == "__main__":
    app = StandaloneApp()
    app.mainloop()
