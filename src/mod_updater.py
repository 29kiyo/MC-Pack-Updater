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
LOADERS     = ["fabric","forge","neoforge"]
DL_BOTH     = "両方（Modrinth優先）"
DL_CF_FIRST = "両方（CurseForge優先）"
DL_MR       = "Modrinthのみ"
DL_CF       = "CurseForgeのみ"
DL_MODES    = [DL_BOTH, DL_CF_FIRST, DL_MR, DL_CF]
CF_LOADER   = {"forge":1,"fabric":4,"neoforge":6}
CF_GAME, CF_MOD, CF_RP, CF_SHADE = 432, 6, 12, 6552
MR_MOD, MR_RP, MR_SHADE = "mod", "resourcepack", "shader"
LOADER_MIN  = {"forge":(1,1),"fabric":(1,14),"neoforge":(1,20,1)}

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

def _current_theme():
    """現在のテーマ名を返す（BGでライト/ダークを判定）"""
    return "dark" if BG == THEMES["dark"]["BG"] else "light"
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
    except Exception: pass  # 設定保存失敗は起動に影響しないため無視

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
    n = re.sub(r'[\s_\-\.]+(mc|for|fabric|forge|neoforge)\d+[\.\d]*$', '', raw, flags=re.I)
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
    except Exception: pass  # 解析失敗時は空の info を返す（呼び出し元でフォールバック）
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
        except Exception: pass  # 取得失敗時は次の取得方法を試みる
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
        return http_get(f"{MODRINTH_API}/project/{pid}/version?{urllib.parse.urlencode(p)}")
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
def find_dl_info(name, mod_id, path, mc_ver, loader, mode, cf_key, mr_type, cf_class, log_cb, **kwargs):
    do_mr = mode in (DL_BOTH, DL_CF_FIRST, DL_MR)
    do_cf = mode in (DL_BOTH, DL_CF_FIRST, DL_CF)
    dl_url = dl_fname = source = version_obj = None

    def _try_mr():
        nonlocal dl_url, dl_fname, source, version_obj
        try:
            sha1 = sha1_file(path) if path and os.path.exists(path) else None
            pid  = mr_find_project(sha1, mod_id, name, mr_type)
            if not pid: log_cb("  Modrinth: 見つからず","warn"); return
            # バージョンオーバーライドがある場合はそのバージョンを直接取得
            ver_override = kwargs.get("ver_override")
            if ver_override:
                v_data = http_get(f"{MODRINTH_API}/version/{ver_override}")
                vs = [v_data]
                log_cb("  Modrinth: 指定バージョンを使用", "info")
            else:
                vs = mr_get_versions(pid, mc_ver, loader, mr_type)
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
    def __init__(self, parent, mr_type, load_fn, update_fn, ver_fetch_fn=None, **kw):
        super().__init__(parent, **kw)
        self.mr_type       = mr_type
        self._load_fn      = load_fn
        self._update_fn    = update_fn
        self._ver_fetch_fn = ver_fetch_fn  # (item, callback) -> None
        self.items         = []
        self._ver_overrides = {}  # filename -> version_id or None（Noneなら最新）
        self._build()

    def _build(self):
        # ── ツールバー ──
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

        # ── 左右分割 ──
        body = ttk.Frame(self); body.pack(fill="both", expand=True)

        # 左: Treeview
        left = ttk.Frame(body); left.pack(side="left", fill="both", expand=True)
        if self.mr_type == MR_MOD:
            cols  = ("chk","name","version","loader")
            heads = [("chk","✔",36),("name","名前",180),("version","バージョン",90),("loader","Loader",66)]
        else:
            cols  = ("chk","name")
            heads = [("chk","✔",36),("name","名前",240)]

        self._tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="none")
        for cid, lbl, w in heads:
            self._tree.heading(cid, text=lbl)
            self._tree.column(cid, width=w, minwidth=w if cid!="name" else 80,
                               anchor="center" if cid=="chk" else "w", stretch=(cid=="name"))
        vsb = ttk.Scrollbar(left, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(4,0), pady=(0,4))
        vsb.pack(side="left", fill="y", pady=(0,4), padx=(0,4))
        self._tree.bind("<Button-1>",        self._on_click)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<ButtonRelease-1>",  self._on_select)

        # 右: サイドパネル（スクロール対応）
        self._side = ttk.LabelFrame(body, text="  📋 詳細  ")
        self._side.pack(side="left", fill="y", padx=(4,4), pady=(0,4))
        self._side.configure(width=220)
        self._side.pack_propagate(False)

        t = THEMES[_current_theme()]
        # スクロールなしのシンプルなフレーム
        sf = tk.Frame(self._side, bg=t["BG"])
        sf.pack(fill="both", expand=True)
        self._side_canvas = sf   # apply_theme から参照されるため sf を指す
        self._side_frame  = sf

        # 選択中ラベル（tk.Label で bg を直接管理）
        lbl_sel = tk.Label(sf, text="選択中:", font=("Yu Gothic UI",8),
                           bg=t["BG"], fg=t["FG"])
        lbl_sel.pack(anchor="w", padx=8, pady=(8,0))
        self._side_lbl_sel = lbl_sel

        self._side_name = tk.Label(sf, text="—", wraplength=195,
                                    font=("Yu Gothic UI",9,"bold"),
                                    bg=t["BG"], fg=t["FG"], justify="left")
        self._side_name.pack(anchor="w", padx=8, pady=(0,6))

        # Separator を tk.Frame で代替（ttk.Separator は bg 制御が複雑）
        self._side_sep = tk.Frame(sf, height=1, bg=t["BG3"])
        self._side_sep.pack(fill="x", padx=8, pady=4)

        # バージョン
        lbl_ver = tk.Label(sf, text="バージョン:", font=("Yu Gothic UI",10),
                           bg=t["BG"], fg=t["FG"])
        lbl_ver.pack(anchor="w", padx=8, pady=(0,2))
        self._side_lbl_ver = lbl_ver

        self._ver_var   = tk.StringVar(value="最新")
        self._ver_combo = ttk.Combobox(sf, textvariable=self._ver_var,
                                        state="readonly", width=24)
        self._ver_combo.pack(padx=8, pady=(0,2), fill="x")
        self._ver_combo.bind("<<ComboboxSelected>>", self._on_ver_select)
        self._ver_status = tk.Label(sf, text="", fg=t["YEL"],
                                     bg=t["BG"], font=("Yu Gothic UI",8))
        self._ver_status.pack(anchor="w", padx=8, pady=(0,4))
        ttk.Button(sf, text="🔄 バージョン取得",
                    command=self._fetch_versions).pack(padx=8, pady=(0,8), fill="x")

        self._current_iid = None

    def _on_select(self, e):
        rows = self._tree.selection()
        if not rows:
            # selectionが空の場合はクリックした行を取得
            row = self._tree.identify_row(e.y if hasattr(e,'y') else 0)
            if not row: return
        else:
            row = rows[0]
        if row == self._current_iid: return
        self._current_iid = row
        item = next((it for it in self.items if it["filename"] == row), None)
        if not item: return
        name = item.get("display_name") or item.get("name", row)
        self._side_name.config(text=name)
        # 既にバージョン取得済みなら表示
        override = self._ver_overrides.get(row)
        self._ver_combo["values"] = ["最新"]
        self._ver_var.set("最新" if override is None else override)
        self._ver_status.config(text="← 取得ボタンでバージョン一覧を取得")

    def _fetch_versions(self):
        """選択中のModのバージョン一覧をAPIから取得"""
        if not self._current_iid: return
        item = next((it for it in self.items if it["filename"] == self._current_iid), None)
        if not item: return
        if not self._ver_fetch_fn:
            self._ver_status.config(text="バージョン取得非対応", foreground=RED); return

        self._ver_status.config(text="🔄 取得中...", foreground=YEL)
        self._ver_combo.config(state="disabled")

        def _cb(versions):
            """versions: [{"label": "1.21.4 - v2.0", "id": "xxx"}, ...]"""
            labels = ["最新"] + [v["label"] for v in versions]
            self._ver_combo["values"] = labels
            self._ver_combo.config(state="readonly")
            cur = self._ver_overrides.get(self._current_iid)
            if cur:
                matched = next((v["label"] for v in versions if v["id"] == cur), None)
                self._ver_var.set(matched or "最新")
            else:
                self._ver_var.set("最新")
            self._ver_status.config(
                text=f"✅ {len(versions)} 件取得" if versions else "⚠ バージョンなし",
                foreground=GRN if versions else RED)
            self._versions_cache = versions

        self._versions_cache = []
        threading.Thread(target=lambda: self._ver_fetch_fn(item, _cb), daemon=True).start()

    def _on_ver_select(self, e=None):
        if not self._current_iid: return
        label = self._ver_var.get()
        if label == "最新":
            self._ver_overrides.pop(self._current_iid, None)
        else:
            ver_id = next((v["id"] for v in getattr(self, "_versions_cache", [])
                           if v["label"] == label), None)
            self._ver_overrides[self._current_iid] = ver_id
        self._ver_status.config(
            text="✅ 最新でDL" if label == "最新" else f"✅ {label} を選択",
            foreground=GRN)

    def get_version_override(self, filename):
        """指定ファイルのバージョンオーバーライドを返す（Noneなら最新）"""
        return self._ver_overrides.get(filename)

    def populate(self, items):
        for row in self._tree.get_children(): self._tree.delete(row)
        self.items = list(items)
        self._ver_overrides.clear()
        self._current_iid = None
        self._side_name.config(text="—")
        self._ver_combo["values"] = ["最新"]
        self._ver_var.set("最新")
        self._ver_status.config(text="")
        for it in self.items:
            iid     = it["filename"]
            display = it.get("display_name") or it.get("name", iid)
            vals    = (("☑",display,it.get("version","?"),it.get("loader","?"))
                       if self.mr_type==MR_MOD else ("☑",display))
            self._tree.insert("","end", iid=iid, values=vals)
        self._upd_label()

    def add_item(self, item, tag="dep"):
        iid = item["filename"]
        if self._tree.exists(iid): return
        self.items.append(item)
        vals = (("☑",item.get("name",iid),item.get("version",""),item.get("loader",""))
                if self.mr_type==MR_MOD else ("☑",item.get("name",iid)))
        self._tree.insert("","end", iid=iid, values=vals)
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
        # サイドパネル更新
        if row:
            self._tree.selection_set(row)
            self._on_select(e)

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
        except Exception: pass  # Windows専用API。非Windows環境では失敗するが問題なし
        try:
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            ip   = os.path.join(base, "icon.ico")
            self._icon_path = ip if os.path.exists(ip) else None
            if self._icon_path: self.iconbitmap(default=self._icon_path)
        except Exception: self._icon_path = None
        self.geometry("1150x780"); self.configure(bg=BG); self.resizable(True, True)

        cfg = load_config()
        self.target_version = tk.StringVar(value=cfg.get("target_version","1.21.4"))
        saved_loader = cfg.get("target_loader","fabric")
        if saved_loader not in LOADERS: saved_loader = "fabric"
        self.target_loader  = tk.StringVar(value=saved_loader)
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
        # 全体設定
        self.auto_switch_tab  = tk.BooleanVar(value=cfg.get("auto_switch_tab",True))
        self.toast_enabled    = tk.BooleanVar(value=cfg.get("toast_enabled",True))
        self.toast_duration   = tk.IntVar(value=cfg.get("toast_duration",3))
        self.backup_mode      = tk.BooleanVar(value=cfg.get("backup_mode", False))
        self.backup_dir       = tk.StringVar(value=cfg.get("backup_dir", ""))
        self._toast_win       = None   # 現在表示中のトースト
        self._cf_key_showing = False
        self._running = self._cancel_flag = False
        # Mod検索タブ用
        self.search_dl_dir    = tk.StringVar(value=cfg.get("search_dl_dir",""))
        self.search_version   = tk.StringVar(value=cfg.get("search_version", cfg.get("target_version","1.21.4")))
        self.search_loader    = tk.StringVar(value=cfg.get("search_loader", cfg.get("target_loader","fabric")))
        self.search_dl_mode   = tk.StringVar(value=cfg.get("search_dl_mode", cfg.get("dl_mode", DL_BOTH)))
        self.search_auto_deps = tk.BooleanVar(value=cfg.get("search_auto_deps", True))
        self.search_strict_deps = tk.BooleanVar(value=cfg.get("search_strict_deps", False))
        self._theme = cfg.get("theme", "light")
        _apply_theme_globals(self._theme)

        self._apply_style(); self._build_ui(); self._disable_combobox_wheel()

    def _t(self):
        """現在テーマ辞書を返す"""
        return THEMES[self._theme]

    def _tw(self, wlist, widget, *pairs):
        """(color_key, attr) のペアを wlist に一括登録するヘルパー"""
        for color_key, attr in pairs:
            wlist.append((widget, color_key, attr))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._fetch_versions_bg, daemon=True).start()

    def _apply_style(self):
        t = self._t()
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

        # ── 共有プログレスバー（ウィンドウ下部）── 先にpackして残りをNotebookに
        bar = ttk.Frame(self); bar.pack(side="bottom", fill="x", padx=12, pady=(0,8))
        self._progress   = ttk.Progressbar(bar, mode="determinate")
        self._progress.pack(side="left", fill="x", expand=True, padx=(0,10))
        self._prog_label = ttk.Label(bar, text="", width=34)
        self._prog_label.pack(side="left")
        self._cancel_btn = ttk.Button(bar, text="⏹ 中止", command=self._cancel, state="disabled")
        self._cancel_btn.pack(side="left", padx=(8,0))

        # ── 親Notebook（MOD / プラグイン / 全体設定） ──
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True, padx=12, pady=(0,4))

        tab_mod    = ttk.Frame(self._nb)
        tab_plugin = ttk.Frame(self._nb)
        tab_global = ttk.Frame(self._nb)
        self._nb.add(tab_mod,    text=" ⛏ MOD ")
        self._nb.add(tab_plugin, text=" 🔌 プラグイン ")
        self._nb.add(tab_global, text=" 🌐 全体設定 ")

        # ── MOD 子Notebook（設定 / 一覧 / ログ / Mod検索） ──
        self._mod_nb = ttk.Notebook(tab_mod)
        self._mod_nb.pack(fill="both", expand=True)

        t_settings = ttk.Frame(self._mod_nb)
        t_lists    = ttk.Frame(self._mod_nb)
        t_log      = ttk.Frame(self._mod_nb)
        t_search   = ttk.Frame(self._mod_nb)
        self._mod_nb.add(t_settings, text=" ⚙ 設定 ")
        self._mod_nb.add(t_lists,    text=" 📦 一覧 ")
        self._mod_nb.add(t_log,      text=" 📋 ログ ")
        self._mod_nb.add(t_search,   text=" 🔍 Mod検索 ")

        self._build_settings(t_settings)
        self._build_lists(t_lists)
        self._build_log(t_log)
        self._build_mod_search_tab(t_search)

        # プラグイン・全体設定
        self._build_plugin_tab(tab_plugin)
        self._build_global_settings(tab_global)

    # ── MOD 子タブ切替ヘルパー ─────────────────────────────────────
    def _mod_select(self, child_idx):
        """MOD 親タブを前面にしてから子タブを選択するヘルパー"""
        self._nb.select(0)
        self._mod_nb.select(child_idx)

    def _build_global_settings(self, p):
        t = self._t()
        f = ttk.Frame(p); f.pack(fill="both", expand=True, padx=20, pady=16)

        # ── バックアップモード ──────────────────────────────────
        lf0 = ttk.LabelFrame(f, text="💾  バックアップモード"); lf0.pack(fill="x", pady=(0,10))

        chk_row = ttk.Frame(lf0); chk_row.pack(fill="x", padx=10, pady=(8,4))
        ttk.Checkbutton(chk_row, text="バックアップモードを有効にする（元ファイルを上書きせず別フォルダへ出力）",
                         variable=self.backup_mode,
                         command=self._on_backup_mode_toggle).pack(side="left", anchor="w")

        dir_row = ttk.Frame(lf0); dir_row.pack(fill="x", padx=10, pady=(0,4))
        self._backup_dir_lbl = tk.Label(dir_row, text="出力先フォルダ:",
                                         bg=t["BG"], fg=t["FG"], font=("Yu Gothic UI", 10))
        self._backup_dir_lbl.pack(side="left")
        self._backup_dir_entry = ttk.Entry(dir_row, textvariable=self.backup_dir, width=38)
        self._backup_dir_entry.pack(side="left", padx=(6,6))
        self._backup_dir_browse_btn = ttk.Button(dir_row, text="参照",
                                                  command=lambda: self._browse(self.backup_dir))
        self._backup_dir_browse_btn.pack(side="left", padx=(0,6))
        ttk.Button(dir_row, text="✕",
                    command=lambda: self.backup_dir.set(""), width=3).pack(side="left")

        self._backup_note_lbl = tk.Label(
            lf0,
            text="  ℹ  ONの場合: [出力先]/v{バージョン}_{日付}_{時刻}/mods|resourcepacks|shaderpacks|plugins へ保存",
            bg=t["BG"], fg=t["YEL"], font=("Yu Gothic UI", 8), anchor="w", justify="left"
        )
        self._backup_note_lbl.pack(fill="x", padx=10, pady=(0,8))

        self._on_backup_mode_toggle()  # 初期状態を反映

        # 一覧自動移動
        lf1 = ttk.LabelFrame(f, text="📦  一覧タブ"); lf1.pack(fill="x", pady=(0,10))
        ttk.Checkbutton(lf1, text="読み込み完了後に自動で一覧タブへ移動する",
                         variable=self.auto_switch_tab).pack(padx=10, pady=8, anchor="w")

        # トースト通知
        lf2 = ttk.LabelFrame(f, text="🔔  通知"); lf2.pack(fill="x", pady=(0,10))
        ttk.Checkbutton(lf2, text="読み込み完了時にトースト通知を表示する",
                         variable=self.toast_enabled).pack(padx=10, pady=(8,4), anchor="w")
        dur_row = ttk.Frame(lf2); dur_row.pack(fill="x", padx=10, pady=(0,8))
        ttk.Label(dur_row, text="通知の表示時間:").pack(side="left")
        ttk.Spinbox(dur_row, from_=1, to=30, textvariable=self.toast_duration,
                     width=5, state="readonly").pack(side="left", padx=(6,4))
        ttk.Label(dur_row, text="秒  （上限: 30秒）").pack(side="left")

        # GitHub ボタン（画像）
        gh_frame = ttk.Frame(f); gh_frame.pack(fill="x", pady=(20, 0))
        try:
            from PIL import Image, ImageTk
            self._gh_btn_base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            t = THEMES[self._theme]
            ico_name = "GitHub_Lockup_White.ico" if self._theme == "dark" else "GitHub_Lockup_Black.ico"
            pil_img = Image.open(os.path.join(self._gh_btn_base, ico_name))
            target_h = 36
            target_w = int(pil_img.width * target_h / pil_img.height)
            pil_img = pil_img.resize((target_w, target_h), Image.LANCZOS)
            gh_img = ImageTk.PhotoImage(pil_img)
            self._gh_btn = tk.Button(
                gh_frame,
                image=gh_img,
                command=lambda: webbrowser.open("https://github.com/29kiyo/MC-Pack-Updater"),
                bg=t["BG"], activebackground=t["BG2"],
                relief="flat", cursor="hand2",
                bd=0, padx=8, pady=4
            )
            self._gh_btn.image = gh_img  # GC対策
            self._gh_btn.pack()
        except Exception: pass  # 画像読み込み失敗時はボタンを表示しない

    def _show_toast(self, message):
        """アプリ右下にトースト通知を表示する"""
        if not self.toast_enabled.get(): return
        # 既存のトーストを閉じる
        if self._toast_win and self._toast_win.winfo_exists():
            self._toast_win.destroy()

        t = self._t()
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)   # タイトルバーなし
        toast.attributes("-topmost", True)
        toast.configure(bg=t["BG3"])
        if self._icon_path:
            try: toast.iconbitmap(self._icon_path)
            except Exception: pass  # アイコン設定失敗はUIに影響しないため無視
        self._toast_win = toast

        # 内容
        frame = tk.Frame(toast, bg=t["BG2"], relief="solid", bd=1)
        frame.pack(fill="both", expand=True, padx=1, pady=1)

        tk.Label(frame, text="✅ " + message,
                  bg=t["BG2"], fg=t["FG"],
                  font=("Yu Gothic UI",10), wraplength=280,
                  justify="left", padx=12, pady=8).pack(side="left", fill="both", expand=True)
        tk.Button(frame, text="×", bg=t["BG2"], fg=t["FG"],
                   font=("Yu Gothic UI",10), relief="flat", cursor="hand2",
                   command=toast.destroy, padx=6).pack(side="right", anchor="n", pady=4)

        # 位置計算（ウィンドウ右下）
        def _position():
            self.update_idletasks(); toast.update_idletasks()
            wx, wy = self.winfo_x(), self.winfo_y()
            ww, wh = self.winfo_width(), self.winfo_height()
            tw, th = toast.winfo_reqwidth(), toast.winfo_reqheight()
            x = wx + ww - tw - 20
            y = wy + wh - th - 20
            toast.geometry(f"{tw}x{th}+{x}+{y}")
        self.after(10, _position)

        # 自動消去
        secs = max(1, min(30, self.toast_duration.get()))
        self.after(secs * 1000, lambda: toast.destroy() if toast.winfo_exists() else None)

    def _on_backup_mode_toggle(self):
        """バックアップモードON/OFFに応じて出力先UIの活性状態を切り替える"""
        state = "normal" if self.backup_mode.get() else "disabled"
        self._backup_dir_entry.config(state=state)
        self._backup_dir_browse_btn.config(state=state)

    def _get_backup_out_dir(self, mr_type_key):
        """バックアップモード用の出力先サブフォルダパスを返す（親フォルダも作成）"""
        import datetime
        base    = self.backup_dir.get().strip()
        mc_ver  = self.target_version.get()
        now     = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        parent  = os.path.join(base, f"v{mc_ver}_{now}")
        sub_map = {"mod": "mods", "rp": "resourcepacks", "shader": "shaderpacks", "plugin": "plugins"}
        sub     = sub_map.get(mr_type_key, mr_type_key)
        out     = os.path.join(parent, sub)
        os.makedirs(out, exist_ok=True)
        return out

    def _build_settings(self, p):
        t = self._t()
        # 設定タブはスクロール不要のためFrameを使用
        outer = ttk.Frame(p)
        outer.pack(fill="both", expand=True)
        self._settings_canvas = None  # _toggle_themeとの互換用
        f = ttk.Frame(outer)
        f.pack(fill="both", expand=True, padx=2, pady=2)
        # マウスホイールはModタブ（一覧）でのみ有効にする
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
        for lbl, var, load_cmd, upd_cmd in [
            ("🧩 Mods",         self.mods_dir,   self._load_mods,   lambda: self._start_panel(self._mod_panel,    "Mod",          "mod")),
            ("🎨 ResourcePacks", self.rp_dir,     self._load_rp,     lambda: self._start_panel(self._rp_panel,     "ResourcePack", "rp")),
            ("✨ Shaders",       self.shader_dir, self._load_shader, lambda: self._start_panel(self._shader_panel, "Shader",       "shader")),
        ]:
            row = ttk.Frame(lf1); row.pack(fill="x", padx=10, pady=3)
            ttk.Label(row, text=lbl, width=18).pack(side="left")
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=(0,6))
            ttk.Button(row, text="参照",       command=lambda v=var: self._browse(v)).pack(side="left", padx=(0,6))
            ttk.Button(row, text="📂 読み込む", command=load_cmd).pack(side="left", padx=(0,6))
            ttk.Button(row, text="⬇ ダウンロード", command=upd_cmd).pack(side="left", padx=(0,6))
            ttk.Button(row, text="✕",          command=lambda v=var: v.set(""), width=3).pack(side="left")
        # 全て操作ボタン
        all_row = ttk.Frame(lf1); all_row.pack(fill="x", padx=10, pady=(4,8))
        ttk.Button(all_row, text="📂 全て読み込む",        command=self._load_all).pack(side="left", padx=(0,8))
        ttk.Button(all_row, text="🔄 全て一括アップデート", command=self._start_all).pack(side="left")

        # アップデート先＋ダウンロード設定（横並び）
        mid_row = ttk.Frame(f)
        mid_row.pack(fill="x", **PAD)
        mid_row.columnconfigure(0, weight=1)
        mid_row.columnconfigure(1, weight=1)

        # アップデート先（左）
        lf2 = ttk.LabelFrame(mid_row, text="🎯  アップデート先")
        lf2.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        r2a = ttk.Frame(lf2); r2a.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(r2a, text="MCバージョン:").pack(side="left")
        self._ver_cb = ttk.Combobox(r2a, textvariable=self.target_version,
                                     values=MC_VERSIONS_FALLBACK, width=12, state="readonly")
        self._ver_cb.pack(side="left", padx=(4, 6))
        self._ver_status = tk.Label(r2a, text="🔄 取得中...",
                                     fg=t["YEL"], bg=t["BG"],
                                     font=("Yu Gothic UI", 8), anchor="w")
        self._ver_status.pack(side="left")
        self._tk_widgets_settings = getattr(self, "_tk_widgets_settings", [])
        self._tk_widgets_settings.append((self._ver_status, "YEL", "fg"))
        self._tk_widgets_settings.append((self._ver_status, "BG",  "bg"))
        r2b = ttk.Frame(lf2); r2b.pack(fill="x", padx=10, pady=(2, 8))
        ttk.Label(r2b, text="Mod Loader:").pack(side="left")
        self._loader_cb = ttk.Combobox(r2b, textvariable=self.target_loader,
                                        values=LOADERS, width=12, state="readonly")
        self._loader_cb.pack(side="left", padx=(4, 6))
        self._loader_cb.bind("<<ComboboxSelected>>", lambda _: self._filter_versions())
        ttk.Button(r2b, text="✕ リセット",
                    command=lambda: (self.target_version.set(""), self.target_loader.set(""))).pack(side="left")

        # ダウンロード設定（右）
        lf3 = ttk.LabelFrame(mid_row, text="🌐  ダウンロード設定")
        lf3.grid(row=0, column=1, sticky="nsew")
        r3 = ttk.Frame(lf3); r3.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(r3, text="モード:").pack(side="left")
        self._dl_mode_cb = ttk.Combobox(r3, textvariable=self.dl_mode, values=DL_MODES, width=20, state="readonly")
        self._dl_mode_cb.pack(side="left", padx=(4, 0))
        self._dl_mode_cb.bind("<<ComboboxSelected>>", lambda _: self._update_mode_ui())
        self._mode_desc = tk.Label(lf3, text="",
                                    fg=t["YEL"], bg=t["BG"],
                                    font=("Yu Gothic UI", 9),
                                    wraplength=260, justify="left", anchor="w")
        self._mode_desc.pack(anchor="w", padx=10, pady=(2, 4))
        self._tk_widgets_settings.append((self._mode_desc, "YEL", "fg"))
        self._tk_widgets_settings.append((self._mode_desc, "BG",  "bg"))
        ttk.Separator(lf3, orient="horizontal").pack(fill="x", padx=10, pady=2)
        r4 = ttk.Frame(lf3); r4.pack(fill="x", padx=10, pady=(4, 4))
        ttk.Label(r4, text="CurseForge APIキー:").pack(side="left")
        self._cf_entry = ttk.Entry(r4, textvariable=self.cf_api_key, show="*", width=24)
        self._cf_entry.pack(side="left", padx=(6, 4))
        self._cf_show_btn = ttk.Button(r4, text="表示", command=self._toggle_cf_show, width=4)
        self._cf_show_btn.pack(side="left", padx=(0, 4))
        ttk.Button(r4, text="取得方法 ↗", command=self._show_api_guide).pack(side="left")
        self._update_mode_ui()

        # オプション＋注意（横並び）
        bottom_row = ttk.Frame(f)
        bottom_row.pack(fill="x", **PAD)
        bottom_row.columnconfigure(0, weight=1)
        bottom_row.columnconfigure(1, weight=1)

        lf4 = ttk.LabelFrame(bottom_row, text="⚙  オプション")
        lf4.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        for txt, var in [
            ("アップデート後に古いファイルを削除する",                    self.delete_old),
            ("ダウンロード失敗したファイルを削除する（壊れたファイル除去）", self.delete_failed),
            ("前提Modが足りなければ自動でダウンロードする",               self.auto_deps),
            ("前提Modのバージョンを厳密に指定する（不安定な場合はOFF）",   self.strict_deps),
        ]:
            ttk.Checkbutton(lf4, text=txt, variable=var).pack(padx=10, pady=2, anchor="w")

        lf5 = ttk.LabelFrame(bottom_row, text="⚠  注意")
        lf5.grid(row=0, column=1, sticky="nsew")
        warn_msg = (
            "起動構成フォルダを直接読み込んで使用できますが、"
            "検出された構成がそのまま正常に動作するとは限りません。\n\n"
            "Modのバージョン・ローダーの種類・依存関係によっては"
            "アップデート後に起動しなくなる場合があります。\n\n"
            "実行前に必ずバックアップを取り、自己責任でご使用ください。"
        )
        self._settings_warn_label = tk.Label(
            lf5, text=warn_msg,
            justify="left", anchor="nw",
            fg=t["RED"], bg=t["BG"],
            font=("Yu Gothic UI", 9),
        )
        self._settings_warn_label.pack(padx=10, pady=8, anchor="nw", fill="x", expand=True)
        # 枠幅が変わったら wraplength を自動追従
        def _update_warn_wrap(e, lbl=self._settings_warn_label):
            lbl.configure(wraplength=max(100, e.width - 20))
        lf5.bind("<Configure>", _update_warn_wrap)

        ttk.Frame(f, height=10).pack()

    def _build_lists(self, p):
        inner_nb = ttk.Notebook(p)
        inner_nb.pack(fill="both", expand=True)
        self._inner_nb = inner_nb

        for attr, mr_type, lbl, log_key, load_fn, upd_fn, export_key in [
            ("_mod_panel",    MR_MOD,   "🧩 Mod",         "mod",    self._load_mods,   lambda: self._start_panel(self._mod_panel,    "Mod",          "mod"),    "mod"),
            ("_rp_panel",     MR_RP,    "🎨 ResourcePack", "rp",     self._load_rp,     lambda: self._start_panel(self._rp_panel,     "ResourcePack", "rp"),     "resourcepack"),
            ("_shader_panel", MR_SHADE, "✨ Shader",        "shader", self._load_shader, lambda: self._start_panel(self._shader_panel, "Shader",       "shader"), "shader"),
        ]:
            tab = ttk.Frame(inner_nb)
            inner_nb.add(tab, text=f" {lbl} ")

            panel = FileListPanel(tab, mr_type,
                                   load_fn=load_fn,
                                   update_fn=upd_fn,
                                   ver_fetch_fn=self._make_ver_fetch_fn(mr_type))
            panel.pack(fill="both", expand=True)
            setattr(self, attr, panel)

            # エクスポートボタン（タブ下部）
            bar = ttk.Frame(tab)
            bar.pack(fill="x", padx=4, pady=(0, 4))
            ttk.Button(bar, text="📤 リスト出力",
                       command=lambda p=panel, k=export_key: self._export_list(p, k),
                       width=11).pack(side="left")


    def _make_ver_fetch_fn(self, mr_type):
        """バージョン取得関数を生成して返す"""
        def _fetch(item, callback):
            mc_ver = self.target_version.get()
            loader = self.target_loader.get()
            name   = item.get("name", item["filename"])
            mod_id = item.get("mod_id", "")
            path   = item.get("path")
            try:
                sha1 = sha1_file(path) if path and os.path.exists(path) else None
                pid  = mr_find_project(sha1, mod_id, name, mr_type)
                if not pid:
                    self.after(0, lambda: callback([]))
                    return
                # RP/Shaderはloaderなし
                p = {"game_versions": json.dumps([mc_ver])}
                if mr_type == MR_MOD: p["loaders"] = json.dumps([loader])
                versions = http_get(
                    f"{MODRINTH_API}/project/{pid}/version?{urllib.parse.urlencode(p)}")
                result = [{"label": f"{v.get('version_number','?')}  [{v.get('game_versions',['?'])[-1]}]",
                           "id": v["id"]} for v in versions]
                self.after(0, lambda r=result: callback(r))
            except Exception:  # バージョン取得失敗時は空リストで返す
                self.after(0, lambda: callback([]))
        return _fetch

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
        def _do():
            at_bottom = box.yview()[1] >= 0.999
            box.insert("end", msg + "\n", tag)
            if at_bottom:
                box.see("end")
        self.after(0, _do)

    def _set_status(self, msg):
        def _do():
            self._prog_label.config(text=msg)
        self.after(0, _do)

    def _set_progress(self, v, maximum=None):
        def _do():
            if maximum is not None:
                self._progress.configure(maximum=maximum)
            self._progress.configure(value=v)
        self.after(0, _do)

    # ══════════════════════════════════════════════════════════════
    # Mod検索タブ（子タブ構成：設定 / 一覧 / ログ）
    # ══════════════════════════════════════════════════════════════
    def _build_mod_search_tab(self, p):
        """「🔍 Mod検索」タブ ― 子Notebookで 設定/一覧/ログ に分割"""
        self._search_tk_widgets  = []
        self._search_running     = False
        self._search_cancel_flag = False
        self._search_items       = []   # {"iid","name","status","ver_override":None}
        self._search_ver_cache   = {}   # iid -> [{"label","id"}, ...]
        self._search_cur_iid     = None

        # 子Notebook
        snb = ttk.Notebook(p)
        snb.pack(fill="both", expand=True)
        self._search_nb = snb

        t_cfg = ttk.Frame(snb); snb.add(t_cfg, text=" ⚙ 設定 ")
        t_lst = ttk.Frame(snb); snb.add(t_lst, text=" 📋 一覧 ")
        t_log = ttk.Frame(snb); snb.add(t_log, text=" 📄 ログ ")

        self._search_build_settings(t_cfg)
        self._search_build_list(t_lst)
        self._search_build_log(t_log)

    # ── 設定タブ ──────────────────────────────────────────────────
    def _search_build_settings(self, p):
        t = self._t()
        f = ttk.Frame(p); f.pack(fill="both", expand=True, padx=2, pady=2)
        PAD = dict(padx=14, pady=(0,8))

        # ── Mod名入力 / ファイル読み込み ──
        lf_input = ttk.LabelFrame(f, text="🔍  Mod名入力 / ファイル読み込み")
        lf_input.pack(fill="x", padx=14, pady=(8,8))

        # プレースホルダーテキスト（入力欄の上に説明として表示する別ラベル方式）
        ph_lbl = tk.Label(lf_input,
            text=(
                "【入力方法】 Mod名（またはModrinth/CurseForgeのスラッグID）をカンマ（,）または改行で区切って入力してください。\n"
                "  ・Mod名にスペースが含まれる場合は正確に入力してください。\n"
                "    例: Fabric API → 「Fabric API」 (スペースあり) ／ sodium → 「sodium」 (スペースなし)\n"
                "  ・スラッグIDが分かる場合はそちらが確実です。\n"
                "    例: fabric-api, sodium, lithium, iris, modmenu\n"
                "  ・ファイルから読み込む場合は下のボタンを使用してください。"
            ),
            fg=t["ACC"], bg=t["BG2"],
            font=("Yu Gothic UI",8), anchor="w", justify="left",
            padx=8, pady=4)
        ph_lbl.pack(fill="x", padx=8, pady=(6,2))
        self._tw(self._search_tk_widgets, (ph_lbl, "ACC", "fg"))
        self._tw(self._search_tk_widgets, (ph_lbl, "BG2", "bg"))

        self._search_input = scrolledtext.ScrolledText(
            lf_input,
            bg=t["LOG"], fg=t["FG"],
            selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
            insertbackground=t["FG"],
            font=("Yu Gothic UI",10), relief="flat", height=4, wrap="word"
        )
        self._search_input.frame.configure(background=t["LOG"])
        self._tw(self._search_tk_widgets, (self._search_input.frame, "LOG", "bg"))
        self._search_input.pack(fill="x", padx=8, pady=(0,4))
        self._search_ph_active = False  # 専用ラベル方式なのでプレースホルダーは使わない

        file_row = ttk.Frame(lf_input); file_row.pack(fill="x", padx=8, pady=(0,4))
        ttk.Button(file_row, text="📄 .txt/.csv 読込", command=self._search_load_txt).pack(side="left", padx=(0,4))
        ttk.Button(file_row, text="📋 .json 読込",     command=self._search_load_json).pack(side="left", padx=(0,4))
        ttk.Button(file_row, text="🗑 クリア",          command=self._search_clear_input).pack(side="left", padx=(0,4))
        ttk.Button(file_row, text="📋 リストに追加",    command=self._search_add_to_list).pack(side="left")

        note_lbl = tk.Label(lf_input,
            text=(
                "  ℹ ファイル対応: .txt（カンマ区切り / 1行1Mod）/ .csv（同左）"
                " / .json（文字列配列 / {\"mods\":[...]} / オブジェクトのキーをMod名として使用）"
            ),
            fg=t["YEL"], bg=t["BG"], font=("Yu Gothic UI",8), anchor="w", justify="left")
        note_lbl.pack(fill="x", padx=8, pady=(0,6))
        self._tw(self._search_tk_widgets, (note_lbl, "YEL", "fg"))
        self._tw(self._search_tk_widgets, (note_lbl, "BG",  "bg"))

        # ── ダウンロード設定 ──
        mid_row = ttk.Frame(f); mid_row.pack(fill="x", **PAD)
        mid_row.columnconfigure(0, weight=1); mid_row.columnconfigure(1, weight=1)

        lf_dl = ttk.LabelFrame(mid_row, text="🎯  ダウンロード先・バージョン")
        lf_dl.grid(row=0, column=0, sticky="nsew", padx=(0,6))

        # 対象タイプ
        r_type = ttk.Frame(lf_dl); r_type.pack(fill="x", padx=10, pady=(8,2))
        ttk.Label(r_type, text="対象タイプ:").pack(side="left")
        self._search_mr_type = tk.StringVar(value="Mod")
        for val, lbl in [("Mod","🧩 Mod"), ("ResourcePack","🎨 ResourcePack"), ("Shader","✨ Shader")]:
            ttk.Radiobutton(r_type, text=lbl, variable=self._search_mr_type,
                            value=val).pack(side="left", padx=(6,0))

        r_ver = ttk.Frame(lf_dl); r_ver.pack(fill="x", padx=10, pady=(8,2))
        ttk.Label(r_ver, text="MCバージョン:").pack(side="left")
        self._search_ver_cb = ttk.Combobox(r_ver, textvariable=self.search_version,
                                            values=MC_VERSIONS_FALLBACK, width=11, state="readonly")
        self._search_ver_cb.pack(side="left", padx=(4,4))
        self._search_ver_status = tk.Label(r_ver, text="🔄",
                                            fg=t["YEL"], bg=t["BG"], font=("Yu Gothic UI",8))
        self._search_ver_status.pack(side="left")
        self._tw(self._search_tk_widgets, (self._search_ver_status, "YEL", "fg"))
        self._tw(self._search_tk_widgets, (self._search_ver_status, "BG",  "bg"))

        r_ldr = ttk.Frame(lf_dl); r_ldr.pack(fill="x", padx=10, pady=(2,4))
        ttk.Label(r_ldr, text="Mod Loader:").pack(side="left")
        self._search_loader_cb = ttk.Combobox(r_ldr, textvariable=self.search_loader,
                                               values=LOADERS, width=11, state="readonly")
        self._search_loader_cb.pack(side="left", padx=(4,0))

        r_dir = ttk.Frame(lf_dl); r_dir.pack(fill="x", padx=10, pady=(0,4))
        ttk.Label(r_dir, text="保存先フォルダ:").pack(side="left")
        ttk.Entry(r_dir, textvariable=self.search_dl_dir).pack(side="left", padx=(4,4), fill="x", expand=True)
        ttk.Button(r_dir, text="参照", command=lambda: self._browse(self.search_dl_dir), width=4).pack(side="left", padx=(0,4))
        ttk.Button(r_dir, text="✕", command=lambda: self.search_dl_dir.set(""), width=3).pack(side="left")

        lf_mode = ttk.LabelFrame(mid_row, text="🌐  ダウンロードモード")
        lf_mode.grid(row=0, column=1, sticky="nsew")

        r_mode = ttk.Frame(lf_mode); r_mode.pack(fill="x", padx=10, pady=(8,2))
        ttk.Label(r_mode, text="モード:").pack(side="left")
        self._search_dl_mode_cb = ttk.Combobox(r_mode, textvariable=self.search_dl_mode,
                                                values=DL_MODES, width=20, state="readonly")
        self._search_dl_mode_cb.pack(side="left", padx=(4,0))
        self._search_dl_mode_cb.bind("<<ComboboxSelected>>", lambda _: self._search_update_mode_ui())
        self._search_mode_desc = tk.Label(lf_mode, text="", fg=t["YEL"], bg=t["BG"],
                                           font=("Yu Gothic UI",9), wraplength=260,
                                           justify="left", anchor="w")
        self._search_mode_desc.pack(anchor="w", padx=10, pady=(0,4))
        self._tw(self._search_tk_widgets, (self._search_mode_desc, "YEL", "fg"))
        self._tw(self._search_tk_widgets, (self._search_mode_desc, "BG",  "bg"))
        self._search_update_mode_ui()

        # ── オプション ──
        bot_row = ttk.Frame(f); bot_row.pack(fill="x", **PAD)
        bot_row.columnconfigure(0, weight=1); bot_row.columnconfigure(1, weight=1)

        lf_opt = ttk.LabelFrame(bot_row, text="⚙  オプション")
        lf_opt.grid(row=0, column=0, sticky="nsew", padx=(0,6))
        ttk.Checkbutton(lf_opt,
            text="前提Modが足りなければ自動でダウンロードする",
            variable=self.search_auto_deps).pack(padx=10, pady=(6,2), anchor="w")
        ttk.Checkbutton(lf_opt,
            text="前提Modのバージョンを厳密に指定する（不安定な場合はOFF）",
            variable=self.search_strict_deps).pack(padx=10, pady=(0,8), anchor="w")

        lf_warn = ttk.LabelFrame(bot_row, text="⚠  注意")
        lf_warn.grid(row=0, column=1, sticky="nsew")
        warn_msg = (
            "ここではMod名（またはID）を直接指定してModrinth / CurseForgeから\n"
            "ダウンロードします。名前が完全一致しない場合、意図しないModが\n"
            "DLされることがあります。前提Modは自動取得しますが、バージョン・\n"
            "Loaderの互換性は保証されません。\n"
            "必ずバックアップを取ってから使用してください。"
        )
        self._search_warn_label = tk.Label(
            lf_warn, text=warn_msg,
            justify="left", anchor="nw",
            fg=t["RED"], bg=t["BG"],
            font=("Yu Gothic UI",9))
        self._search_warn_label.pack(padx=10, pady=8, fill="x", expand=True, anchor="nw")
        self._tw(self._search_tk_widgets, (self._search_warn_label, "RED", "fg"))
        self._tw(self._search_tk_widgets, (self._search_warn_label, "BG",  "bg"))
        def _upd_wrap(e, lbl=self._search_warn_label):
            lbl.configure(wraplength=max(100, e.width - 20))
        lf_warn.bind("<Configure>", _upd_wrap)

        ttk.Frame(f, height=8).pack()

    # ── 一覧タブ ──────────────────────────────────────────────────
    def _search_build_list(self, p):
        t = self._t()

        # ツールバー
        tb = ttk.Frame(p); tb.pack(fill="x", padx=6, pady=(6,2))
        for text, w, cmd in [("全選択",6,lambda: self._search_sel_all(True)),
                               ("全解除",6,lambda: self._search_sel_all(False))]:
            ttk.Button(tb, text=text, width=w, command=cmd).pack(side="left", padx=(0,3))
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=(0,6), pady=2)
        ttk.Button(tb, text="📋 リストに追加", command=self._search_add_to_list).pack(side="left", padx=(0,3))
        ttk.Button(tb, text="🗑 選択削除",     command=self._search_remove_selected).pack(side="left", padx=(0,3))
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=(0,6), pady=2)
        ttk.Button(tb, text="⬇ 選択をDL",     command=self._search_start_download).pack(side="left")
        self._search_sel_label = ttk.Label(tb, text="0 / 0 件", width=12, anchor="e")
        self._search_sel_label.pack(side="right", padx=4)

        # 左右分割
        body = ttk.Frame(p); body.pack(fill="both", expand=True)

        # 左：Treeview
        left = ttk.Frame(body); left.pack(side="left", fill="both", expand=True)
        cols = ("chk","name","status")
        self._search_tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="none")
        self._search_tree.heading("chk",    text="✔")
        self._search_tree.heading("name",   text="Mod名")
        self._search_tree.heading("status", text="状態")
        self._search_tree.column("chk",    width=36,  minwidth=36,  anchor="center", stretch=False)
        self._search_tree.column("name",   width=240, minwidth=80,  anchor="w",      stretch=True)
        self._search_tree.column("status", width=160, minwidth=60,  anchor="w",      stretch=False)
        vsb = ttk.Scrollbar(left, orient="vertical", command=self._search_tree.yview)
        self._search_tree.configure(yscrollcommand=vsb.set)
        self._search_tree.pack(side="left", fill="both", expand=True, padx=(4,0), pady=(0,4))
        vsb.pack(side="left", fill="y", pady=(0,4), padx=(0,4))
        self._search_tree.bind("<Button-1>",        self._search_on_click)
        self._search_tree.bind("<<TreeviewSelect>>", self._search_on_select)
        self._search_tree.bind("<ButtonRelease-1>",  self._search_on_select)

        # 右：サイドパネル（FileListPanel と同じ構成）
        side = ttk.LabelFrame(body, text="  📋 詳細  ")
        side.pack(side="left", fill="y", padx=(4,4), pady=(0,4))
        side.configure(width=220); side.pack_propagate(False)

        sf = tk.Frame(side, bg=t["BG"])
        sf.pack(fill="both", expand=True)
        self._search_side_canvas = sf
        self._search_side_frame  = sf
        self._tw(self._search_tk_widgets, (sf, "BG", "bg"))

        lbl_sel = tk.Label(sf, text="選択中:", font=("Yu Gothic UI",8),
                           bg=t["BG"], fg=t["FG"])
        lbl_sel.pack(anchor="w", padx=8, pady=(8,0))
        self._tw(self._search_tk_widgets, (lbl_sel, "BG", "bg"))
        self._tw(self._search_tk_widgets, (lbl_sel, "FG", "fg"))

        self._search_side_name = tk.Label(sf, text="—", wraplength=195,
                                           font=("Yu Gothic UI",9,"bold"),
                                           bg=t["BG"], fg=t["FG"], justify="left")
        self._search_side_name.pack(anchor="w", padx=8, pady=(0,6))
        self._tw(self._search_tk_widgets, (self._search_side_name, "BG", "bg"))
        self._tw(self._search_tk_widgets, (self._search_side_name, "FG", "fg"))

        self._search_side_sep = tk.Frame(sf, height=1, bg=t["BG3"])
        self._search_side_sep.pack(fill="x", padx=8, pady=4)
        self._tw(self._search_tk_widgets, (self._search_side_sep, "BG3", "bg"))

        lbl_ver = tk.Label(sf, text="バージョン:", font=("Yu Gothic UI",10),
                           bg=t["BG"], fg=t["FG"])
        lbl_ver.pack(anchor="w", padx=8, pady=(0,2))
        self._tw(self._search_tk_widgets, (lbl_ver, "BG", "bg"))
        self._tw(self._search_tk_widgets, (lbl_ver, "FG", "fg"))

        self._search_ver_var   = tk.StringVar(value="最新")
        self._search_ver_combo = ttk.Combobox(sf, textvariable=self._search_ver_var,
                                               state="readonly", width=24)
        self._search_ver_combo.pack(padx=8, pady=(0,2), fill="x")
        self._search_ver_combo.bind("<<ComboboxSelected>>", self._search_on_ver_select)

        self._search_ver_side_status = tk.Label(sf, text="", fg=t["YEL"],
                                                 bg=t["BG"], font=("Yu Gothic UI",8))
        self._search_ver_side_status.pack(anchor="w", padx=8, pady=(0,4))
        self._tw(self._search_tk_widgets, (self._search_ver_side_status, "BG", "bg"))

        ttk.Button(sf, text="🔄 バージョン取得",
                   command=self._search_fetch_versions).pack(padx=8, pady=(0,8), fill="x")

    # ── ログタブ ──────────────────────────────────────────────────
    def _search_build_log(self, p):
        t = self._t()
        self._search_log_box = scrolledtext.ScrolledText(
            p,
            bg=t["LOG"], fg=t["FG"],
            selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
            insertbackground=t["FG"],
            font=("Consolas",9), relief="flat", wrap="word"
        )
        self._search_log_box.frame.configure(background=t["LOG"])
        self._search_log_box.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, color in [("ok",t["GRN"]),("err",t["RED"]),("info",t["ACC"]),("warn",t["YEL"])]:
            self._search_log_box.tag_config(tag, foreground=color)
        ttk.Button(p, text="クリア",
                   command=lambda: self._search_log_box.delete("1.0","end")).pack(pady=(0,8))

    # ── Mod検索タブ ヘルパー群 ─────────────────────────────────────

    def _search_update_mode_ui(self):
        mode = self.search_dl_mode.get()
        desc = {DL_BOTH:     "Modrinthで検索 → なければCurseForgeも",
                DL_CF_FIRST: "CurseForgeで検索 → なければModrinthも（APIキー必須）",
                DL_MR:       "Modrinthのみ（APIキー不要）",
                DL_CF:       "CurseForgeのみ（APIキー必須）"}.get(mode,"")
        self._search_mode_desc.config(text=f"  ℹ {desc}")

    def _search_log(self, msg, tag=""):
        def _do():
            at_bottom = self._search_log_box.yview()[1] >= 0.999
            self._search_log_box.insert("end", msg + "\n", tag)
            if at_bottom: self._search_log_box.see("end")
        self.after(0, _do)

    def _search_set_status(self, msg):
        # ウィンドウ下部の共有ラベルを使う
        self._set_status(msg)

    def _search_set_progress(self, v, maximum=None):
        # ウィンドウ下部の共有プログレスバーを使う
        self._set_progress(v, maximum)

    def _search_do_cancel(self):
        # 共有の _cancel を呼ぶことで _search_cancel_flag・_cancel_flag 両方を立てる
        self._cancel()

    # ── 入力エリア操作 ──

    def _search_clear_input(self):
        self._search_input.delete("1.0","end")

    def _search_get_raw_text(self):
        return self._search_input.get("1.0","end").strip()

    def _parse_mod_names(self, text):
        parts = re.split(r"[,\n]", text)
        return [p.strip() for p in parts if p.strip()]

    def _search_load_txt(self):
        path = filedialog.askopenfilename(
            title="テキスト/CSVファイルを選択",
            filetypes=[("テキスト/CSV","*.txt *.csv"),("すべて","*.*")])
        if not path: return
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                raw = f.read()
            self._search_append_names(self._parse_mod_names(raw), path)
        except Exception as e:
            messagebox.showerror("読込エラー", str(e))

    def _search_load_json(self):
        """JSON対応: 配列 / {"mods":[...]} / オブジェクトキーをMod名として使用"""
        path = filedialog.askopenfilename(
            title="JSONファイルを選択",
            filetypes=[("JSON","*.json"),("すべて","*.*")])
        if not path: return
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                data = json.load(f)
            names = []
            if isinstance(data, list):
                names = [str(x).strip() for x in data if isinstance(x, str) and x.strip()]
            elif isinstance(data, dict):
                for key in ("mods","modlist","mods_list","modIds","mod_ids"):
                    if key in data and isinstance(data[key], list):
                        names = [str(x).strip() for x in data[key] if isinstance(x, str) and str(x).strip()]
                        break
                else:
                    names = [str(k).strip() for k in data.keys() if str(k).strip()]
            if not names:
                messagebox.showinfo("情報","Mod名が見つかりませんでした"); return
            self._search_append_names(names, path)
        except Exception as e:
            messagebox.showerror("読込エラー", str(e))

    def _search_append_names(self, names, source_path):
        if not names:
            messagebox.showinfo("情報","Mod名が見つかりませんでした"); return
        existing = self._search_get_raw_text()
        sep = ", " if existing else ""
        self._search_input.insert("end", sep + ", ".join(names))
        self._search_log(f"📄 {os.path.basename(source_path)} から {len(names)} 件読み込み", "info")

    # ── 一覧タブ操作 ──

    def _search_add_to_list(self):
        raw = self._search_get_raw_text()
        if not raw:
            messagebox.showinfo("情報","Mod名を入力してください"); return
        names = self._parse_mod_names(raw)
        if not names:
            messagebox.showinfo("情報","Mod名が見つかりませんでした"); return
        # 既存リストをクリアしてから追加
        for iid in self._search_tree.get_children():
            self._search_tree.delete(iid)
        self._search_items.clear()
        self._search_ver_cache.clear()
        self._search_cur_iid = None
        self._search_side_name.config(text="—")
        self._search_ver_var.set("最新")
        self._search_ver_combo["values"] = ["最新"]
        self._search_ver_side_status.config(text="")
        added = 0
        for n in names:
            iid = f"srch_{added}_{n}"
            self._search_items.append({"iid":iid,"name":n,"status":"待機中","ver_override":None})
            self._search_tree.insert("","end", iid=iid, values=("☑", n, "待機中"))
            added += 1
        self._search_upd_label()
        if added:
            self._search_log(f"✅ {added} 件をリストに追加しました", "ok")
            self._show_toast(f"Mod検索: {added} 件を一覧に追加しました")
            # 一覧子タブへ移動
            self._search_nb.select(1)
            # 全体設定の「自動タブ移動」がONなら MOD親タブ内のMod検索(子3)へ移動
            if hasattr(self, "auto_switch_tab") and self.auto_switch_tab.get():
                self._mod_select(3)
        else:
            self._search_log("⚠ 追加するMod名がありませんでした", "warn")

    def _search_remove_selected(self):
        to_rm = [iid for iid in self._search_tree.get_children()
                 if self._search_tree.set(iid,"chk") == "☑"]
        for iid in to_rm:
            self._search_tree.delete(iid)
            self._search_items = [it for it in self._search_items if it["iid"] != iid]
            self._search_ver_cache.pop(iid, None)
        if self._search_cur_iid in to_rm:
            self._search_cur_iid = None
            self._search_side_name.config(text="—")
            self._search_ver_var.set("最新")
            self._search_ver_combo["values"] = ["最新"]
            self._search_ver_side_status.config(text="")
        self._search_upd_label()

    def _search_sel_all(self, v):
        mark = "☑" if v else "☐"
        for row in self._search_tree.get_children():
            self._search_tree.set(row, "chk", mark)
        self._search_upd_label()

    def _search_on_click(self, e):
        row = self._search_tree.identify_row(e.y)
        if row and self._search_tree.identify_column(e.x) == "#1":
            cur = self._search_tree.set(row,"chk")
            self._search_tree.set(row,"chk","☑" if cur=="☐" else "☐")
            self._search_upd_label()
        if row:
            self._search_tree.selection_set(row)
            self._search_on_select(e)

    def _search_on_select(self, e=None):
        rows = self._search_tree.selection()
        if not rows: return
        row = rows[0]
        if row == self._search_cur_iid: return
        self._search_cur_iid = row
        item = next((it for it in self._search_items if it["iid"]==row), None)
        if not item: return
        self._search_side_name.config(text=item["name"])
        cached = self._search_ver_cache.get(row, [])
        labels = ["最新"] + [v["label"] for v in cached]
        self._search_ver_combo["values"] = labels
        override = item.get("ver_override")
        if override:
            matched = next((v["label"] for v in cached if v["id"]==override), None)
            self._search_ver_var.set(matched or "最新")
        else:
            self._search_ver_var.set("最新")
        if cached:
            self._search_ver_side_status.config(
                text=f"✅ {len(cached)} 件取得済み",
                fg=THEMES[self._theme]["GRN"])
        else:
            self._search_ver_side_status.config(
                text="← 取得ボタンでバージョン一覧を取得",
                fg=THEMES[self._theme]["FG"])

    def _search_upd_label(self):
        rows = self._search_tree.get_children()
        sel  = sum(1 for r in rows if self._search_tree.set(r,"chk")=="☑")
        self._search_sel_label.config(text=f"{sel} / {len(rows)} 件選択")

    def _search_set_item_status(self, iid, status):
        def _do():
            if not self._search_tree.exists(iid): return
            item = next((it for it in self._search_items if it["iid"]==iid), None)
            if item: item["status"] = status
            self._search_tree.item(iid, values=(
                self._search_tree.set(iid,"chk"),
                self._search_tree.set(iid,"name"),
                status))
        self.after(0, _do)

    # ── サイドパネル バージョン取得 ──

    def _search_fetch_versions(self):
        if not self._search_cur_iid: return
        item = next((it for it in self._search_items if it["iid"]==self._search_cur_iid), None)
        if not item: return
        t = self._t()
        self._search_ver_side_status.config(text="🔄 取得中...", fg=t["YEL"])
        self._search_ver_combo.config(state="disabled")

        iid    = self._search_cur_iid
        name   = item["name"]
        mc_ver = self.search_version.get()
        loader = self.search_loader.get()
        # 現在選択中のタイプを取得
        type_map = {"Mod": MR_MOD, "ResourcePack": MR_RP, "Shader": MR_SHADE}
        mr_type  = type_map.get(self._search_mr_type.get(), MR_MOD)

        def _fetch():
            results = []
            try:
                # mr_find_project で名前→スラッグ検索→ハッシュの順で探す
                # （updaterと同じ経路で一致率を上げる）
                pid = mr_find_project(None, name, name, mr_type)
                if not pid:
                    # スラッグとして直接試みる
                    try:
                        pid = http_get(f"{MODRINTH_API}/project/{name}").get("id")
                    except Exception:
                        pass
                if pid:
                    p = {"game_versions": json.dumps([mc_ver])}
                    if mr_type == MR_MOD:
                        p["loaders"] = json.dumps([loader])
                    vs = http_get(f"{MODRINTH_API}/project/{pid}/version?{urllib.parse.urlencode(p)}")
                    results = [{"label": f"{v.get('version_number','?')}  [{v.get('game_versions',['?'])[-1]}]",
                                "id": v["id"]} for v in vs]
            except Exception:
                pass
            self.after(0, lambda r=results: self._search_ver_cb_done(iid, r))

        threading.Thread(target=_fetch, daemon=True).start()

    def _search_ver_cb_done(self, iid, results):
        t = self._t()
        self._search_ver_cache[iid] = results
        labels = ["最新"] + [v["label"] for v in results]
        self._search_ver_combo["values"] = labels
        self._search_ver_combo.config(state="readonly")
        item = next((it for it in self._search_items if it["iid"]==iid), None)
        override = item.get("ver_override") if item else None
        if override:
            matched = next((v["label"] for v in results if v["id"]==override), None)
            self._search_ver_var.set(matched or "最新")
        else:
            self._search_ver_var.set("最新")
        if results:
            self._search_ver_side_status.config(text=f"✅ {len(results)} 件取得", fg=t["GRN"])
        else:
            self._search_ver_side_status.config(text="⚠ バージョンなし", fg=t["RED"])

    def _search_on_ver_select(self, e=None):
        if not self._search_cur_iid: return
        label = self._search_ver_var.get()
        item  = next((it for it in self._search_items if it["iid"]==self._search_cur_iid), None)
        if not item: return
        t = self._t()
        if label == "最新":
            item["ver_override"] = None
            self._search_ver_side_status.config(text="✅ 最新でDL", fg=t["GRN"])
        else:
            cached = self._search_ver_cache.get(self._search_cur_iid, [])
            ver = next((v for v in cached if v["label"]==label), None)
            item["ver_override"] = ver["id"] if ver else None
            self._search_ver_side_status.config(text=f"✅ {label} を選択", fg=t["GRN"])

    # ── ダウンロード ──

    def _search_start_download(self):
        selected = [it for it in self._search_items
                    if self._search_tree.exists(it["iid"])
                    and self._search_tree.set(it["iid"],"chk") == "☑"]
        if not selected:
            messagebox.showinfo("情報","ダウンロードするアイテムを選択してください"); return
        out_dir = self.search_dl_dir.get().strip()
        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showerror("エラー","有効な保存先フォルダを指定してください"); return
        mode = self.search_dl_mode.get()
        if mode in (DL_BOTH, DL_CF_FIRST, DL_CF) and not self.cf_api_key.get().strip():
            messagebox.showerror("エラー",
                "CurseForgeを使用するにはAPIキーが必要です\n設定タブでAPIキーを入力してください"); return
        if self._search_running:
            messagebox.showwarning("実行中","現在ダウンロード中です"); return
        # 対象タイプを解決
        type_map = {
            "Mod":          (MR_MOD,   CF_MOD),
            "ResourcePack": (MR_RP,    CF_RP),
            "Shader":       (MR_SHADE, CF_SHADE),
        }
        mr_type, cf_class = type_map.get(self._search_mr_type.get(), (MR_MOD, CF_MOD))
        self._search_running     = True
        self._search_cancel_flag = False
        self._search_set_progress(0, len(selected))
        self.after(0, lambda: self._cancel_btn.config(state="normal"))
        self._mod_select(3)          # MOD親タブ内のMod検索へ
        self._search_nb.select(2)    # さらにログ子タブへ
        threading.Thread(
            target=self._search_worker,
            args=(selected, out_dir, self.search_version.get(),
                  self.search_loader.get(), mode, self.cf_api_key.get().strip(),
                  mr_type, cf_class),
            daemon=True).start()

    def _search_worker(self, items, out_dir, mc_ver, loader, mode, cf_key,
                       mr_type=None, cf_class=None):
        if mr_type  is None: mr_type  = MR_MOD
        if cf_class is None: cf_class = CF_MOD
        auto_deps = self.search_auto_deps.get()
        strict    = self.search_strict_deps.get()
        done_deps = set()
        ok_list   = []
        fail_list = []

        for i, item in enumerate(items):
            if self._search_cancel_flag:
                self._search_log("\n⏹ 中止されました","warn"); break
            name         = item["name"]
            ver_override = item.get("ver_override")
            self._search_set_item_status(item["iid"],"🔄 検索中...")
            self._search_set_status(f"{i+1}/{len(items)}: {name[:24]}")
            self._search_log(f"\n── {name} ──","info")

            def _log(msg, tag=""): self._search_log(msg, tag)

            dl_url, dl_fname, source, version_obj = find_dl_info(
                name, "", None,
                mc_ver, loader, mode, cf_key,
                mr_type, cf_class, _log,
                ver_override=ver_override)

            if dl_url and dl_fname:
                dest = os.path.join(out_dir, dl_fname)
                try:
                    self._search_log(f"  ⬇ DL中 [{source}]: {dl_fname}","")
                    download_file(dl_url, dest,
                                  lambda prog, n=name: self._search_set_status(
                                      f"DL: {n[:18]} {prog*100:.0f}%"))
                    self._search_log("  ✅ 完了","ok")
                    self._search_set_item_status(item["iid"],"✅ 完了")
                    ok_list.append(name)
                    if auto_deps and version_obj:
                        for dep_pid, dep_vid in mr_get_deps(version_obj):
                            if dep_pid in done_deps: continue
                            done_deps.add(dep_pid)
                            self._search_log(f"  🔗 依存Mod: {dep_pid}","info")
                            try:
                                du = df = None
                                if strict and dep_vid:
                                    v_data = http_get(f"{MODRINTH_API}/version/{dep_vid}")
                                    du, df = mr_best_file(v_data)
                                else:
                                    vs = mr_get_versions(dep_pid, mc_ver, loader)
                                    if vs: du, df = mr_best_file(vs[0])
                                if du and df:
                                    ddest = os.path.join(out_dir, df)
                                    if os.path.exists(ddest):
                                        self._search_log(f"  🔗 既存: {df}","ok")
                                    else:
                                        download_file(du, ddest)
                                        self._search_log(f"  🔗 依存DL完了: {df}","ok")
                                        ok_list.append(f"[依存] {df}")
                                else:
                                    self._search_log("  🔗 依存Mod: 対応バージョンなし","warn")
                            except Exception as dep_e:
                                self._search_log(f"  🔗 依存エラー: {dep_e}","err")
                except Exception as e:
                    self._search_log(f"  ❌ DL失敗: {e}","err")
                    if os.path.exists(dest):
                        try: os.remove(dest)
                        except Exception: pass
                    self._search_set_item_status(item["iid"],"❌ 失敗")
                    fail_list.append(name)
            else:
                self._search_set_item_status(item["iid"],"❌ 見つからず")
                fail_list.append(name)

            self._search_set_progress(i + 1)

        self._search_log(f"\n{'═'*40}","info")
        self._search_log(f"✅ 成功: {len(ok_list)} 件","ok")
        for n in ok_list: self._search_log(f"   ✓ {n}","ok")
        if fail_list:
            self._search_log(f"❌ 失敗: {len(fail_list)} 件","err")
            for n in fail_list: self._search_log(f"   ✗ {n}","err")
        else:
            self._search_log("🎉 全て完了！","ok")

        self._search_set_status("完了" if not self._search_cancel_flag else "中止")
        self._search_running = False
        self.after(0, lambda: self._cancel_btn.config(state="disabled"))
        msg = f"✅ 成功: {len(ok_list)} 件\n❌ 失敗: {len(fail_list)} 件"
        if fail_list:
            msg += "\n\n失敗:\n" + "\n".join(f"  • {n}" for n in fail_list)
        self.after(0, lambda: messagebox.showinfo("完了", msg))

    def _build_plugin_tab(self, p):
        """plugin_updater.py を動的にインポートしてプラグインタブに埋め込む"""
        try:
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            plugin_path = os.path.join(base, "plugin_updater.py")
            import importlib.util
            spec   = importlib.util.spec_from_file_location("plugin_updater", plugin_path)
            mod    = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod._apply_theme_globals(self._theme)
            self._plugin_app = mod.PluginUpdaterApp(p, theme=self._theme,
                                                     icon_path=self._icon_path,
                                                     parent_app=self)
            self._plugin_app.pack(fill="both", expand=True)
            self._plugin_app._disable_combobox_wheel()
            # プラグインリスト出力ボタン（タブ下部）
            plugin_bar = ttk.Frame(p)
            plugin_bar.pack(fill="x", padx=4, pady=(0,4))
            ttk.Button(plugin_bar, text="📤 プラグインリスト出力",
                       command=lambda: self._export_list(None, "plugin"),
                       width=22).pack(side="left", padx=(4,0))
        except Exception as e:
            ttk.Label(p, text=f"プラグインタブの読み込みに失敗しました\n{e}",
                       foreground=RED).pack(expand=True)
            self._plugin_app = None

    def _toggle_theme(self):
        self._theme = "dark" if self._theme == "light" else "light"
        _apply_theme_globals(self._theme)
        self._apply_style()
        t = self._t()
        self._theme_btn.config(text=t["ICON"])
        # ログボックスの色を更新
        for box in self._log_boxes.values():
            box.config(bg=t["LOG"], fg=t["FG"],
                       selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
                       insertbackground=t["FG"])
            box.frame.configure(background=t["LOG"])
            for tag, color in [("ok",t["GRN"]),("err",t["RED"]),("info",t["ACC"]),("warn",t["YEL"])]:
                box.tag_config(tag, foreground=color)
        # ラベルの色を更新
        self._mode_desc.config(fg=t["YEL"], bg=t["BG"])
        self._ver_status.config(fg=t["YEL"], bg=t["BG"])
        self._profile_note.config(foreground=t["YEL"], background=t["BG"])
        if hasattr(self, "_settings_warn_label"):
            self._settings_warn_label.config(fg=t["RED"], bg=t["BG"])
        if self._settings_canvas:
            self._settings_canvas.config(bg=t["BG"])
        # Treeview は ttk.Style 側（_apply_style）で色が更新されるため configure 不要
        # サイドパネル（Canvas・Frame・tk.Label）の色を更新
        for panel in (self._mod_panel, self._rp_panel, self._shader_panel):
            panel._side_canvas.configure(bg=t["BG"])
            panel._side_frame.configure(bg=t["BG"])
            panel._side_sep.configure(bg=t["BG3"])
            panel._side_lbl_sel.configure(bg=t["BG"], fg=t["FG"])
            panel._side_name.configure(bg=t["BG"], fg=t["FG"])
            panel._side_lbl_ver.configure(bg=t["BG"], fg=t["FG"])
            panel._ver_status.configure(bg=t["BG"])
            # ver_status の fg は現在の状態テキストから判定して維持
            vs_text = panel._ver_status.cget("text")
            if vs_text.startswith("✅"):
                panel._ver_status.configure(fg=t["GRN"])
            elif vs_text.startswith("⚠"):
                panel._ver_status.configure(fg=t["RED"])
            elif vs_text.startswith("🔄"):
                panel._ver_status.configure(fg=t["YEL"])
            else:
                panel._ver_status.configure(fg=t["FG"])
        # GitHubボタンの画像をテーマに合わせて更新
        if hasattr(self, "_gh_btn") and self._gh_btn.winfo_exists():
            try:
                from PIL import Image, ImageTk
                ico_name = "GitHub_Lockup_White.ico" if self._theme == "dark" else "GitHub_Lockup_Black.ico"
                pil_img = Image.open(os.path.join(self._gh_btn_base, ico_name))
                target_h = 36
                target_w = int(pil_img.width * target_h / pil_img.height)
                pil_img = pil_img.resize((target_w, target_h), Image.LANCZOS)
                gh_img = ImageTk.PhotoImage(pil_img)
                self._gh_btn.config(image=gh_img, bg=t["BG"], activebackground=t["BG2"])
                self._gh_btn.image = gh_img  # GC対策
            except Exception: pass  # 画像更新失敗時は現状維持
        # バックアップモードウィジェットの色を更新
        if hasattr(self, "_backup_dir_lbl"):
            self._backup_dir_lbl.config(bg=t["BG"], fg=t["FG"])
        if hasattr(self, "_backup_note_lbl"):
            self._backup_note_lbl.config(bg=t["BG"], fg=t["YEL"])
        # プラグインタブにも適用
        if hasattr(self, "_plugin_app") and self._plugin_app:
            self._plugin_app.apply_theme(self._theme)
        # Mod検索タブのtk.Labelなどを更新
        if hasattr(self, "_search_tk_widgets"):
            for widget, color_key, attr in self._search_tk_widgets:
                try:
                    widget.config(**{attr: t[color_key]})
                except Exception: pass
        if hasattr(self, "_search_log_box"):
            self._search_log_box.config(
                bg=t["LOG"], fg=t["FG"],
                selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
                insertbackground=t["FG"])
            self._search_log_box.frame.configure(background=t["LOG"])
            for tag, color in [("ok",t["GRN"]),("err",t["RED"]),("info",t["ACC"]),("warn",t["YEL"])]:
                self._search_log_box.tag_config(tag, foreground=color)
        # 入力欄（ScrolledText）の色を更新
        if hasattr(self, "_search_input"):
            self._search_input.config(bg=t["LOG"], fg=t["FG"],
                                       selectbackground=t["SEL"], selectforeground=t["SEL_FG"],
                                       insertbackground=t["FG"])
            self._search_input.frame.configure(background=t["LOG"])
        # バージョン状態ラベルの fg を現在の状態に合わせて再設定
        if hasattr(self, "_search_ver_side_status"):
            txt = self._search_ver_side_status.cget("text")
            if txt.startswith("✅"):   self._search_ver_side_status.config(fg=t["GRN"])
            elif txt.startswith("⚠"): self._search_ver_side_status.config(fg=t["RED"])
            elif txt.startswith("🔄"): self._search_ver_side_status.config(fg=t["YEL"])
            else:                       self._search_ver_side_status.config(fg=t["FG"])

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

    def _export_list(self, panel, kind_key):
        """パネルの一覧をテキストファイルに出力する。
        kind_key: "mod" / "resourcepack" / "shader" / "plugin"
        """
        # 対象アイテム取得
        if kind_key == "plugin":
            if not hasattr(self, "_plugin_app") or not self._plugin_app:
                messagebox.showerror("エラー", "プラグインタブが利用できません"); return
            items = self._plugin_app.plugin_list
            if not items:
                messagebox.showinfo("情報", "プラグインリストが空です\nまず「📂 読み込む」を実行してください"); return
            lines = [it.get("name", it.get("filename","")) for it in items]
        else:
            if not panel.items:
                messagebox.showinfo("情報", "リストが空です\nまず「📂 読み込む」を実行してください"); return
            lines = [it.get("name") or it.get("display_name") or it.get("filename","")
                     for it in panel.items]

        label_map = {
            "mod":          "Mod",
            "resourcepack": "ResourcePack",
            "shader":       "Shader",
            "plugin":       "Plugin",
        }
        default_name = f"{label_map.get(kind_key, kind_key)}_list.txt"

        path = filedialog.asksaveasfilename(
            title="リストを保存",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("テキストファイル","*.txt"),("CSVファイル","*.csv"),("すべて","*.*")]
        )
        if not path: return

        try:
            # 拡張子が .csv ならカンマ区切り、それ以外は1行1項目
            if path.lower().endswith(".csv"):
                content = ", ".join(lines) + "\n"
            else:
                content = "\n".join(lines) + "\n"
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self._log(f"📤 {label_map.get(kind_key,kind_key)}リスト出力: {os.path.basename(path)} ({len(lines)} 件)", "ok", "sys")
            messagebox.showinfo("完了", f"{len(lines)} 件を出力しました\n{path}")
        except Exception as e:
            messagebox.showerror("出力エラー", str(e))

    def _cancel(self):
        self._cancel_flag = True
        if hasattr(self, "_search_cancel_flag"):
            self._search_cancel_flag = True
        if hasattr(self, "_plugin_app") and self._plugin_app:
            self._plugin_app._psearch_cancel_flag = True
        self._set_status("中止中...")
        self._cancel_btn.config(state="disabled")
        if hasattr(self, "_plugin_app") and self._plugin_app:
            self._plugin_app._cancel()

    def _disable_combobox_wheel(self):
        def _block(e): return "break"
        def _bind(w):
            if isinstance(w, ttk.Combobox):
                for ev in ("<MouseWheel>","<Button-4>","<Button-5>"): w.bind(ev, _block)
            for c in w.winfo_children(): _bind(c)
        _bind(self)
        for ev in ("<MouseWheel>","<Button-4>","<Button-5>"): self._ver_cb.bind(ev, _block)

    def _filter_versions(self):
        loader  = self.target_loader.get()
        min_ver = LOADER_MIN.get(loader)
        # 全バージョンリストを _all_versions に保持し、常にそこからフィルタする
        # （フィルタ済みリストを再フィルタすると元に戻せなくなる）
        if not hasattr(self, "_all_versions") or not self._all_versions:
            self._all_versions = list(self._ver_cb["values"])
        all_v    = self._all_versions
        filtered = [v for v in all_v if ver_tuple(v) >= min_ver] if min_ver else all_v
        if not filtered:
            filtered = all_v
        self._ver_cb["values"] = filtered
        cur = self.target_version.get()
        if cur not in filtered:
            self._ver_cb.set(filtered[0])
            self.target_version.set(filtered[0])

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
            except Exception: pass  # アイコン設定失敗はUIに影響しないため無視
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
        if self._load_dir(self.mods_dir, ".jar", self._mod_panel, "mod", "Mod"):
            if self.auto_switch_tab.get(): self._mod_select(1)
            self._show_toast("Modを読み込みました。")

    def _load_rp(self):
        if self._load_dir(self.rp_dir, ".zip", self._rp_panel, "rp", "ResourcePack"):
            if self.auto_switch_tab.get(): self._mod_select(1)
            self._show_toast("ResourcePackを読み込みました。")

    def _load_shader(self):
        if self._load_dir(self.shader_dir, ".zip", self._shader_panel, "shader", "Shader"):
            if self.auto_switch_tab.get(): self._mod_select(1)
            self._show_toast("Shaderを読み込みました。")

    def _load_all(self):
        loaded = []
        if self._load_dir(self.mods_dir, ".jar", self._mod_panel, "mod", "Mod"):
            loaded.append("Mod")
        if self._load_dir(self.rp_dir, ".zip", self._rp_panel, "rp", "ResourcePack"):
            loaded.append("ResourcePack")
        if self._load_dir(self.shader_dir, ".zip", self._shader_panel, "shader", "Shader"):
            loaded.append("Shader")
        if loaded:
            if self.auto_switch_tab.get(): self._mod_select(1)
            self._show_toast("・".join(loaded) + "を読み込みました。")

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
        # _load_allでまとめて読み込み・トースト通知
        self._load_all()

    # ── アップデート ──────────────────────────────────────────
    def _build_tasks(self, panel):
        dir_map  = {MR_MOD:self.mods_dir.get(),MR_RP:self.rp_dir.get(),MR_SHADE:self.shader_dir.get()}
        cf_class = {MR_MOD:CF_MOD,MR_RP:CF_RP,MR_SHADE:CF_SHADE}[panel.mr_type]
        tasks = []
        for it in panel.get_selected():
            it = dict(it)  # コピー
            it["_ver_override"] = panel.get_version_override(it["filename"])
            tasks.append((it, dir_map[panel.mr_type], panel.mr_type, cf_class))
        return tasks

    def _start_panel(self, panel, label, single_type_key=None):
        if not self._validate_cf(): return
        tasks = self._build_tasks(panel)
        if not tasks: messagebox.showinfo("情報","アイテムが選択されていません"); return
        self._run_tasks(tasks, single_type=single_type_key)

    def _start_all(self):
        if not self._validate_cf(): return
        tasks = self._build_tasks(self._mod_panel) + self._build_tasks(self._rp_panel) + self._build_tasks(self._shader_panel)
        if not tasks: messagebox.showinfo("情報","アイテムが選択されていません"); return
        self._run_tasks(tasks, single_type=None)

    def _run_tasks(self, tasks, single_type=None):
        if self._running: messagebox.showwarning("実行中","現在アップデート中です"); return
        self._running = True; self._cancel_flag = False
        self._set_progress(0, len(tasks)); self._mod_select(2)
        def _enable_cancel():
            self._cancel_btn.config(state="normal")
        self.after(0, _enable_cancel)
        threading.Thread(target=self._worker,
                          args=(tasks, self.target_version.get(), self.target_loader.get(),
                                self.dl_mode.get(), self.cf_api_key.get().strip(), single_type),
                          daemon=True).start()

    def _worker(self, tasks, mc_ver, loader, mode, cf_key, single_type=None):
        delete_old   = self.delete_old.get()
        delete_fail  = self.delete_failed.get()
        auto_deps    = self.auto_deps.get()
        strict       = self.strict_deps.get()
        backup_on    = self.backup_mode.get()
        backup_base  = self.backup_dir.get().strip()
        done_deps    = set()
        results      = {"mod":{"ok":[],"fail":[]},"rp":{"ok":[],"fail":[]},"shader":{"ok":[],"fail":[]}}

        # バックアップモード時: 今回の実行で1つの親フォルダを共有する
        import datetime
        _backup_ts      = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        _backup_subdirs = {}  # key -> 実際の出力先フォルダ（初回アクセス時に作成）

        def _resolve_out_dir(key, original_dir):
            """バックアップモードONのときは専用フォルダを返す。
            単体（single_type指定あり）: v{ver}_{type}_{ts} 直下（子フォルダなし）
            複数（single_type=None）  : v{ver}_{ts}/{type} サブフォルダあり
            """
            if not backup_on:
                return original_dir
            if key not in _backup_subdirs:
                if single_type is not None:
                    # 単体: 子フォルダなし
                    out = os.path.join(backup_base, f"v{mc_ver}_{single_type}_{_backup_ts}")
                else:
                    # 複数: 種類ごとサブフォルダ
                    sub_map = {"mod": "mods", "rp": "resourcepacks", "shader": "shaderpacks"}
                    parent  = os.path.join(backup_base, f"v{mc_ver}_{_backup_ts}")
                    out     = os.path.join(parent, sub_map.get(key, key))
                os.makedirs(out, exist_ok=True)
                _backup_subdirs[key] = out
            return _backup_subdirs[key]

        if backup_on:
            if not backup_base or not os.path.isdir(backup_base):
                self.after(0, lambda: messagebox.showerror(
                    "バックアップモードエラー",
                    "バックアップ出力先フォルダが設定されていないか存在しません。\n"
                    "全体設定タブで有効なフォルダを指定してください。"))
                self._running = False
                return
            if single_type is not None:
                self._log(f"💾 バックアップモード ON → v{mc_ver}_{single_type}_{_backup_ts}/", "info", "sys")
            else:
                self._log(f"💾 バックアップモード ON → v{mc_ver}_{_backup_ts}/", "info", "sys")

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
                mc_ver, loader, mode, cf_key, mr_type, cf_class, _log,
                ver_override=item.get("_ver_override"))

            if dl_url and dl_fname:
                actual_dir  = _resolve_out_dir(key, out_dir)
                dest        = os.path.join(actual_dir, dl_fname)
                # バックアップモード時は元ファイルを上書き・削除しない
                do_del_old  = (delete_old  if mr_type == MR_MOD else False) and not backup_on
                do_del_fail = (delete_fail if mr_type == MR_MOD else False) and not backup_on
                old_path    = None if backup_on else item.get("path")
                success     = self._do_download(dl_url, dest, name, source,
                                                 old_path, do_del_old, do_del_fail, key)
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
                                    # バックアップモード時は元フォルダを走査しない
                                    if du and df and not backup_on:
                                        try:
                                            slug = http_get(f"{MODRINTH_API}/project/{dep_pid}").get("slug","")
                                            for fn in os.listdir(out_dir):
                                                if not fn.lower().endswith(".jar"): continue
                                                fp = os.path.join(out_dir, fn)
                                                m  = read_jar_meta(fp)
                                                if m.get("mod_id") == slug and fn != df:
                                                    self._log(f"  🔗 バージョン不足のため差し替え: {fn}","warn",key)
                                                    try: os.remove(fp)
                                                    except Exception:  # 削除失敗は差し替え処理継続に影響しないため無視
                                                        pass
                                                    break
                                        except Exception: pass  # 依存関係解決の失敗は後続処理に影響しないため無視
                                else:
                                    vs = mr_get_versions(dep_pid, mc_ver, loader)
                                    if vs: du, df = mr_best_file(vs[0])
                                if du and df:
                                    ddest = os.path.join(actual_dir, df)
                                    if os.path.exists(ddest):
                                        self._log(f"  🔗 既存: {df}","ok",key)
                                    else:
                                        self._do_download(du, ddest, df, "Modrinth", None, False, do_del_fail, key)
                                        dep_item = {"filename":df,"path":ddest,"name":df,"mod_id":"","version":"","loader":""}
                                        self.after(0, lambda di=dep_item: self._mod_panel.add_item(di,"dep"))
                                        results[key]["ok"].append(f"[依存] {df}")
                                else:
                                    self._log("  🔗 依存Mod: 対応バージョンなし", "warn", key)
                            except Exception as e:
                                self._log(f"  🔗 依存エラー: {e}","err",key)
                else:
                    results[key]["fail"].append(name)
            else:
                results[key]["fail"].append(name)
                self._log("  ❌ スキップ（対応バージョンなし）","err",key)
                if delete_fail and not backup_on and mr_type == MR_MOD and item.get("path") and os.path.exists(item["path"]):
                    try: os.remove(item["path"]); self._log(f"  🗑 失敗ファイル削除: {item['filename']}","warn",key)
                    except Exception:  # 削除失敗は処理継続に影響しないため無視
                        pass
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
        def _disable_cancel():
            self._cancel_btn.config(state="disabled")
        self.after(0, _disable_cancel)
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
                    self._log(f"  🗑 旧ファイル削除: {os.path.basename(old_path)}","warn",log_key)
            self._log("  ✅ 完了","ok",log_key); return True
        except Exception as e:
            self._log(f"  ❌ DL失敗: {e}","err",log_key)
            if os.path.exists(dest):
                try: os.remove(dest)
                except Exception: pass  # 一時ファイル削除失敗は無視
            if delete_fail and old_path and os.path.exists(old_path):
                try: os.remove(old_path); self._log(f"  🗑 失敗ファイル削除: {os.path.basename(old_path)}","warn",log_key)
                except Exception: pass  # 削除失敗は処理継続に影響しないため無視
            return False

    def _fetch_versions_bg(self):
        versions = fetch_mc_versions()
        def _upd():
            cur = self.target_version.get()
            # 全バージョンリストを更新（フィルタのベースになる）
            self._all_versions = list(versions)
            self._ver_cb["values"] = versions
            self._ver_cb.set(cur if cur in versions else versions[0])
            self.target_version.set(self._ver_cb.get())
            self._filter_versions()
            for ev in ("<MouseWheel>","<Button-4>","<Button-5>"):
                self._ver_cb.bind(ev, lambda e: "break")
            # 検索タブのバージョンコンボにも反映
            if hasattr(self, "_search_ver_cb"):
                scur = self.search_version.get()
                self._search_ver_cb["values"] = versions
                self._search_ver_cb.set(scur if scur in versions else versions[0])
                self.search_version.set(self._search_ver_cb.get())
                for ev in ("<MouseWheel>","<Button-4>","<Button-5>"):
                    self._search_ver_cb.bind(ev, lambda e: "break")
            if versions == MC_VERSIONS_FALLBACK:
                self._ver_status.config(text="⚠ オフライン", foreground=YEL)
                if hasattr(self,"_search_ver_status"):
                    self._search_ver_status.config(text="⚠", foreground=YEL)
                self._log("⚠ バージョン取得失敗 → フォールバック使用","warn","sys")
            else:
                self._ver_status.config(text=f"✅ {len(versions)} 件", foreground=GRN)
                if hasattr(self,"_search_ver_status"):
                    self._search_ver_status.config(text=f"✅ {len(versions)}件", foreground=GRN)
                self._log(f"✅ MCバージョン {len(versions)} 件取得（最新: {versions[0]}）","ok","sys")
        self.after(0, _upd)

    def _on_close(self):
        cfg = load_config()
        cfg.update({
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
            "auto_switch_tab":self.auto_switch_tab.get(),
            "toast_enabled":  self.toast_enabled.get(),
            "toast_duration": self.toast_duration.get(),
            "backup_mode":    self.backup_mode.get(),
            "backup_dir":     self.backup_dir.get(),
            "theme":          self._theme,
            "search_dl_dir":     self.search_dl_dir.get(),
            "search_version":    self.search_version.get(),
            "search_loader":     self.search_loader.get(),
            "search_dl_mode":    self.search_dl_mode.get(),
            "search_auto_deps":  self.search_auto_deps.get(),
            "search_strict_deps":self.search_strict_deps.get(),
        })
        # plugin_updater の設定を値を直接取り出してマージ（別ファイルに保存されないよう）
        if hasattr(self, "_plugin_app") and self._plugin_app:
            pa = self._plugin_app
            cfg.update({
                "plugins_dir":          pa.plugins_dir.get(),
                "plugin_delete_old":    pa.delete_old.get(),
                "plugin_delete_failed": pa.delete_failed.get(),
                "plugin_auto_deps":     pa.auto_deps.get(),
            })
        save_config(cfg)
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()
