import os, re, sys, json, zipfile, hashlib, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import urllib.request, urllib.parse, webbrowser

MODRINTH_API   = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"
CONFIG_FILE    = os.path.join(os.path.expanduser("~"), ".mc_pack_updater_config.json")
MC_VERSIONS_FALLBACK = [
    "1.21.4","1.21.3","1.21.1","1.21","1.20.6","1.20.4","1.20.2","1.20.1","1.20",
    "1.19.4","1.19.3","1.19.2","1.19.1","1.19","1.18.2","1.18.1","1.18",
    "1.17.1","1.17","1.16.5","1.16.4","1.16.3","1.16.2","1.16.1","1.15.2","1.12.2",
]
LOADERS     = ["fabric","forge","neoforge","quilt"]
DL_BOTH     = "両方（Modrinth優先）"
DL_CF_FIRST = "両方（CurseForge優先）"
DL_MR       = "Modrinthのみ"
DL_CF       = "CurseForgeのみ"
DL_MODES    = [DL_BOTH, DL_CF_FIRST, DL_MR, DL_CF]
CF_LOADER   = {"forge":1,"fabric":4,"quilt":5,"neoforge":6}
CF_GAME, CF_MOD, CF_RP, CF_SHADE = 432, 6, 12, 6552
MR_MOD, MR_RP, MR_SHADE = "mod", "resourcepack", "shader"
LOADER_MIN  = {"forge":(1,1),"fabric":(1,14),"quilt":(1,16),"neoforge":(1,20,1)}

THEMES = {
    "light": {
        "BG":  "#f4f4f0", "BG2": "#e8e8e3", "BG3": "#d0d0c8",
        "FG":  "#1e1e1e", "ACC": "#1d4ed8",
        "GRN": "#15803d", "RED": "#dc2626", "YEL": "#92400e",
        "LOG": "#ffffff", "SEL": "#bfdbfe", "SEL_FG": "#1e1e1e",
        "BTN_FG": "#ffffff", "BTN_ACT": "#3b82f6", "BTN_DIS": "#d0d0c8",
        "TREE_SEL": "#bfdbfe", "ROW_ODD": "#f0f0eb",
        "ICON": "🌙",
    },
    "dark": {
        "BG":  "#1e1e2e", "BG2": "#2a2a3e", "BG3": "#45475a",
        "FG":  "#cdd6f4", "ACC": "#89b4fa",
        "GRN": "#a6e3a1", "RED": "#f38ba8", "YEL": "#f9e2af",
        "LOG": "#181825", "SEL": "#313244", "SEL_FG": "#cdd6f4",
        "BTN_FG": "#1e1e2e", "BTN_ACT": "#74c7ec", "BTN_DIS": "#45475a",
        "TREE_SEL": "#45475a", "ROW_ODD": "#252535",
        "ICON": "☀️",
    },
}

# グローバルカラー変数（テーマ切り替え時に更新）
BG = BG2 = BG3 = FG = ACC = GRN = RED = YEL = ""
def _apply_theme_globals(theme):
    global BG, BG2, BG3, FG, ACC, GRN, RED, YEL
    t = THEMES[theme]
    BG, BG2, BG3 = t["BG"], t["BG2"], t["BG3"]
    FG, ACC      = t["FG"], t["ACC"]
    GRN, RED, YEL = t["GRN"], t["RED"], t["YEL"]
_apply_theme_globals("light")

# ── ユーティリティ ────────────────────────────────────────────
def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception: pass

def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent", "MC-Pack-Updater/6.0")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def download_file(url, dest, progress_cb=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MC-Pack-Updater/6.0")
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        done  = 0
        with open(dest, "wb") as f:
            while chunk := r.read(65536):
                f.write(chunk); done += len(chunk)
                if progress_cb and total: progress_cb(done / total)

def clean_name(raw):
    n = re.sub(r'[\s_\-\.]+(mc|for|fabric|forge|neoforge|quilt)\d+[\.\d]*$', '', raw, flags=re.I)
    n = re.sub(r'[\s_\-\.]+v\d+[\.\d]*[a-zA-Z]*$', '', n, flags=re.I)
    n = re.sub(r'[\s_\-\.]+\d+\.\d+[\.\d]*[a-zA-Z]*$', '', n, flags=re.I)
    return n.strip(" _-.") or raw

def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""): h.update(chunk)
    return h.hexdigest()

def ver_tuple(v):
    try: return tuple(int(x) for x in v.split("."))
    except Exception: return (0,)

# ── MCバージョン ──────────────────────────────────────────────
def fetch_mc_versions():
    try:
        data = http_get(f"{MODRINTH_API}/tag/game_version")
        releases = [v["version"] for v in data
                    if v.get("version_type") == "release" and "." in v.get("version","")]
        releases.sort(key=lambda v: tuple(int(x) if x.isdigit() else 0
                                          for x in re.split(r"[.\-]", v)), reverse=True)
        return releases or MC_VERSIONS_FALLBACK
    except Exception: return MC_VERSIONS_FALLBACK

# ── JAR解析 ───────────────────────────────────────────────────
def read_jar_meta(jar_path):
    info = {"filename":os.path.basename(jar_path), "path":jar_path,
            "name":os.path.basename(jar_path), "mod_id":"", "version":"", "loader":"不明"}
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = zf.namelist()
            for meta in ("fabric.mod.json","quilt.mod.json"):
                if meta in names:
                    d = json.loads(zf.read(meta).decode("utf-8", errors="ignore"))
                    info.update({"mod_id":d.get("id",""), "name":d.get("name",info["filename"]),
                                 "version":d.get("version",""),
                                 "loader":"quilt" if meta.startswith("quilt") else "fabric"})
                    return info
            for meta in ("META-INF/mods.toml","META-INF/neoforge.mods.toml"):
                if meta in names:
                    raw = zf.read(meta).decode("utf-8", errors="ignore")
                    info["loader"] = "neoforge" if "neoforge" in meta else "forge"
                    in_mods = False
                    for line in raw.splitlines():
                        line = line.strip()
                        if line.startswith("[[mods]]"): in_mods = True
                        if in_mods:
                            if line.startswith("modId"):
                                info["mod_id"] = line.split("=",1)[1].strip().strip('"')
                            elif line.startswith("displayName"):
                                info["name"] = line.split("=",1)[1].strip().strip('"')
                            elif line.startswith("version"):
                                v = line.split("=",1)[1].strip().strip('"')
                                if not v.startswith("$"): info["version"] = v
                    return info
    except Exception: pass
    return info

# ── Modrinth API ──────────────────────────────────────────────
def mr_find_project(sha1, mod_id, name, mr_type):
    for fn in [
        lambda: http_get(f"{MODRINTH_API}/version_file/{sha1}?algorithm=sha1").get("project_id") if sha1 else None,
        lambda: http_get(f"{MODRINTH_API}/project/{mod_id}").get("id") if mod_id else None,
    ]:
        try:
            r = fn()
            if r: return r
        except Exception: pass
    try:
        params = urllib.parse.urlencode({"query":name,"limit":5,
                                          "facets":json.dumps([["project_type:"+mr_type]])})
        hits = http_get(f"{MODRINTH_API}/search?{params}").get("hits",[])
        if not hits: return None
        for h in hits:
            if h.get("title","").lower() == name.lower(): return h["project_id"]
        return hits[0]["project_id"]
    except Exception: return None

def mr_get_versions(pid, mc_ver, loader, mr_type=MR_MOD):
    try:
        p = {"game_versions":json.dumps([mc_ver])}
        if mr_type == MR_MOD: p["loaders"] = json.dumps([loader])
        vs = http_get(f"{MODRINTH_API}/project/{pid}/version?{urllib.parse.urlencode(p)}")
        # Quiltで見つからない場合はFabricでも再検索（Quilt/Fabric互換）
        if not vs and loader == "quilt" and mr_type == MR_MOD:
            p["loaders"] = json.dumps(["fabric"])
            vs = http_get(f"{MODRINTH_API}/project/{pid}/version?{urllib.parse.urlencode(p)}")
        return vs
    except Exception: return []

def mr_get_deps(version_obj):
    return [(d.get("project_id"), d.get("version_id"))
            for d in version_obj.get("dependencies",[])
            if d.get("dependency_type") == "required" and d.get("project_id")]

def mr_best_file(version_obj):
    du = df = None
    for fi in version_obj.get("files",[]):
        if fi.get("primary") or not du:
            du, df = fi["url"], fi["filename"]
            if fi.get("primary"): break
    return du, df

# ── CurseForge API ────────────────────────────────────────────
def _cf_req(url, api_key):
    req = urllib.request.Request(url)
    req.add_header("User-Agent","MC-Pack-Updater/6.0")
    req.add_header("x-api-key", api_key)
    req.add_header("Accept","application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def cf_search(name, api_key, class_id):
    params = urllib.parse.urlencode({"gameId":CF_GAME,"classId":class_id,
                                      "searchFilter":name,"pageSize":5,"sortField":2,"sortOrder":"desc"})
    try:
        results = _cf_req(f"{CURSEFORGE_API}/mods/search?{params}", api_key).get("data",[])
        if not results: return None
        for r in results:
            if r.get("name","").lower() == name.lower(): return r["id"]
        return results[0]["id"]
    except Exception: return None

def cf_get_file(cf_id, mc_ver, loader, api_key, mr_type=MR_MOD):
    loader_id = CF_LOADER.get(loader, 0) if mr_type == MR_MOD else 0
    params = urllib.parse.urlencode({"gameVersion":mc_ver,"modLoaderType":loader_id,"pageSize":10})
    try:
        files = _cf_req(f"{CURSEFORGE_API}/mods/{cf_id}/files?{params}", api_key).get("data",[])
        files.sort(key=lambda f: (f.get("releaseType",9), -f.get("id",0)))
        return files[0] if files else None
    except Exception: return None

# ── 統合検索 ──────────────────────────────────────────────────
def find_dl_info(name, mod_id, path, mc_ver, loader, mode, cf_key, mr_type, cf_class, log_cb):
    do_mr = mode in (DL_BOTH, DL_CF_FIRST, DL_MR)
    do_cf = mode in (DL_BOTH, DL_CF_FIRST, DL_CF)
    dl_url = dl_fname = source = version_obj = None

    def _try_mr():
        nonlocal dl_url, dl_fname, source, version_obj
        try:
            sha1 = sha1_file(path) if path and os.path.exists(path) else None
            pid  = mr_find_project(sha1, mod_id, name, mr_type)
            if not pid: log_cb("  Modrinth: 見つからず","warn"); return
            vs = mr_get_versions(pid, mc_ver, loader, mr_type)
            # Quiltで見つからない場合はFabricでも試す
            if not vs and loader == "quilt":
                vs = mr_get_versions(pid, mc_ver, "fabric", mr_type)
                if vs: log_cb("  Modrinth: Fabric互換バージョンで代替","warn")
            if not vs: log_cb(f"  Modrinth: {mc_ver} 対応なし","warn"); return
            version_obj = vs[0]
            dl_url, dl_fname = mr_best_file(vs[0]); source = "Modrinth"
            log_cb(f"  ✓ Modrinth: {dl_fname}","ok")
        except Exception as e: log_cb(f"  Modrinth エラー: {e}","err")

    def _try_cf():
        nonlocal dl_url, dl_fname, source
        try:
            cf_id = cf_search(name, cf_key, cf_class)
            if not cf_id: log_cb("  CurseForge: 見つからず","warn"); return
            fi = cf_get_file(cf_id, mc_ver, loader, cf_key, mr_type)
            if not fi: log_cb(f"  CurseForge: {mc_ver} 対応なし","warn"); return
            dl_url, dl_fname, source = fi.get("downloadUrl"), fi.get("fileName"), "CurseForge"
            log_cb(f"  ✓ CurseForge: {dl_fname}","ok")
        except Exception as e: log_cb(f"  CurseForge エラー: {e}","err")

    if mode == DL_CF_FIRST:
        if do_cf: _try_cf()
        if do_mr and not dl_url: _try_mr()
    else:
        if do_mr: _try_mr()
        if do_cf and not dl_url: _try_cf()
    return dl_url, dl_fname, source, version_obj

# ══════════════════════════════════════════════════════════════
# FileListPanel
# ══════════════════════════════════════════════════════════════
class FileListPanel(ttk.Frame):
    def __init__(self, parent, mr_type, load_fn, update_fn, **kw):
        super().__init__(parent, **kw)
        self.mr_type, self._load_fn, self._update_fn = mr_type, load_fn, update_fn
        self.items = []
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=(6,2))
        for text, w, cmd in [("全選択",6,lambda:self._sel_all(True)),
                               ("全解除",6,lambda:self._sel_all(False))]:
            ttk.Button(top, text=text, width=w, command=cmd).pack(side="left", padx=(0,3))
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=(0,6), pady=2)
        ttk.Button(top, text="📂 読込", width=7, command=self._load_fn).pack(side="left", padx=(0,3))
        ttk.Button(top, text="⬇ 更新", width=7, command=self._update_fn).pack(side="left")
        self._sel_label = ttk.Label(top, text="0 / 0 件", width=12, anchor="e")
        self._sel_label.pack(side="right", padx=4)

        if self.mr_type == MR_MOD:
            cols  = ("chk","name","version","loader")
            heads = [("chk","✔",36),("name","名前",200),("version","バージョン",95),("loader","Loader",70)]
        else:
            cols  = ("chk","name")
            heads = [("chk","✔",36),("name","名前",280)]

        self._tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="none")
        for cid, lbl, w in heads:
            self._tree.heading(cid, text=lbl)
            self._tree.column(cid, width=w, minwidth=w if cid!="name" else 80,
                               anchor="center" if cid=="chk" else "w", stretch=(cid=="name"))
        self._tree.tag_configure("even", background=BG2)
        self._tree.tag_configure("odd",  background="#f0f0eb")
        self._tree.tag_configure("dep",  background="#dbeafe")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(4,0), pady=(0,4))
        vsb.pack(side="left", fill="y", pady=(0,4), padx=(0,4))
        self._tree.bind("<Button-1>", self._on_click)

    def populate(self, items):
        for row in self._tree.get_children(): self._tree.delete(row)
        self.items = list(items)
        for i, it in enumerate(self.items):
            iid     = it["filename"]
            display = it.get("display_name") or it.get("name", iid)
            vals    = (("☑",display,it.get("version","?"),it.get("loader","?"))
                       if self.mr_type==MR_MOD else ("☑",display))
            self._tree.insert("","end", iid=iid, tags=("even" if i%2==0 else "odd",), values=vals)
        self._upd_label()

    def add_item(self, item, tag="dep"):
        iid = item["filename"]
        if self._tree.exists(iid): return
        self.items.append(item)
        vals = (("☑",item.get("name",iid),item.get("version",""),item.get("loader",""))
                if self.mr_type==MR_MOD else ("☑",item.get("name",iid)))
        self._tree.insert("","end", iid=iid, tags=(tag,), values=vals)
        self._upd_label()

    def get_selected(self):
        return [it for it in self.items
                if self._tree.exists(it["filename"]) and self._tree.set(it["filename"],"chk")=="☑"]

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

# ══════════════════════════════════════════════════════════════
# App
# ══════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("⛏ MC Pack Updater")
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MCPackUpdater.App.1.0")
        except Exception: pass
        try:
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            ip   = os.path.join(base, "icon.ico")
            self._icon_path = ip if os.path.exists(ip) else None
            if self._icon_path: self.iconbitmap(default=self._icon_path)
        except Exception: self._icon_path = None
        self.geometry("1150x780"); self.configure(bg=BG); self.resizable(True, True)

        cfg = load_config()
        self.target_version = tk.StringVar(value=cfg.get("target_version","1.21.4"))
        self.target_loader  = tk.StringVar(value=cfg.get("target_loader","fabric"))
        self.cf_api_key     = tk.StringVar(value=cfg.get("cf_api_key",""))
        self.dl_mode        = tk.StringVar(value=cfg.get("dl_mode",DL_BOTH))
        self.profile_dir    = tk.StringVar(value=cfg.get("profile_dir",""))
        self.mods_dir       = tk.StringVar(value=cfg.get("mods_dir",""))
        self.rp_dir         = tk.StringVar(value=cfg.get("rp_dir",""))
        self.shader_dir     = tk.StringVar(value=cfg.get("shader_dir",""))
        self.delete_old     = tk.BooleanVar(value=cfg.get("delete_old",False))
        self.delete_failed  = tk.BooleanVar(value=cfg.get("delete_failed",False))
        self.auto_deps      = tk.BooleanVar(value=cfg.get("auto_deps",True))
        self.strict_deps    = tk.BooleanVar(value=cfg.get("strict_deps",False))
        self._cf_key_showing = False
        self._running = self._cancel_flag = False
        self._theme = cfg.get("theme", "light")
        _apply_theme_globals(self._theme)

        self._apply_style(); self._build_ui(); self._disable_combobox_wheel()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._fetch_versions_bg, daemon=True).start()

    def _apply_style(self):
        t = THEMES[self._theme]
        BG, BG2, BG3 = t["BG"], t["BG2"], t["BG3"]
        FG, ACC = t["FG"], t["ACC"]
        s = ttk.Style(self); s.theme_use("clam")
        s.configure("TFrame",           background=BG)
        s.configure("TLabel",           background=BG, foreground=FG, font=("Yu Gothic UI",10))
        s.configure("Hdr.TLabel",       background=BG, foreground=ACC, font=("Yu Gothic UI",13,"bold"))
        s.configure("Sub.TLabel",       background=BG, foreground=FG, font=("Yu Gothic UI",9))
        s.configure("TButton",          background=ACC, foreground=t["BTN_FG"],
                     font=("Yu Gothic UI",10,"bold"), relief="flat", padding=(8,5))
        s.map("TButton",                background=[("active",t["BTN_ACT"]),("disabled",t["BTN_DIS"])],
                                        foreground=[("disabled","#6c7086")])
        s.configure("TEntry",           fieldbackground=BG2, foreground=FG, insertcolor=FG, relief="flat", padding=4)
        s.configure("TCheckbutton",     background=BG, foreground=FG, font=("Yu Gothic UI",10))
        s.map("TCheckbutton",           background=[("active",BG)])
        s.configure("TCombobox",        fieldbackground=BG2, foreground=FG,
                     selectbackground=BG2, selectforeground=FG, padding=4)
        s.map("TCombobox",
              fieldbackground=[("readonly",BG2),("disabled",BG3)],
              foreground=[("readonly",FG),("disabled","#6c7086")],
              selectbackground=[("readonly",BG2)], selectforeground=[("readonly",FG)])
        s.configure("Treeview",         background=BG2, foreground=FG, fieldbackground=BG2,
                     rowheight=26, font=("Yu Gothic UI",9))
        s.configure("Treeview.Heading", background=BG, foreground=ACC,
                     font=("Yu Gothic UI",9,"bold"), relief="flat")
        s.map("Treeview",               background=[("selected",t["TREE_SEL"])],
                                        foreground=[("selected",t["SEL_FG"])])
        s.map("Treeview.Heading",       background=[("active",BG2),("pressed",BG2)],
                                        foreground=[("active",ACC),("pressed",ACC)],
                                        relief=[("active","flat"),("pressed","flat")])
        s.configure("TProgressbar",     troughcolor=BG2, background=ACC, thickness=8)
        s.configure("TNotebook",        background=BG, tabmargins=0)
        s.configure("TNotebook.Tab",    background=BG2, foreground=FG, padding=[14,7], font=("Yu Gothic UI",10))
        s.map("TNotebook.Tab",          background=[("selected",BG)], foreground=[("selected",ACC)])
        s.configure("TLabelframe",      background=BG, relief="solid", borderwidth=1, bordercolor=BG3)
        s.configure("TLabelframe.Label",background=BG, foreground=ACC, font=("Yu Gothic UI",10,"bold"))
        s.configure("TSeparator",       background=BG3)
        self.configure(bg=BG)

    def _build_ui(self):
        hdr = ttk.Frame(self); hdr.pack(fill="x", padx=12, pady=(12,0))
        hdr.columnconfigure(0, weight=1)
        hdr.columnconfigure(1, weight=1)
        hdr.columnconfigure(2, weight=1)
        ttk.Label(hdr, text="⛏  MC Pack Updater", style="Hdr.TLabel").grid(
            row=0, column=1, sticky="")
        self._theme_btn = ttk.Button(hdr, text=THEMES[self._theme]["ICON"],
                                      command=self._toggle_theme, width=3)
        self._theme_btn.grid(row=0, column=2, sticky="e")
        ttk.Label(self, text="Mod / ResourcePack / Shader を一括アップデート",
                   style="Sub.TLabel").pack(pady=(2,8))
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True, padx=12, pady=(0,4))
        for tab, label in [(ttk.Frame(self._nb), " ⚙ 設定 "),
                            (ttk.Frame(self._nb), " 📦 一覧 "),
                            (ttk.Frame(self._nb), " 📋 ログ ")]:
            self._nb.add(tab, text=label)
        tabs = self._nb.tabs()
        self._build_settings(self._nb.nametowidget(tabs[0]))
        self._build_lists(self._nb.nametowidget(tabs[1]))
        self._build_log(self._nb.nametowidget(tabs[2]))
        bar = ttk.Frame(self); bar.pack(fill="x", padx=12, pady=(0,8))
        self._progress   = ttk.Progressbar(bar, mode="determinate")
        self._progress.pack(side="left", fill="x", expand=True, padx=(0,10))
        self._prog_label = ttk.Label(bar, text="", width=34)
        self._prog_label.pack(side="left")
        self._cancel_btn = ttk.Button(bar, text="⏹ 中止", command=self._cancel, state="disabled")
        self._cancel_btn.pack(side="left", padx=(8,0))

    def _build_settings(self, p):
        t = THEMES[self._theme]
        self._settings_canvas = tk.Canvas(p, bg=t["BG"], highlightthickness=0)
        canvas = self._settings_canvas
        vsb    = ttk.Scrollbar(p, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
        f = ttk.Frame(canvas)
        wid = canvas.create_window((0,0), window=f, anchor="nw")
        f.bind("<Configure>",      lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        def _wheel(e):
            if isinstance(e.widget, ttk.Combobox): return
            try:
                if e.widget.winfo_toplevel() != self: return
            except Exception: return
            canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)
        PAD = dict(padx=14, pady=(0,8))

        # 起動構成
        lf0 = ttk.LabelFrame(f, text="🚀  起動構成フォルダ"); lf0.pack(fill="x", **PAD)
        self._profile_note = ttk.Label(lf0, text="指定すると mods / resourcepacks / shaderpacks を自動検出します",
                   foreground=YEL, background=BG, font=("Yu Gothic UI",8))
        self._profile_note.pack(anchor="w", padx=10, pady=(4,0))
        r0 = ttk.Frame(lf0); r0.pack(fill="x", padx=10, pady=(4,8))
        ttk.Entry(r0, textvariable=self.profile_dir).pack(side="left", fill="x", expand=True, padx=(0,6))
        ttk.Button(r0, text="参照",       command=lambda: self._browse(self.profile_dir)).pack(side="left", padx=(0,6))
        ttk.Button(r0, text="📂 読み込む", command=self._load_from_profile).pack(side="left", padx=(0,6))
        ttk.Button(r0, text="⬇ ダウンロード", command=self._start_all).pack(side="left", padx=(0,6))
        ttk.Button(r0, text="✕", command=lambda: self.profile_dir.set(""), width=3).pack(side="left")

        # 個別フォルダ
        lf1 = ttk.LabelFrame(f, text="📁  個別フォルダ指定"); lf1.pack(fill="x", **PAD)
        for lbl, var in [("🧩 Mods",self.mods_dir),("🎨 ResourcePacks",self.rp_dir),("✨ Shaders",self.shader_dir)]:
            row = ttk.Frame(lf1); row.pack(fill="x", padx=10, pady=3)
            ttk.Label(row, text=lbl, width=18).pack(side="left")
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=(0,6))
            ttk.Button(row, text="参照", command=lambda v=var: self._browse(v)).pack(side="left", padx=(0,6))
            ttk.Button(row, text="✕",   command=lambda v=var: v.set(""), width=3).pack(side="left")

        # バージョン
        lf2 = ttk.LabelFrame(f, text="🎯  アップデート先"); lf2.pack(fill="x", **PAD)
        r2 = ttk.Frame(lf2); r2.pack(fill="x", padx=10, pady=8)
        ttk.Label(r2, text="MCバージョン:").pack(side="left")
        self._ver_cb = ttk.Combobox(r2, textvariable=self.target_version,
                                     values=MC_VERSIONS_FALLBACK, width=12, state="readonly")
        self._ver_cb.pack(side="left", padx=(4,4))
        self._ver_status = ttk.Label(r2, text="🔄 取得中...", foreground=YEL, background=BG, font=("Yu Gothic UI",8))
        self._ver_status.pack(side="left", padx=(0,14))
        ttk.Label(r2, text="Mod Loader:").pack(side="left")
        self._loader_cb = ttk.Combobox(r2, textvariable=self.target_loader,
                                        values=LOADERS, width=12, state="readonly")
        self._loader_cb.pack(side="left", padx=(4,10))
        self._loader_cb.bind("<<ComboboxSelected>>", lambda _: self._filter_versions())
        ttk.Button(r2, text="✕ リセット",
                    command=lambda: (self.target_version.set(""), self.target_loader.set(""))).pack(side="left")

        # DL設定
        lf3 = ttk.LabelFrame(f, text="🌐  ダウンロード設定"); lf3.pack(fill="x", **PAD)
        r3 = ttk.Frame(lf3); r3.pack(fill="x", padx=10, pady=(8,4))
        ttk.Label(r3, text="モード:").pack(side="left")
        self._dl_mode_cb = ttk.Combobox(r3, textvariable=self.dl_mode, values=DL_MODES, width=24, state="readonly")
        self._dl_mode_cb.pack(side="left", padx=(4,0))
        self._dl_mode_cb.bind("<<ComboboxSelected>>", lambda _: self._update_mode_ui())
        self._mode_desc = ttk.Label(lf3, text="", foreground=YEL, background=BG, font=("Yu Gothic UI",9))
        self._mode_desc.pack(anchor="w", padx=10, pady=(0,4))
        ttk.Separator(lf3, orient="horizontal").pack(fill="x", padx=10, pady=4)
        r4 = ttk.Frame(lf3); r4.pack(fill="x", padx=10, pady=(2,8))
        ttk.Label(r4, text="CurseForge APIキー:").pack(side="left")
        self._cf_entry = ttk.Entry(r4, textvariable=self.cf_api_key, show="*", width=38)
        self._cf_entry.pack(side="left", padx=(6,6))
        self._cf_show_btn = ttk.Button(r4, text="表示", command=self._toggle_cf_show, width=5)
        self._cf_show_btn.pack(side="left", padx=(0,6))
        ttk.Button(r4, text="取得方法 ↗", command=self._show_api_guide).pack(side="left")
        self._update_mode_ui()

        # オプション
        lf4 = ttk.LabelFrame(f, text="⚙  オプション"); lf4.pack(fill="x", **PAD)
        for txt, var in [
            ("アップデート後に古いファイルを削除する",                    self.delete_old),
            ("ダウンロード失敗したファイルを削除する（壊れたファイル除去）", self.delete_failed),
            ("前提Modが足りなければ自動でダウンロードする",               self.auto_deps),
            ("前提Modのバージョンを厳密に指定する（不安定な場合はOFF）",   self.strict_deps),
        ]:
            ttk.Checkbutton(lf4, text=txt, variable=var).pack(padx=10, pady=2, anchor="w")

        # 操作ボタン
        lf5 = ttk.LabelFrame(f, text="▶  操作"); lf5.pack(fill="x", padx=14, pady=(0,4))
        top_row = ttk.Frame(lf5); top_row.pack(fill="x", padx=10, pady=(8,4))
        ttk.Button(top_row, text="📂 全て読み込む",     command=self._load_all).pack(side="left", padx=(0,8))
        ttk.Button(top_row, text="🔄 全て一括アップデート", command=self._start_all).pack(side="left")
        ttk.Separator(lf5, orient="horizontal").pack(fill="x", padx=10, pady=4)
        for lbl, load_cmd, upd_cmd in [
            ("🧩 Mod",          self._load_mods,   lambda: self._start_panel(self._mod_panel,   "Mod")),
            ("🎨 ResourcePack", self._load_rp,     lambda: self._start_panel(self._rp_panel,    "ResourcePack")),
            ("✨ Shader",        self._load_shader, lambda: self._start_panel(self._shader_panel,"Shader")),
        ]:
            row = ttk.Frame(lf5); row.pack(fill="x", padx=10, pady=3)
            ttk.Label(row, text=lbl, width=16).pack(side="left")
            ttk.Button(row, text="📂 読み込む",     command=load_cmd).pack(side="left", padx=(0,6))
            ttk.Button(row, text="⬇ アップデート", command=upd_cmd).pack(side="left")
        ttk.Frame(f, height=10).pack()

    def _build_lists(self, p):
        p.columnconfigure(0, weight=1); p.columnconfigure(1, weight=1)
        p.columnconfigure(2, weight=1); p.rowconfigure(0, weight=1)
        for col, (attr, mr_type, lbl, load_fn, upd_fn) in enumerate([
            ("_mod_panel",    MR_MOD,   "🧩 Mod",          "_load_mods",   "_mod_panel"),
            ("_rp_panel",     MR_RP,    "🎨 ResourcePack",  "_load_rp",     "_rp_panel"),
            ("_shader_panel", MR_SHADE, "✨ Shader",         "_load_shader", "_shader_panel"),
        ]):
            lf = ttk.LabelFrame(p, text=f"  {lbl}  ")
            lf.grid(row=0, column=col, sticky="nsew", padx=5, pady=5)
            panel = FileListPanel(lf, mr_type,
                                   load_fn=getattr(self, load_fn.replace("_mod_panel","_load_mods")
                                                   .replace("_rp_panel","_load_rp")
                                                   .replace("_shader_panel","_load_shader"), None)
                                            or self.__getattribute__(load_fn),
                                   update_fn=lambda p=attr: self._start_panel(getattr(self, p), lbl))
            panel.pack(fill="both", expand=True)
            setattr(self, attr, panel)

    def _build_log(self, p):
        self._log_boxes = {}
        p.columnconfigure(0, weight=1); p.columnconfigure(1, weight=1)
        p.columnconfigure(2, weight=1); p.rowconfigure(0, weight=1); p.rowconfigure(1, weight=3)
        lf_sys = ttk.LabelFrame(p, text="  🖥 システム  ")
        lf_sys.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=5, pady=(5,2))
        sys_box = scrolledtext.ScrolledText(lf_sys, bg=THEMES[self._theme]["LOG"], fg=THEMES[self._theme]["FG"],
                                             selectbackground=THEMES[self._theme]["SEL"],
                                             selectforeground=THEMES[self._theme]["SEL_FG"],
                                             insertbackground=THEMES[self._theme]["FG"], height=5,
                                             font=("Consolas",9), relief="flat", wrap="word")
        sys_box.pack(fill="both", expand=True, padx=4, pady=(4,0))
        for tag, color in [("ok",GRN),("err",RED),("info",ACC),("warn",YEL)]:
            sys_box.tag_config(tag, foreground=color)
        ttk.Button(lf_sys, text="クリア", command=lambda b=sys_box: b.delete("1.0","end")).pack(pady=3)
        self._log_boxes["sys"] = sys_box
        for col, (key, lbl) in enumerate([("mod","🧩 Mod"),("rp","🎨 ResourcePack"),("shader","✨ Shader")]):
            lf = ttk.LabelFrame(p, text=f"  {lbl}  ")
            lf.grid(row=1, column=col, sticky="nsew", padx=5, pady=(2,5))
            box = scrolledtext.ScrolledText(lf, bg=THEMES[self._theme]["LOG"], fg=THEMES[self._theme]["FG"],
                                             selectbackground=THEMES[self._theme]["SEL"],
                                             selectforeground=THEMES[self._theme]["SEL_FG"],
                                             insertbackground=THEMES[self._theme]["FG"],
                                             font=("Consolas",9), relief="flat", wrap="word")
            box.pack(fill="both", expand=True, padx=4, pady=(4,0))
            for tag, color in [("ok",GRN),("err",RED),("info",ACC),("warn",YEL)]:
                box.tag_config(tag, foreground=color)
            ttk.Button(lf, text="クリア", command=lambda b=box: b.delete("1.0","end")).pack(pady=3)
            self._log_boxes[key] = box

    # ── ヘルパー ──────────────────────────────────────────────
    def _log(self, msg, tag="", key="mod"):
        box = self._log_boxes.get(key, self._log_boxes["mod"])
        self.after(0, lambda: (box.insert("end", msg+"\n", tag), box.see("end")))

    def _set_status(self, msg): self.after(0, lambda: self._prog_label.config(text=msg))
    def _set_progress(self, v, maximum=None):
        def _do():
            if maximum is not None: self._progress.configure(maximum=maximum)
            self._progress.configure(value=v)
        self.after(0, _do)

    def _toggle_theme(self):
        self._theme = "dark" if self._theme == "light" else "light"
        _apply_theme_globals(self._theme)
        self._apply_style()
        t = THEMES[self._theme]
        self._theme_btn.config(text=t["ICON"])
        # ログボックスの色を更新
        for box in self._log_boxes.values():
            box.config(bg=t["LOG"], fg=t["FG"],
                       selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
                       insertbackground=t["FG"])
            for tag, color in [("ok",t["GRN"]),("err",t["RED"]),("info",t["ACC"]),("warn",t["YEL"])]:
                box.tag_config(tag, foreground=color)
        # ラベルの色を更新
        self._mode_desc.config(foreground=t["YEL"], background=t["BG"])
        self._ver_status.config(background=t["BG"])
        self._profile_note.config(foreground=t["YEL"], background=t["BG"])
        self._settings_canvas.config(bg=t["BG"])
        # Treeviewの全色を更新
        for panel in (self._mod_panel, self._rp_panel, self._shader_panel):
            panel._tree.configure(background=t["BG2"], foreground=t["FG"],
                                   fieldbackground=t["BG2"])
            panel._tree.tag_configure("even", background=t["BG2"])
            panel._tree.tag_configure("odd",  background=t["ROW_ODD"])
            panel._tree.tag_configure("dep",  background=t["SEL"])
            # 既存の行のタグを再適用
            for i, row in enumerate(panel._tree.get_children()):
                current_tags = panel._tree.item(row, "tags")
                if "dep" not in current_tags:
                    panel._tree.item(row, tags=("even" if i%2==0 else "odd",))

    def _update_mode_ui(self):
        mode = self.dl_mode.get()
        desc = {DL_BOTH:"Modrinthで検索 → なければCurseForgeも",
                DL_CF_FIRST:"CurseForgeで検索 → なければModrinthも（APIキー必須）",
                DL_MR:"Modrinthのみ（APIキー不要）",DL_CF:"CurseForgeのみ（APIキー必須）"}.get(mode,"")
        self._mode_desc.config(text=f"  ℹ {desc}")
        need_cf = mode in (DL_BOTH, DL_CF_FIRST, DL_CF)
        state   = "normal" if need_cf else "disabled"
        self._cf_entry.config(state=state); self._cf_show_btn.config(state=state)

    def _toggle_cf_show(self):
        self._cf_key_showing = not self._cf_key_showing
        self._cf_entry.config(show="" if self._cf_key_showing else "*")
        self._cf_show_btn.config(text="隠す" if self._cf_key_showing else "表示")

    def _browse(self, var):
        d = filedialog.askdirectory()
        if d: var.set(d)

    def _validate_cf(self):
        if self.dl_mode.get() in (DL_BOTH, DL_CF_FIRST, DL_CF) and not self.cf_api_key.get().strip():
            messagebox.showerror("エラー","CurseForgeを使用するにはAPIキーが必要です"); return False
        return True

    def _cancel(self):
        self._cancel_flag = True
        self._set_status("中止中...")
        self._cancel_btn.config(state="disabled")

    def _disable_combobox_wheel(self):
        def _block(e): return "break"
        def _bind(w):
            if isinstance(w, ttk.Combobox):
                for ev in ("<MouseWheel>","<Button-4>","<Button-5>"): w.bind(ev, _block)
            for c in w.winfo_children(): _bind(c)
        _bind(self)
        for ev in ("<MouseWheel>","<Button-4>","<Button-5>"): self._ver_cb.bind(ev, _block)

    def _filter_versions(self):
        min_ver = LOADER_MIN.get(self.target_loader.get())
        all_v   = list(self._ver_cb["values"])
        if not all_v or not min_ver: return
        filtered = [v for v in all_v if ver_tuple(v) >= min_ver]
        self._ver_cb["values"] = filtered
        if self.target_version.get() not in filtered and filtered:
            self._ver_cb.set(filtered[0]); self.target_version.set(filtered[0])

    def _show_api_guide(self):
        base     = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        pdf_path = os.path.join(base, "API Key Guide.pdf")
        if not os.path.exists(pdf_path):
            webbrowser.open("https://console.curseforge.com/"); return
        try: import fitz
        except ImportError: os.startfile(pdf_path); return

        win = tk.Toplevel(self)
        win.title("API Key 取得方法"); win.configure(bg=BG)
        if self._icon_path:
            try: win.iconbitmap(self._icon_path)
            except Exception: pass
        self.update_idletasks()
        mw,mh,mx,my = self.winfo_width(),self.winfo_height(),self.winfo_x(),self.winfo_y()
        ww,wh = int(mw*2/3), int(mh*2/3)
        win.geometry(f"{ww}x{wh}+{mx+(mw-ww)//2}+{my+(mh-wh)//2}")
        win.resizable(True, True)

        doc    = fitz.open(pdf_path)
        total  = len(doc)
        page_var = tk.IntVar(value=1)
        img_ref  = [None]

        toolbar = ttk.Frame(win); toolbar.pack(fill="x", padx=8, pady=(8,4))
        ttk.Button(toolbar, text="✕ 閉じる", command=win.destroy).pack(side="right", padx=(4,0))
        ttk.Button(toolbar, text="▶ 次", command=lambda: (page_var.set(min(page_var.get()+1,total)), _draw())).pack(side="right", padx=(4,0))
        ttk.Button(toolbar, text="◀ 前", command=lambda: (page_var.set(max(page_var.get()-1,1)), _draw())).pack(side="right", padx=(4,0))
        ttk.Label(toolbar, text=f"/ {total} ページ").pack(side="right", padx=(4,0))
        ttk.Spinbox(toolbar, from_=1, to=total, textvariable=page_var, width=4).pack(side="right", padx=(4,4))

        frame  = ttk.Frame(win); frame.pack(fill="both", expand=True, padx=8, pady=(0,8))
        canvas = tk.Canvas(frame, bg="#808080", highlightthickness=0)
        vsb    = ttk.Scrollbar(frame, orient="vertical",   command=canvas.yview)
        hsb    = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y"); hsb.pack(side="bottom", fill="x")
        canvas.pack(side="left", fill="both", expand=True)

        def _draw(event=None):
            canvas.update_idletasks()
            w   = max(canvas.winfo_width(), 400)
            pg  = doc[page_var.get()-1]
            mat = fitz.Matrix(w/pg.rect.width, w/pg.rect.width)
            pix = pg.get_pixmap(matrix=mat, alpha=False)
            img = tk.PhotoImage(data=pix.tobytes("ppm"))
            img_ref[0] = img
            canvas.delete("all")
            canvas.create_image(w//2, 0, anchor="n", image=img)
            canvas.configure(scrollregion=(0, 0, w, img.height()))
            canvas.yview_moveto(0)

        canvas.bind("<Configure>", _draw)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)),"units")
                    if e.widget.winfo_toplevel()==win else None)
        page_var.trace_add("write", lambda *_: _draw())
        win.after(100, _draw)

    # ── 読み込み ──────────────────────────────────────────────
    def _load_dir(self, dir_var, ext, panel, key, kind_label):
        d = dir_var.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror("エラー", f"有効な{kind_label}フォルダを指定してください"); return False
        files = sorted(f for f in os.listdir(d) if f.lower().endswith(ext))
        if not files:
            messagebox.showinfo("情報", f"{ext}ファイルが見つかりませんでした"); return False
        self._log(f"📂 {kind_label}: {len(files)} 個を解析中...", "info", "sys")
        items = []
        for fname in files:
            path = os.path.join(d, fname)
            if ext == ".jar":
                info = read_jar_meta(path)
            else:
                raw  = os.path.splitext(fname)[0]
                info = {"filename":fname,"path":path,"name":clean_name(raw),
                        "display_name":raw,"mod_id":"","version":"","loader":""}
            items.append(info)
        items.sort(key=lambda x: x.get("name","").lower())
        panel.populate(items)
        self._log(f"✅ {kind_label}: {len(items)} 件読み込み完了", "ok", "sys")
        return True

    def _load_mods(self):
        if self._load_dir(self.mods_dir, ".jar", self._mod_panel, "mod", "Mod"): self._nb.select(1)

    def _load_rp(self):
        if self._load_dir(self.rp_dir, ".zip", self._rp_panel, "rp", "ResourcePack"): self._nb.select(1)

    def _load_shader(self):
        if self._load_dir(self.shader_dir, ".zip", self._shader_panel, "shader", "Shader"): self._nb.select(1)

    def _load_all(self):
        self._load_mods(); self._load_rp(); self._load_shader(); self._nb.select(1)

    def _load_from_profile(self):
        base = self.profile_dir.get().strip()
        if not base or not os.path.isdir(base):
            messagebox.showerror("エラー","有効な起動構成フォルダを指定してください"); return
        mapping = {"mods":self.mods_dir,"resourcepacks":self.rp_dir,"shaderpacks":self.shader_dir}
        found = []
        for sub, var in mapping.items():
            path = os.path.join(base, sub)
            if os.path.isdir(path): var.set(path); found.append(sub)
        if not found:
            messagebox.showwarning("確認", f"mods / resourcepacks / shaderpacks が見つかりませんでした\n{base}"); return
        self._log(f"🚀 起動構成検出: {base}", "info", "sys")
        for sub in found: self._log(f"   ✓ {sub}", "ok", "sys")
        self._load_all()

    # ── アップデート ──────────────────────────────────────────
    def _build_tasks(self, panel):
        dir_map  = {MR_MOD:self.mods_dir.get(),MR_RP:self.rp_dir.get(),MR_SHADE:self.shader_dir.get()}
        cf_class = {MR_MOD:CF_MOD,MR_RP:CF_RP,MR_SHADE:CF_SHADE}[panel.mr_type]
        return [(it, dir_map[panel.mr_type], panel.mr_type, cf_class) for it in panel.get_selected()]

    def _start_panel(self, panel, label):
        if not self._validate_cf(): return
        tasks = self._build_tasks(panel)
        if not tasks: messagebox.showinfo("情報","アイテムが選択されていません"); return
        self._run_tasks(tasks)

    def _start_all(self):
        if not self._validate_cf(): return
        tasks = self._build_tasks(self._mod_panel) + self._build_tasks(self._rp_panel) + self._build_tasks(self._shader_panel)
        if not tasks: messagebox.showinfo("情報","アイテムが選択されていません"); return
        self._run_tasks(tasks)

    def _run_tasks(self, tasks):
        if self._running: messagebox.showwarning("実行中","現在アップデート中です"); return
        self._running = True; self._cancel_flag = False
        self._set_progress(0, len(tasks)); self._nb.select(2)
        self.after(0, lambda: self._cancel_btn.config(state="normal"))
        threading.Thread(target=self._worker,
                          args=(tasks, self.target_version.get(), self.target_loader.get(),
                                self.dl_mode.get(), self.cf_api_key.get().strip()),
                          daemon=True).start()

    def _worker(self, tasks, mc_ver, loader, mode, cf_key):
        delete_old  = self.delete_old.get()
        delete_fail = self.delete_failed.get()
        auto_deps   = self.auto_deps.get()
        strict      = self.strict_deps.get()
        done_deps   = set()
        results     = {"mod":{"ok":[],"fail":[]},"rp":{"ok":[],"fail":[]},"shader":{"ok":[],"fail":[]}}

        for i, (item, out_dir, mr_type, cf_class) in enumerate(tasks):
            if self._cancel_flag:
                self._log("\n⏹ ユーザーによって中止されました","warn","mod"); break
            name = item.get("name", item["filename"])
            key  = {"mod":"mod","resourcepack":"rp","shader":"shader"}.get(mr_type,"mod")
            kind = {"mod":"Mod","rp":"RP","shader":"Shader"}[key]
            self._set_status(f"{i+1}/{len(tasks)}: [{kind}] {name[:22]}")
            self._log(f"\n── {name} ──","info",key)
            def _log(msg, tag="", _k=key): self._log(msg, tag, _k)

            dl_url, dl_fname, source, version_obj = find_dl_info(
                name, item.get("mod_id",""), item.get("path"),
                mc_ver, loader, mode, cf_key, mr_type, cf_class, _log)

            if dl_url and dl_fname:
                dest       = os.path.join(out_dir, dl_fname)
                do_del_old = delete_old  if mr_type == MR_MOD else False
                do_del_fail= delete_fail if mr_type == MR_MOD else False
                success    = self._do_download(dl_url, dest, name, source,
                                                item.get("path"), do_del_old, do_del_fail, key)
                if success:
                    results[key]["ok"].append(name)
                    if mr_type == MR_MOD and auto_deps and version_obj:
                        for dep_pid, dep_vid in mr_get_deps(version_obj):
                            if dep_pid in done_deps: continue
                            done_deps.add(dep_pid)
                            self._log(f"  🔗 依存Mod: {dep_pid}","info",key)
                            try:
                                du = df = None
                                if strict and dep_vid:
                                    self._log(f"  🔗 指定バージョン: {dep_vid}","info",key)
                                    v_data = http_get(f"{MODRINTH_API}/version/{dep_vid}")
                                    du, df = mr_best_file(v_data)
                                    # 既存の同Modで古いバージョンがあれば差し替え
                                    if du and df:
                                        try:
                                            slug = http_get(f"{MODRINTH_API}/project/{dep_pid}").get("slug","")
                                            for fn in os.listdir(out_dir):
                                                if not fn.lower().endswith(".jar"): continue
                                                fp = os.path.join(out_dir, fn)
                                                m  = read_jar_meta(fp)
                                                if m.get("mod_id") == slug and fn != df:
                                                    self._log(f"  🔗 バージョン不足のため差し替え: {fn}","warn",key)
                                                    try: os.remove(fp)
                                                    except Exception: pass
                                                    break
                                        except Exception: pass
                                else:
                                    vs = mr_get_versions(dep_pid, mc_ver, loader)
                                    if vs: du, df = mr_best_file(vs[0])
                                if du and df:
                                    ddest = os.path.join(out_dir, df)
                                    if os.path.exists(ddest):
                                        self._log(f"  🔗 既存: {df}","ok",key)
                                    else:
                                        self._do_download(du, ddest, df, "Modrinth", None, False, do_del_fail, key)
                                        dep_item = {"filename":df,"path":ddest,"name":df,"mod_id":"","version":"","loader":""}
                                        self.after(0, lambda di=dep_item: self._mod_panel.add_item(di,"dep"))
                                        results[key]["ok"].append(f"[依存] {df}")
                                else:
                                    self._log(f"  🔗 依存Mod: 対応バージョンなし","warn",key)
                            except Exception as e:
                                self._log(f"  🔗 依存エラー: {e}","err",key)
                else:
                    results[key]["fail"].append(name)
            else:
                results[key]["fail"].append(name)
                self._log("  ❌ スキップ（対応バージョンなし）","err",key)
                if delete_fail and mr_type == MR_MOD and item.get("path") and os.path.exists(item["path"]):
                    try: os.remove(item["path"]); self._log(f"  🗑 失敗ファイル削除: {item['filename']}","warn",key)
                    except Exception: pass
            self._set_progress(i+1)

        total_ok   = sum(len(v["ok"])   for v in results.values())
        total_fail = sum(len(v["fail"]) for v in results.values())
        for key, lbl in [("mod","🧩 Mod"),("rp","🎨 ResourcePack"),("shader","✨ Shader")]:
            ok, fail = results[key]["ok"], results[key]["fail"]
            if not ok and not fail: continue
            self._log(f"\n{'═'*40}","info",key)
            self._log(f"{lbl} 結果","info",key)
            self._log(f"✅ 成功: {len(ok)} 件","ok",key)
            for n in ok: self._log(f"   ✓ {n}","ok",key)
            if fail:
                self._log(f"❌ 失敗: {len(fail)} 件","err",key)
                for n in fail: self._log(f"   ✗ {n}","err",key)
            else:
                self._log("🎉 全て完了！","ok",key)

        self._set_status("完了" if not self._cancel_flag else "中止")
        self._running = False
        self.after(0, lambda: self._cancel_btn.config(state="disabled"))
        msg = f"✅ 成功: {total_ok} 件\n❌ 失敗: {total_fail} 件"
        if total_fail:
            msg += "\n"
            for key, lbl in [("mod","🧩 Mod"),("rp","🎨 ResourcePack"),("shader","✨ Shader")]:
                if results[key]["fail"]:
                    msg += f"\n{lbl}:\n" + "\n".join(f"  • {n}" for n in results[key]["fail"]) + "\n"
        self.after(0, lambda: messagebox.showinfo("完了", msg))

    def _do_download(self, url, dest, name, source, old_path, delete_old, delete_fail, log_key):
        try:
            self._log(f"  ⬇ DL中 [{source}]: {os.path.basename(dest)}","",log_key)
            download_file(url, dest, lambda p: self._set_status(f"DL: {name[:18]} {p*100:.0f}%"))
            if delete_old and old_path and os.path.exists(old_path):
                if os.path.abspath(dest) != os.path.abspath(old_path):
                    os.remove(old_path)
                    self._log(f"  🗑 旧ファイル削除: {os.path.basename(old_path)}","",log_key)
            self._log("  ✅ 完了","ok",log_key); return True
        except Exception as e:
            self._log(f"  ❌ DL失敗: {e}","err",log_key)
            if os.path.exists(dest):
                try: os.remove(dest)
                except Exception: pass
            if delete_fail and old_path and os.path.exists(old_path):
                try: os.remove(old_path); self._log(f"  🗑 失敗ファイル削除: {os.path.basename(old_path)}","warn",log_key)
                except Exception: pass
            return False

    def _fetch_versions_bg(self):
        versions = fetch_mc_versions()
        def _upd():
            cur = self.target_version.get()
            self._ver_cb["values"] = versions
            self._ver_cb.set(cur if cur in versions else versions[0])
            self.target_version.set(self._ver_cb.get())
            self._filter_versions()
            for ev in ("<MouseWheel>","<Button-4>","<Button-5>"):
                self._ver_cb.bind(ev, lambda e: "break")
            if versions == MC_VERSIONS_FALLBACK:
                self._ver_status.config(text="⚠ オフライン", foreground=YEL)
                self._log("⚠ バージョン取得失敗 → フォールバック使用","warn","sys")
            else:
                self._ver_status.config(text=f"✅ {len(versions)} 件", foreground=GRN)
                self._log(f"✅ MCバージョン {len(versions)} 件取得（最新: {versions[0]}）","ok","sys")
        self.after(0, _upd)

    def _on_close(self):
        save_config({
            "profile_dir":    self.profile_dir.get(),
            "mods_dir":       self.mods_dir.get(),
            "rp_dir":         self.rp_dir.get(),
            "shader_dir":     self.shader_dir.get(),
            "target_version": self.target_version.get(),
            "target_loader":  self.target_loader.get(),
            "cf_api_key":     self.cf_api_key.get(),
            "dl_mode":        self.dl_mode.get(),
            "delete_old":     self.delete_old.get(),
            "delete_failed":  self.delete_failed.get(),
            "auto_deps":      self.auto_deps.get(),
            "strict_deps":    self.strict_deps.get(),
            "theme":          self._theme,
        })
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()
