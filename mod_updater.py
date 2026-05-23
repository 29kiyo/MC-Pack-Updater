import os
import re
import json
import zipfile
import hashlib
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import urllib.request
import urllib.parse
import webbrowser

# ── 定数 ──────────────────────────────────────────────────────
MODRINTH_API   = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"
CONFIG_FILE    = os.path.join(os.path.expanduser("~"), ".mc_pack_updater_config.json")

MC_VERSIONS_FALLBACK = [
    "1.21.4","1.21.3","1.21.1","1.21",
    "1.20.6","1.20.4","1.20.2","1.20.1","1.20",
    "1.19.4","1.19.3","1.19.2","1.19.1","1.19",
    "1.18.2","1.18.1","1.18","1.17.1","1.17",
    "1.16.5","1.16.4","1.16.3","1.16.2","1.16.1",
    "1.15.2","1.12.2",
]
LOADERS  = ["fabric","forge","neoforge","quilt"]
DL_BOTH     = "両方（Modrinth優先）"
DL_CF_FIRST = "両方（CurseForge優先）"
DL_MR       = "Modrinthのみ"
DL_CF       = "CurseForgeのみ"
DL_MODES    = [DL_BOTH, DL_CF_FIRST, DL_MR, DL_CF]

CF_LOADER = {"forge":1,"fabric":4,"quilt":5,"neoforge":6}
CF_GAME   = 432
CF_MOD    = 6
CF_RP     = 12
CF_SHADE  = 6552
MR_MOD    = "mod"
MR_RP     = "resourcepack"
MR_SHADE  = "shader"

def clean_name(raw_name):
    """ファイル名からバージョン番号・MC バージョン等を除去して検索用名前を返す。
    例: '3D items_1.20' -> '3D items'
        'SomeShader v2.1 MC1.20.1' -> 'SomeShader'
    """
    name = raw_name
    # MC1.x / for1.x 形式（MCプレフィックス付き）を先に削除
    name = re.sub(r'[\s_\-\.]+(mc|for|fabric|forge|neoforge|quilt)\d+[\.\d]*$',
                  '', name, flags=re.IGNORECASE)
    # _v2.1 / -v5.1 / v2.1 のようなバージョン番号を削除
    name = re.sub(r'[\s_\-\.]+v\d+[\.\d]*[a-zA-Z]*$', '', name, flags=re.IGNORECASE)
    # _1.20 / -1.19.2 / 1.20.1 のような数字バージョンを削除
    name = re.sub(r'[\s_\-\.]+\d+\.\d+[\.\d]*[a-zA-Z]*$', '', name, flags=re.IGNORECASE)
    # 末尾の記号を整理
    name = name.strip(" _-.")
    return name if name else raw_name

# ── カラー ────────────────────────────────────────────────────
BG  = "#f4f4f0"
BG2 = "#e8e8e3"
BG3 = "#d0d0c8"
FG  = "#1e1e1e"
ACC = "#1d4ed8"
GRN = "#15803d"
RED = "#dc2626"
YEL = "#92400e"

# ── 設定 ──────────────────────────────────────────────────────
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

# ── HTTP ──────────────────────────────────────────────────────
def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent", "MC-Pack-Updater/5.0")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def download_file(url, dest, progress_cb=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MC-Pack-Updater/5.0")
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        done  = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk: break
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(done / total)

# ── MCバージョン ──────────────────────────────────────────────
def fetch_mc_versions():
    try:
        data = http_get(f"{MODRINTH_API}/tag/game_version")
        releases = [v["version"] for v in data
                    if v.get("version_type") == "release" and "." in v.get("version","")]
        releases.sort(key=lambda v: tuple(int(x) if x.isdigit() else 0
                                          for x in re.split(r"[.\-]", v)), reverse=True)
        return releases if releases else MC_VERSIONS_FALLBACK
    except Exception:
        return MC_VERSIONS_FALLBACK

# ── JAR解析 ───────────────────────────────────────────────────
def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""): h.update(chunk)
    return h.hexdigest()

def read_jar_meta(jar_path):
    info = {"filename": os.path.basename(jar_path), "path": jar_path,
            "name": os.path.basename(jar_path), "mod_id":"", "version":"", "loader":"不明"}
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
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
    except Exception:
        pass
    return info

# ── Modrinth ──────────────────────────────────────────────────
def mr_find_project(sha1, mod_id, name, project_type):
    if sha1:
        try:
            d = http_get(f"{MODRINTH_API}/version_file/{sha1}?algorithm=sha1")
            if d.get("project_id"): return d["project_id"]
        except Exception: pass
    if mod_id:
        try:
            d = http_get(f"{MODRINTH_API}/project/{mod_id}")
            if d.get("id"): return d["id"]
        except Exception: pass
    try:
        params = urllib.parse.urlencode({
            "query": name, "limit": 5,
            "facets": json.dumps([["project_type:"+project_type]]),
        })
        d = http_get(f"{MODRINTH_API}/search?{params}")
        hits = d.get("hits", [])
        if not hits: return None
        for h in hits:
            if h.get("title","").lower() == name.lower(): return h["project_id"]
        return hits[0]["project_id"]
    except Exception:
        return None

def mr_get_versions(pid, mc_ver, loader, mr_type=MR_MOD):
    try:
        # RP・Shaderはmod loaderなしでバージョンのみ指定
        if mr_type in (MR_RP, MR_SHADE):
            params = urllib.parse.urlencode({
                "game_versions": json.dumps([mc_ver]),
            })
        else:
            params = urllib.parse.urlencode({
                "game_versions": json.dumps([mc_ver]),
                "loaders":       json.dumps([loader]),
            })
        return http_get(f"{MODRINTH_API}/project/{pid}/version?{params}")
    except Exception:
        return []

def mr_get_deps(version_obj, mc_ver, loader):
    return [d.get("project_id") for d in version_obj.get("dependencies",[])
            if d.get("dependency_type") == "required" and d.get("project_id")]

# ── CurseForge ────────────────────────────────────────────────
def _cf_req(url, api_key):
    req = urllib.request.Request(url)
    req.add_header("User-Agent","MC-Pack-Updater/5.0")
    req.add_header("x-api-key", api_key)
    req.add_header("Accept","application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def cf_search(name, api_key, class_id):
    params = urllib.parse.urlencode({
        "gameId":CF_GAME,"classId":class_id,"searchFilter":name,"pageSize":5,
        "sortField":2,"sortOrder":"desc",
    })
    try:
        d = _cf_req(f"{CURSEFORGE_API}/mods/search?{params}", api_key)
        results = d.get("data",[])
        if not results: return None
        for r in results:
            if r.get("name","").lower() == name.lower(): return r["id"]
        return results[0]["id"]
    except Exception:
        return None

def cf_get_file(cf_id, mc_ver, loader, api_key, mr_type=MR_MOD):
    # RP・Shaderはmod loaderなし（0=Any）
    loader_id = CF_LOADER.get(loader, 0) if mr_type == MR_MOD else 0
    params = urllib.parse.urlencode({
        "gameVersion":mc_ver, "modLoaderType":loader_id, "pageSize":10,
    })
    try:
        d = _cf_req(f"{CURSEFORGE_API}/mods/{cf_id}/files?{params}", api_key)
        files = d.get("data",[])
        files.sort(key=lambda f: (f.get("releaseType",9), -f.get("id",0)))
        return files[0] if files else None
    except Exception:
        return None

# ── 統合検索 ──────────────────────────────────────────────────
def find_dl_info(name, mod_id, path, mc_ver, loader, mode, cf_key,
                 mr_type, cf_class, log_cb):
    do_mr      = mode in (DL_BOTH, DL_CF_FIRST, DL_MR)
    do_cf      = mode in (DL_BOTH, DL_CF_FIRST, DL_CF)
    cf_first   = mode == DL_CF_FIRST
    dl_url = dl_fname = source = None
    version_obj = None

    def _try_modrinth():
        nonlocal dl_url, dl_fname, source, version_obj
        try:
            sha1 = sha1_file(path) if path and os.path.exists(path) else None
            pid  = mr_find_project(sha1, mod_id, name, mr_type)
            if pid:
                vs = mr_get_versions(pid, mc_ver, loader, mr_type)
                if vs:
                    version_obj = vs[0]
                    for fi in vs[0].get("files",[]):
                        if fi.get("primary") or not dl_url:
                            dl_url,dl_fname,source = fi["url"],fi["filename"],"Modrinth"
                            if fi.get("primary"): break
                    log_cb(f"  ✓ Modrinth: {dl_fname}","ok")
                else:
                    log_cb(f"  Modrinth: {mc_ver} 対応なし","warn")
            else:
                log_cb(f"  Modrinth: 見つからず","warn")
        except Exception as e:
            log_cb(f"  Modrinth エラー: {e}","err")

    def _try_curseforge():
        nonlocal dl_url, dl_fname, source
        try:
            cf_id = cf_search(name, cf_key, cf_class)
            if cf_id:
                fi = cf_get_file(cf_id, mc_ver, loader, cf_key, mr_type)
                if fi:
                    dl_url,dl_fname,source = fi.get("downloadUrl"),fi.get("fileName"),"CurseForge"
                    log_cb(f"  ✓ CurseForge: {dl_fname}","ok")
                else:
                    log_cb(f"  CurseForge: {mc_ver} 対応なし","warn")
            else:
                log_cb(f"  CurseForge: 見つからず","warn")
        except Exception as e:
            log_cb(f"  CurseForge エラー: {e}","err")

    if cf_first:
        if do_cf: _try_curseforge()
        if do_mr and not dl_url: _try_modrinth()
    else:
        if do_mr: _try_modrinth()
        if do_cf and not dl_url: _try_curseforge()

    return dl_url, dl_fname, source, version_obj

# ══════════════════════════════════════════════════════════════
# FileListPanel
# ══════════════════════════════════════════════════════════════
class FileListPanel(ttk.Frame):
    def __init__(self, parent, mr_type, load_fn, update_fn, **kw):
        super().__init__(parent, **kw)
        self.mr_type  = mr_type
        self._load_fn   = load_fn
        self._update_fn = update_fn
        self.items = []
        self._build()

    def _build(self):
        # ── ツールバー：固定高さで揺れを防ぐ ──
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=(6,2))

        ttk.Button(top, text="全選択", width=6,
                    command=lambda: self._sel_all(True)).pack(side="left", padx=(0,3))
        ttk.Button(top, text="全解除", width=6,
                    command=lambda: self._sel_all(False)).pack(side="left", padx=(0,6))
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=(0,6), pady=2)
        ttk.Button(top, text="📂 読込", width=7,
                    command=self._load_fn).pack(side="left", padx=(0,3))
        ttk.Button(top, text="⬇ 更新", width=7,
                    command=self._update_fn).pack(side="left")

        # 固定幅ラベルで全選択/解除時のレイアウト揺れを防ぐ
        self._sel_label = ttk.Label(top, text="0 / 0 件", width=12, anchor="e")
        self._sel_label.pack(side="right", padx=4)

        if self.mr_type == MR_MOD:
            cols  = ("chk","name","version","loader")
            heads = [("chk","✔",36),("name","名前",200),
                     ("version","バージョン",95),("loader","Loader",70)]
        else:
            cols  = ("chk","name")
            heads = [("chk","✔",36),("name","名前",280)]

        self._tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="none")
        for cid,lbl,w in heads:
            self._tree.heading(cid, text=lbl)
            # name以外は固定幅、nameだけstretch=Trueで残り幅を全部使う
            self._tree.column(cid, width=w,
                               minwidth=w if cid != "name" else 80,
                               anchor="center" if cid=="chk" else "w",
                               stretch=(cid=="name"))
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
            tag = "even" if i%2==0 else "odd"
            iid = it["filename"]
            # 表示名: display_name があればそちらを優先（RP/Shaderの元ファイル名）
            display = it.get("display_name") or it.get("name", iid)
            vals = (("☑", display, it.get("version","?"), it.get("loader","?"))
                    if self.mr_type == MR_MOD else
                    ("☑", display))
            self._tree.insert("","end", iid=iid, tags=(tag,), values=vals)
        self._upd_label()

    def add_item(self, item, tag="dep"):
        iid = item["filename"]
        if self._tree.exists(iid): return
        self.items.append(item)
        vals = (("☑", item.get("name",iid), item.get("version",""), item.get("loader",""))
                if self.mr_type == MR_MOD else
                ("☑", item.get("name",iid)))
        self._tree.insert("","end", iid=iid, tags=(tag,), values=vals)
        self._upd_label()

    def get_selected(self):
        return [it for it in self.items
                if self._tree.exists(it["filename"]) and
                   self._tree.set(it["filename"],"chk") == "☑"]

    def _on_click(self, e):
        row = self._tree.identify_row(e.y)
        col = self._tree.identify_column(e.x)
        if row and col == "#1":
            cur = self._tree.set(row,"chk")
            self._tree.set(row,"chk","☑" if cur=="☐" else "☐")
            self._upd_label()

    def _sel_all(self, v):
        for row in self._tree.get_children():
            self._tree.set(row,"chk","☑" if v else "☐")
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

        # ウィンドウ・タスクバーのアイコン設定
        try:
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base, "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass
        self.geometry("1150x780")
        self.configure(bg=BG)
        self.resizable(True, True)

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

        self._cf_key_showing = False
        self._running        = False
        self._cancel_flag    = False

        self._apply_style()
        self._build_ui()
        self._disable_combobox_wheel()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._fetch_versions_bg, daemon=True).start()

    # ── スタイル ──────────────────────────────────────────────
    def _apply_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",           background=BG)
        s.configure("TLabel",           background=BG, foreground=FG, font=("Segoe UI",10))
        s.configure("Hdr.TLabel",       background=BG, foreground=ACC, font=("Segoe UI",13,"bold"))
        s.configure("Sub.TLabel",       background=BG, foreground=FG,  font=("Segoe UI",9))
        s.configure("TButton",          background=ACC, foreground="#ffffff",
                     font=("Segoe UI",10,"bold"), relief="flat", padding=(8,5))
        s.map("TButton",                background=[("active","#3b82f6"),("disabled",BG3)],
                                        foreground=[("disabled","#9ca3af")])
        s.configure("TEntry",           fieldbackground=BG2, foreground=FG,
                     insertcolor=FG, relief="flat", padding=4)
        s.configure("TCheckbutton",     background=BG, foreground=FG, font=("Segoe UI",10))
        s.map("TCheckbutton",           background=[("active",BG)])
        s.configure("TCombobox",        fieldbackground=BG2, foreground=FG,
                     selectbackground=BG2, selectforeground=FG, padding=4)
        s.map("TCombobox",
              fieldbackground=[("readonly",BG2),("disabled",BG3)],
              foreground=[("readonly",FG),("disabled","#9ca3af")],
              selectbackground=[("readonly",BG2)],
              selectforeground=[("readonly",FG)])
        s.configure("Treeview",         background=BG2, foreground=FG,
                     fieldbackground=BG2, rowheight=26, font=("Segoe UI",9))
        s.configure("Treeview.Heading", background=BG, foreground=ACC,
                     font=("Segoe UI",9,"bold"), relief="flat")
        s.map("Treeview",               background=[("selected","#bfdbfe")],
                                        foreground=[("selected",FG)])
        s.configure("TProgressbar",     troughcolor=BG2, background=ACC, thickness=8)
        s.configure("TNotebook",        background=BG, tabmargins=0)
        s.configure("TNotebook.Tab",    background=BG2, foreground=FG,
                     padding=[14,7], font=("Segoe UI",10))
        s.map("TNotebook.Tab",          background=[("selected",BG)],
                                        foreground=[("selected",ACC)])
        s.configure("TLabelframe",      background=BG, relief="solid",
                     borderwidth=1, bordercolor=BG3)
        s.configure("TLabelframe.Label",background=BG, foreground=ACC,
                     font=("Segoe UI",10,"bold"))
        s.configure("TSeparator",       background=BG3)

    # ── UI ────────────────────────────────────────────────────
    def _build_ui(self):
        ttk.Label(self, text="⛏  MC Pack Updater", style="Hdr.TLabel").pack(pady=(12,2))
        ttk.Label(self, text="Mod / ResourcePack / Shader を一括アップデート",
                   style="Sub.TLabel").pack(pady=(0,8))

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True, padx=12, pady=(0,4))

        t_set  = ttk.Frame(self._nb); self._nb.add(t_set,  text=" ⚙ 設定 ")
        t_list = ttk.Frame(self._nb); self._nb.add(t_list, text=" 📦 一覧 ")
        t_log  = ttk.Frame(self._nb); self._nb.add(t_log,  text=" 📋 ログ ")

        self._build_settings(t_set)
        self._build_lists(t_list)
        self._build_log(t_log)

        bar = ttk.Frame(self); bar.pack(fill="x", padx=12, pady=(0,8))
        self._progress   = ttk.Progressbar(bar, mode="determinate")
        self._progress.pack(side="left", fill="x", expand=True, padx=(0,10))
        self._prog_label = ttk.Label(bar, text="", width=34)
        self._prog_label.pack(side="left")
        self._cancel_btn = ttk.Button(bar, text="⏹ 中止", command=self._cancel,
                                       state="disabled")
        self._cancel_btn.pack(side="left", padx=(8,0))

    # ── 設定タブ（スクロール対応） ────────────────────────────
    def _build_settings(self, p):
        canvas = tk.Canvas(p, bg=BG, highlightthickness=0)
        vsb    = ttk.Scrollbar(p, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        f = ttk.Frame(canvas)
        win_id = canvas.create_window((0,0), window=f, anchor="nw")

        f.bind("<Configure>",      lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        def _wheel(e):
            # コンボボックス上ではスクロールしない
            if isinstance(e.widget, ttk.Combobox): return
            canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)

        PAD = dict(padx=14, pady=(0,8))

        # ── 起動構成 ──
        lf0 = ttk.LabelFrame(f, text="🚀  起動構成フォルダ")
        lf0.pack(fill="x", **PAD)
        note = ttk.Label(lf0, text="指定すると mods / resourcepacks / shaderpacks を自動検出します",
                          foreground=YEL, background=BG, font=("Segoe UI",8))
        note.pack(anchor="w", padx=10, pady=(4,0))
        r0 = ttk.Frame(lf0); r0.pack(fill="x", padx=10, pady=(4,8))
        ttk.Entry(r0, textvariable=self.profile_dir).pack(
            side="left", fill="x", expand=True, padx=(0,6))
        ttk.Button(r0, text="参照",
                    command=lambda: self._browse(self.profile_dir)).pack(side="left",padx=(0,6))
        ttk.Button(r0, text="自動検出して読み込む",
                    command=self._load_from_profile).pack(side="left",padx=(0,6))
        ttk.Button(r0, text="✕ リセット",
                    command=lambda: self.profile_dir.set("")).pack(side="left")

        # ── 個別フォルダ ──
        lf1 = ttk.LabelFrame(f, text="📁  個別フォルダ指定")
        lf1.pack(fill="x", **PAD)
        for lbl, var in [("🧩 Mods", self.mods_dir),
                          ("🎨 ResourcePacks", self.rp_dir),
                          ("✨ Shaders", self.shader_dir)]:
            row = ttk.Frame(lf1); row.pack(fill="x", padx=10, pady=3)
            ttk.Label(row, text=lbl, width=18).pack(side="left")
            ttk.Entry(row, textvariable=var).pack(side="left",fill="x",expand=True,padx=(0,6))
            ttk.Button(row, text="参照",
                        command=lambda v=var: self._browse(v)).pack(side="left",padx=(0,6))
            ttk.Button(row, text="✕",
                        command=lambda v=var: v.set(""), width=3).pack(side="left")

        # ── バージョン ──
        lf2 = ttk.LabelFrame(f, text="🎯  アップデート先")
        lf2.pack(fill="x", **PAD)
        r2 = ttk.Frame(lf2); r2.pack(fill="x", padx=10, pady=8)
        ttk.Label(r2, text="MCバージョン:").pack(side="left")
        self._ver_cb = ttk.Combobox(r2, textvariable=self.target_version,
                                     values=MC_VERSIONS_FALLBACK, width=12, state="readonly")
        self._ver_cb.pack(side="left", padx=(4,4))
        self._ver_status = ttk.Label(r2, text="🔄 取得中...",
                                      foreground=YEL, background=BG, font=("Segoe UI",8))
        self._ver_status.pack(side="left", padx=(0,14))
        ttk.Label(r2, text="Mod Loader:").pack(side="left")
        self._loader_cb = ttk.Combobox(r2, textvariable=self.target_loader,
                      values=LOADERS, width=12, state="readonly")
        self._loader_cb.pack(side="left",padx=(4,10))
        self._loader_cb.bind("<<ComboboxSelected>>", lambda _: self._filter_versions())
        ttk.Button(r2, text="✕ リセット",
                    command=lambda: (self.target_version.set(""),
                                     self.target_loader.set(""))).pack(side="left")

        # ── DL設定 ──
        lf3 = ttk.LabelFrame(f, text="🌐  ダウンロード設定")
        lf3.pack(fill="x", **PAD)
        r3 = ttk.Frame(lf3); r3.pack(fill="x", padx=10, pady=(8,4))
        ttk.Label(r3, text="モード:").pack(side="left")
        self._dl_mode_cb = ttk.Combobox(r3, textvariable=self.dl_mode,
                                         values=DL_MODES, width=24, state="readonly")
        self._dl_mode_cb.pack(side="left", padx=(4,0))
        self._dl_mode_cb.bind("<<ComboboxSelected>>", lambda _: self._update_mode_ui())
        self._mode_desc = ttk.Label(lf3, text="", foreground=YEL,
                                     background=BG, font=("Segoe UI",9))
        self._mode_desc.pack(anchor="w", padx=10, pady=(0,4))
        ttk.Separator(lf3, orient="horizontal").pack(fill="x", padx=10, pady=4)
        r4 = ttk.Frame(lf3); r4.pack(fill="x", padx=10, pady=(2,8))
        ttk.Label(r4, text="CurseForge APIキー:").pack(side="left")
        self._cf_entry = ttk.Entry(r4, textvariable=self.cf_api_key, show="*", width=38)
        self._cf_entry.pack(side="left", padx=(6,6))
        self._cf_show_btn = ttk.Button(r4, text="表示",
                                        command=self._toggle_cf_show, width=5)
        self._cf_show_btn.pack(side="left", padx=(0,6))
        ttk.Button(r4, text="取得方法 ↗",
                    command=lambda: webbrowser.open("https://console.curseforge.com/")).pack(side="left")
        self._update_mode_ui()

        # ── オプション ──
        lf4 = ttk.LabelFrame(f, text="⚙  オプション")
        lf4.pack(fill="x", **PAD)
        for txt, var in [
            ("アップデート後に古いファイルを削除する",                    self.delete_old),
            ("ダウンロード失敗したファイルを削除する（壊れたファイル除去）", self.delete_failed),
            ("前提Modが足りなければ自動でダウンロードする",               self.auto_deps),
        ]:
            ttk.Checkbutton(lf4, text=txt, variable=var).pack(padx=10, pady=2, anchor="w")

        # ── 操作ボタン ──
        lf5 = ttk.LabelFrame(f, text="▶  操作")
        lf5.pack(fill="x", padx=14, pady=(0,4))
        top_row = ttk.Frame(lf5); top_row.pack(fill="x", padx=10, pady=(8,4))
        ttk.Button(top_row, text="📂 全て読み込む",
                    command=self._load_all).pack(side="left",padx=(0,8))
        ttk.Button(top_row, text="🔄 全て一括アップデート",
                    command=self._start_all).pack(side="left")
        ttk.Separator(lf5, orient="horizontal").pack(fill="x", padx=10, pady=4)
        for lbl, load_cmd, upd_cmd in [
            ("🧩 Mod",          self._load_mods,   lambda: self._start_panel(self._mod_panel,   "Mod")),
            ("🎨 ResourcePack", self._load_rp,     lambda: self._start_panel(self._rp_panel,    "ResourcePack")),
            ("✨ Shader",        self._load_shader, lambda: self._start_panel(self._shader_panel,"Shader")),
        ]:
            row = ttk.Frame(lf5); row.pack(fill="x", padx=10, pady=3)
            ttk.Label(row, text=lbl, width=16).pack(side="left")
            ttk.Button(row, text="📂 読み込む",     command=load_cmd).pack(side="left",padx=(0,6))
            ttk.Button(row, text="⬇ アップデート", command=upd_cmd).pack(side="left")
        ttk.Frame(f, height=10).pack()

    # ── 一覧タブ（3列） ───────────────────────────────────────
    def _build_lists(self, p):
        p.columnconfigure(0, weight=1)
        p.columnconfigure(1, weight=1)
        p.columnconfigure(2, weight=1)
        p.rowconfigure(0, weight=1)

        # LabelFrame を先に作り、その中にパネルを直接生成する
        lf_mod    = ttk.LabelFrame(p, text="  🧩 Mod  ")
        lf_rp     = ttk.LabelFrame(p, text="  🎨 ResourcePack  ")
        lf_shader = ttk.LabelFrame(p, text="  ✨ Shader  ")
        lf_mod.grid(   row=0, column=0, sticky="nsew", padx=5, pady=5)
        lf_rp.grid(    row=0, column=1, sticky="nsew", padx=5, pady=5)
        lf_shader.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)

        self._mod_panel = FileListPanel(
            lf_mod, MR_MOD,
            load_fn=self._load_mods,
            update_fn=lambda: self._start_panel(self._mod_panel, "Mod"))
        self._mod_panel.pack(fill="both", expand=True)

        self._rp_panel = FileListPanel(
            lf_rp, MR_RP,
            load_fn=self._load_rp,
            update_fn=lambda: self._start_panel(self._rp_panel, "ResourcePack"))
        self._rp_panel.pack(fill="both", expand=True)

        self._shader_panel = FileListPanel(
            lf_shader, MR_SHADE,
            load_fn=self._load_shader,
            update_fn=lambda: self._start_panel(self._shader_panel, "Shader"))
        self._shader_panel.pack(fill="both", expand=True)

    # ── ログタブ（システム上段 + 3列下段） ───────────────────
    def _build_log(self, p):
        self._log_boxes = {}

        # 上段：システムログ
        lf_sys = ttk.LabelFrame(p, text="  🖥 システム  ")
        lf_sys.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=5, pady=(5,2))
        sys_box = scrolledtext.ScrolledText(
            lf_sys, bg="#ffffff", fg=FG,
            selectbackground="#bfdbfe", selectforeground=FG,
            insertbackground=FG, height=5,
            font=("Consolas",9), relief="flat", wrap="word")
        sys_box.pack(fill="both", expand=True, padx=4, pady=(4,0))
        for tag, color in [("ok",GRN),("err",RED),("info",ACC),("warn",YEL)]:
            sys_box.tag_config(tag, foreground=color)
        ttk.Button(lf_sys, text="クリア",
                    command=lambda b=sys_box: b.delete("1.0","end")).pack(pady=3)
        self._log_boxes["sys"] = sys_box

        # 下段：Mod / RP / Shader
        for col, (key, lbl) in enumerate([
            ("mod",    "🧩 Mod"),
            ("rp",     "🎨 ResourcePack"),
            ("shader", "✨ Shader"),
        ]):
            lf = ttk.LabelFrame(p, text=f"  {lbl}  ")
            lf.grid(row=1, column=col, sticky="nsew", padx=5, pady=(2,5))
            box = scrolledtext.ScrolledText(
                lf, bg="#ffffff", fg=FG,
                selectbackground="#bfdbfe", selectforeground=FG,
                insertbackground=FG,
                font=("Consolas",9), relief="flat", wrap="word")
            box.pack(fill="both", expand=True, padx=4, pady=(4,0))
            for tag, color in [("ok",GRN),("err",RED),("info",ACC),("warn",YEL)]:
                box.tag_config(tag, foreground=color)
            ttk.Button(lf, text="クリア",
                        command=lambda b=box: b.delete("1.0","end")).pack(pady=3)
            self._log_boxes[key] = box

        p.columnconfigure(0, weight=1)
        p.columnconfigure(1, weight=1)
        p.columnconfigure(2, weight=1)
        p.rowconfigure(0, weight=1)   # システム行
        p.rowconfigure(1, weight=3)   # Mod/RP/Shader行（広め）

    # ── ヘルパー ──────────────────────────────────────────────
    def _log(self, msg, tag="", key="mod"):
        box = self._log_boxes.get(key, self._log_boxes["mod"])
        def _do():
            box.insert("end", msg+"\n", tag)
            box.see("end")
        self.after(0, _do)

    def _set_status(self, msg):
        self.after(0, lambda: self._prog_label.config(text=msg))

    def _set_progress(self, v, maximum=None):
        def _do():
            if maximum is not None: self._progress.configure(maximum=maximum)
            self._progress.configure(value=v)
        self.after(0, _do)

    def _update_mode_ui(self):
        mode = self.dl_mode.get()
        desc = {
            DL_BOTH:     "Modrinthで検索 → なければCurseForgeも",
            DL_CF_FIRST: "CurseForgeで検索 → なければModrinthも（APIキー必須）",
            DL_MR:       "Modrinthのみ（APIキー不要）",
            DL_CF:       "CurseForgeのみ（APIキー必須）",
        }.get(mode,"")
        self._mode_desc.config(text=f"  ℹ {desc}")
        need_cf = mode in (DL_BOTH, DL_CF_FIRST, DL_CF)
        state   = "normal" if need_cf else "disabled"
        self._cf_entry.config(state=state)
        self._cf_show_btn.config(state=state)

    def _toggle_cf_show(self):
        self._cf_key_showing = not self._cf_key_showing
        self._cf_entry.config(show="" if self._cf_key_showing else "*")
        self._cf_show_btn.config(text="隠す" if self._cf_key_showing else "表示")

    def _browse(self, var):
        d = filedialog.askdirectory()
        if d: var.set(d)

    def _cancel(self):
        self._cancel_flag = True
        self._set_status("中止中...")
        self._cancel_btn.config(state="disabled")

    def _filter_versions(self):
        """Loader選択に応じてバージョン一覧をフィルタリング"""
        # 各Loaderの最小バージョン
        LOADER_MIN = {
            "forge":    (1, 1),
            "fabric":   (1, 14),
            "quilt":    (1, 16),
            "neoforge": (1, 20, 1),
        }
        loader = self.target_loader.get()
        min_ver = LOADER_MIN.get(loader)
        all_versions = self._ver_cb["values"]
        if not all_versions or not min_ver:
            return

        def ver_tuple(v):
            try:
                return tuple(int(x) for x in v.split("."))
            except Exception:
                return (0,)

        filtered = [v for v in all_versions if ver_tuple(v) >= min_ver]
        self._ver_cb["values"] = filtered
        # 現在の選択がフィルタ後リストにない場合は先頭に変更
        if self.target_version.get() not in filtered and filtered:
            self._ver_cb.set(filtered[0])
            self.target_version.set(filtered[0])

    def _validate_cf(self):
        if self.dl_mode.get() in (DL_BOTH, DL_CF_FIRST, DL_CF) and not self.cf_api_key.get().strip():
            messagebox.showerror("エラー","CurseForgeを使用するにはAPIキーが必要です")
            return False
        return True

    def _disable_combobox_wheel(self):
        def _block(e): return "break"
        def _bind(w):
            if isinstance(w, ttk.Combobox):
                w.bind("<MouseWheel>",_block)
                w.bind("<Button-4>",  _block)
                w.bind("<Button-5>",  _block)
            for c in w.winfo_children(): _bind(c)
        _bind(self)
        # バージョンコンボボックスは values 更新後も確実にブロック
        self._ver_cb.bind("<MouseWheel>", _block)
        self._ver_cb.bind("<Button-4>",   _block)
        self._ver_cb.bind("<Button-5>",   _block)

    # ── 読み込み ──────────────────────────────────────────────
    def _load_dir(self, dir_var, ext, panel, key, kind_label):
        d = dir_var.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror("エラー",
                f"有効な{kind_label}フォルダを指定してください\n（設定タブでフォルダを選択）")
            return False
        files = sorted(f for f in os.listdir(d) if f.lower().endswith(ext))
        if not files:
            messagebox.showinfo("情報", f"{ext}ファイルが見つかりませんでした")
            return False
        self._log(f"📂 {kind_label}: {len(files)} 個を解析中...", "info", "sys")
        items = []
        for fname in files:
            path = os.path.join(d, fname)
            if ext == ".jar":
                info = read_jar_meta(path)
            else:
                raw  = os.path.splitext(fname)[0]
                info = {"filename":fname, "path":path,
                        "name":clean_name(raw),   # バージョン番号を除去した検索名
                        "display_name": raw,       # 表示用は元の名前
                        "mod_id":"","version":"","loader":""}
            items.append(info)
        items.sort(key=lambda x: x.get("name","").lower())
        panel.populate(items)
        self._log(f"✅ {kind_label}: {len(items)} 件読み込み完了", "ok", "sys")
        return True

    def _load_mods(self):
        if self._load_dir(self.mods_dir, ".jar", self._mod_panel, "mod", "Mod"):
            self._nb.select(1)

    def _load_rp(self):
        if self._load_dir(self.rp_dir, ".zip", self._rp_panel, "rp", "ResourcePack"):
            self._nb.select(1)

    def _load_shader(self):
        if self._load_dir(self.shader_dir, ".zip", self._shader_panel, "shader", "Shader"):
            self._nb.select(1)

    def _load_all(self):
        self._load_mods()
        self._load_rp()
        self._load_shader()
        self._nb.select(1)

    def _load_from_profile(self):
        base = self.profile_dir.get().strip()
        if not base or not os.path.isdir(base):
            messagebox.showerror("エラー","有効な起動構成フォルダを指定してください")
            return
        mapping = {"mods":self.mods_dir, "resourcepacks":self.rp_dir, "shaderpacks":self.shader_dir}
        found = []
        for sub, var in mapping.items():
            path = os.path.join(base, sub)
            if os.path.isdir(path):
                var.set(path)
                found.append(sub)
        if not found:
            messagebox.showwarning("確認",
                f"mods / resourcepacks / shaderpacks が見つかりませんでした\n{base}")
            return
        self._log(f"🚀 起動構成検出: {base}", "info", "sys")
        for sub in found:
            self._log(f"   ✓ {sub}", "ok", "sys")
        self._load_all()

    # ── アップデート ──────────────────────────────────────────
    def _kind_key(self, mr_type):
        return {"mod":"mod","resourcepack":"rp","shader":"shader"}.get(mr_type,"mod")

    def _build_tasks(self, panel):
        dir_map = {MR_MOD:self.mods_dir.get(), MR_RP:self.rp_dir.get(),
                   MR_SHADE:self.shader_dir.get()}
        out_dir  = dir_map[panel.mr_type]
        cf_class = {MR_MOD:CF_MOD, MR_RP:CF_RP, MR_SHADE:CF_SHADE}[panel.mr_type]
        return [(it, out_dir, panel.mr_type, cf_class) for it in panel.get_selected()]

    def _start_panel(self, panel, label):
        if not self._validate_cf(): return
        tasks = self._build_tasks(panel)
        if not tasks:
            messagebox.showinfo("情報","アイテムが選択されていません"); return
        self._run_tasks(tasks)

    def _start_all(self):
        if not self._validate_cf(): return
        tasks = (self._build_tasks(self._mod_panel) +
                 self._build_tasks(self._rp_panel) +
                 self._build_tasks(self._shader_panel))
        if not tasks:
            messagebox.showinfo("情報","アイテムが選択されていません"); return
        self._run_tasks(tasks)

    def _run_tasks(self, tasks):
        if self._running:
            messagebox.showwarning("実行中","現在アップデート中です"); return
        self._running     = True
        self._cancel_flag = False
        self._set_progress(0, len(tasks))
        self._nb.select(2)
        self.after(0, lambda: self._cancel_btn.config(state="normal"))
        threading.Thread(target=self._worker,
                          args=(tasks, self.target_version.get(),
                                self.target_loader.get(),
                                self.dl_mode.get(),
                                self.cf_api_key.get().strip()),
                          daemon=True).start()

    # ── ワーカー ──────────────────────────────────────────────
    def _worker(self, tasks, mc_ver, loader, mode, cf_key):
        delete_old   = self.delete_old.get()
        delete_fail  = self.delete_failed.get()
        auto_deps    = self.auto_deps.get()
        done_deps    = set()

        # カテゴリ別に結果を収集
        results = {"mod":{"ok":[],"fail":[]},
                   "rp": {"ok":[],"fail":[]},
                   "shader":{"ok":[],"fail":[]}}

        for i, (item, out_dir, mr_type, cf_class) in enumerate(tasks):
            # 中止チェック
            if self._cancel_flag:
                self._log("\n⏹ ユーザーによって中止されました", "warn", "mod")
                break

            name = item.get("name", item["filename"])
            key  = self._kind_key(mr_type)
            kind = {"mod":"Mod","rp":"RP","shader":"Shader"}[key]

            self._set_status(f"{i+1}/{len(tasks)}: [{kind}] {name[:22]}")
            self._log(f"\n── {name} ──", "info", key)

            def _log(msg, tag="", _key=key): self._log(msg, tag, _key)

            dl_url, dl_fname, source, version_obj = find_dl_info(
                name, item.get("mod_id",""), item.get("path"),
                mc_ver, loader, mode, cf_key,
                mr_type, cf_class, _log)

            if dl_url and dl_fname:
                dest    = os.path.join(out_dir, dl_fname)
                success = self._do_download(dl_url, dest, name, source,
                                             item.get("path"), delete_old, delete_fail, key)
                if success:
                    results[key]["ok"].append(name)
                    # 前提Mod
                    if mr_type == MR_MOD and auto_deps and version_obj:
                        for dep_pid in mr_get_deps(version_obj, mc_ver, loader):
                            if dep_pid in done_deps: continue
                            done_deps.add(dep_pid)
                            self._log(f"  🔗 依存Mod: {dep_pid}", "info", key)
                            try:
                                vs = mr_get_versions(dep_pid, mc_ver, loader)
                                if vs:
                                    du = df = None
                                    for fi in vs[0].get("files",[]):
                                        if fi.get("primary") or not du:
                                            du,df = fi["url"],fi["filename"]
                                            if fi.get("primary"): break
                                    if du and df:
                                        ddest = os.path.join(out_dir, df)
                                        if os.path.exists(ddest):
                                            self._log(f"  🔗 既存: {df}", "ok", key)
                                        else:
                                            self._do_download(du, ddest, df, "Modrinth",
                                                               None, False, delete_fail, key)
                                            dep_item = {"filename":df,"path":ddest,
                                                        "name":df,"mod_id":"","version":"","loader":""}
                                            self.after(0, lambda di=dep_item:
                                                self._mod_panel.add_item(di,"dep"))
                                            results[key]["ok"].append(f"[依存] {df}")
                            except Exception as e:
                                self._log(f"  🔗 依存エラー: {e}", "err", key)
                else:
                    results[key]["fail"].append(name)
            else:
                results[key]["fail"].append(name)
                self._log(f"  ❌ スキップ（対応バージョンなし）", "err", key)
                if delete_fail and item.get("path") and os.path.exists(item["path"]):
                    try:
                        os.remove(item["path"])
                        self._log(f"  🗑 失敗ファイル削除: {item['filename']}", "warn", key)
                    except Exception: pass

            self._set_progress(i+1)

        # ── カテゴリ別サマリー ──
        total_ok   = sum(len(v["ok"])   for v in results.values())
        total_fail = sum(len(v["fail"]) for v in results.values())

        for key, lbl in [("mod","🧩 Mod"), ("rp","🎨 ResourcePack"), ("shader","✨ Shader")]:
            ok   = results[key]["ok"]
            fail = results[key]["fail"]
            if not ok and not fail: continue
            self._log(f"\n{'═'*40}", "info", key)
            self._log(f"{lbl} 結果", "info", key)
            self._log(f"✅ 成功: {len(ok)} 件", "ok", key)
            for n in ok:   self._log(f"   ✓ {n}", "ok", key)
            if fail:
                self._log(f"❌ 失敗: {len(fail)} 件", "err", key)
                for n in fail: self._log(f"   ✗ {n}", "err", key)
            else:
                self._log("🎉 全て完了！", "ok", key)

        self._set_status("完了" if not self._cancel_flag else "中止")
        self._running = False
        self.after(0, lambda: self._cancel_btn.config(state="disabled"))

        msg = f"✅ 成功: {total_ok} 件\n❌ 失敗: {total_fail} 件"
        if total_fail:
            msg += "\n"
            for key, lbl in [("mod","🧩 Mod"),("rp","🎨 ResourcePack"),("shader","✨ Shader")]:
                if results[key]["fail"]:
                    msg += f"\n{lbl}:\n" + "\n".join(f"  • {n}" for n in results[key]["fail"])
        self.after(0, lambda: messagebox.showinfo("完了", msg))

    def _do_download(self, url, dest, name, source, old_path,
                     delete_old, delete_fail, log_key):
        try:
            self._log(f"  ⬇ DL中 [{source}]: {os.path.basename(dest)}", "", log_key)
            def _pcb(p): self._set_status(f"DL: {name[:18]} {p*100:.0f}%")
            download_file(url, dest, _pcb)
            if delete_old and old_path and os.path.exists(old_path):
                if os.path.abspath(dest) != os.path.abspath(old_path):
                    os.remove(old_path)
                    self._log(f"  🗑 旧ファイル削除: {os.path.basename(old_path)}", "", log_key)
            self._log(f"  ✅ 完了", "ok", log_key)
            return True
        except Exception as e:
            self._log(f"  ❌ DL失敗: {e}", "err", log_key)
            if os.path.exists(dest):
                try: os.remove(dest)
                except Exception: pass
            if delete_fail and old_path and os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    self._log(f"  🗑 失敗ファイル削除: {os.path.basename(old_path)}", "warn", log_key)
                except Exception: pass
            return False

    # ── MCバージョン取得 ──────────────────────────────────────
    def _fetch_versions_bg(self):
        versions = fetch_mc_versions()
        def _upd():
            cur = self.target_version.get()
            self._ver_cb["values"] = versions
            self._ver_cb.set(cur if cur in versions else versions[0])
            self.target_version.set(self._ver_cb.get())
            self._filter_versions()  # Loaderに応じてフィルタ適用
            # values更新後にホイールを再ブロック
            self._ver_cb.bind("<MouseWheel>", lambda e: "break")
            self._ver_cb.bind("<Button-4>",   lambda e: "break")
            self._ver_cb.bind("<Button-5>",   lambda e: "break")
            if versions == MC_VERSIONS_FALLBACK:
                self._ver_status.config(text="⚠ オフライン", foreground=YEL)
                self._log("⚠ バージョン取得失敗 → フォールバック使用", "warn", "sys")
            else:
                self._ver_status.config(text=f"✅ {len(versions)} 件", foreground=GRN)
                self._log(f"✅ MCバージョン {len(versions)} 件取得（最新: {versions[0]}）","ok","sys")
        self.after(0, _upd)

    # ── 終了 ──────────────────────────────────────────────────
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
        })
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
