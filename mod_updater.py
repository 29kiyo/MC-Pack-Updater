import os
import re
import sys
import json
import zipfile
import hashlib
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import urllib.request
import urllib.parse

# ── 定数 ──────────────────────────────────────────────────────
MODRINTH_API   = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"
CONFIG_FILE    = os.path.join(os.path.expanduser("~"), ".mc_mod_updater_config.json")

MC_VERSIONS_FALLBACK = [
    "1.21.4","1.21.3","1.21.1","1.21",
    "1.20.6","1.20.4","1.20.2","1.20.1","1.20",
    "1.19.4","1.19.3","1.19.2","1.19.1","1.19",
    "1.18.2","1.18.1","1.18","1.17.1","1.17",
    "1.16.5","1.16.4","1.16.3","1.16.2","1.16.1",
    "1.15.2","1.12.2",
]
LOADERS = ["fabric", "forge", "neoforge", "quilt"]

DL_MODE_BOTH       = "両方（Modrinth優先）"
DL_MODE_MODRINTH   = "Modrinthのみ"
DL_MODE_CURSEFORGE = "CurseForgeのみ"
DL_MODES = [DL_MODE_BOTH, DL_MODE_MODRINTH, DL_MODE_CURSEFORGE]

CF_LOADER_MAP  = {"forge":1,"fabric":4,"quilt":5,"neoforge":6}
CF_GAME_ID     = 432
CF_CLASS_MOD   = 6
CF_CLASS_RP    = 12
CF_CLASS_SHADER= 6552
MR_TYPE_MOD    = "mod"
MR_TYPE_RP     = "resourcepack"
MR_TYPE_SHADER = "shader"

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
    req.add_header("User-Agent", "MC-Mod-Updater/4.0")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def download_file(url, dest, progress_cb=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MC-Mod-Updater/4.0")
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
        def vk(v):
            return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v))
        releases.sort(key=vk, reverse=True)
        return releases if releases else MC_VERSIONS_FALLBACK
    except Exception:
        return MC_VERSIONS_FALLBACK

# ── JAR解析 ───────────────────────────────────────────────────
def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def read_jar_meta(jar_path):
    info = {"filename": os.path.basename(jar_path), "path": jar_path,
            "name": os.path.basename(jar_path), "mod_id": "", "version": "", "loader": "不明"}
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            names = zf.namelist()
            for meta in ("fabric.mod.json", "quilt.mod.json"):
                if meta in names:
                    d = json.loads(zf.read(meta).decode("utf-8", errors="ignore"))
                    info.update({"mod_id": d.get("id",""), "name": d.get("name", info["filename"]),
                                 "version": d.get("version",""),
                                 "loader": "quilt" if meta.startswith("quilt") else "fabric"})
                    return info
            for meta in ("META-INF/mods.toml", "META-INF/neoforge.mods.toml"):
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
            "query":  name,
            "facets": json.dumps([["project_type:" + project_type]]),
            "limit":  5,
        })
        d = http_get(f"{MODRINTH_API}/search?{params}")
        hits = d.get("hits", [])
        if not hits: return None
        for h in hits:
            if h.get("title","").lower() == name.lower(): return h["project_id"]
        return hits[0]["project_id"]
    except Exception:
        return None

def mr_get_versions(pid, mc_ver, loader):
    try:
        params = urllib.parse.urlencode({
            "game_versions": json.dumps([mc_ver]),
            "loaders":       json.dumps([loader]),
        })
        return http_get(f"{MODRINTH_API}/project/{pid}/version?{params}")
    except Exception:
        return []

def mr_get_deps(version_obj, mc_ver, loader):
    return [d.get("project_id") for d in version_obj.get("dependencies", [])
            if d.get("dependency_type") == "required" and d.get("project_id")]

# ── CurseForge ────────────────────────────────────────────────
def _cf_req(url, api_key):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MC-Mod-Updater/4.0")
    req.add_header("x-api-key",  api_key)
    req.add_header("Accept",     "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def cf_search(name, api_key, class_id):
    params = urllib.parse.urlencode({
        "gameId": CF_GAME_ID, "classId": class_id,
        "searchFilter": name, "pageSize": 5,
        "sortField": 2, "sortOrder": "desc",
    })
    try:
        d = _cf_req(f"{CURSEFORGE_API}/mods/search?{params}", api_key)
        results = d.get("data", [])
        if not results: return None
        for r in results:
            if r.get("name","").lower() == name.lower(): return r["id"]
        return results[0]["id"]
    except Exception:
        return None

def cf_get_file(cf_id, mc_ver, loader, api_key):
    params = urllib.parse.urlencode({
        "gameVersion": mc_ver, "modLoaderType": CF_LOADER_MAP.get(loader, 0), "pageSize": 10,
    })
    try:
        d = _cf_req(f"{CURSEFORGE_API}/mods/{cf_id}/files?{params}", api_key)
        files = d.get("data", [])
        files.sort(key=lambda f: (f.get("releaseType", 9), -f.get("id", 0)))
        return files[0] if files else None
    except Exception:
        return None

# ── 統合検索 ──────────────────────────────────────────────────
def find_dl_info(name, mod_id, path, mc_ver, loader, mode, cf_key,
                 mr_type, cf_class, log_cb):
    do_mr = mode in (DL_MODE_BOTH, DL_MODE_MODRINTH)
    do_cf = mode in (DL_MODE_BOTH, DL_MODE_CURSEFORGE)
    dl_url = dl_fname = source = None
    version_obj = None

    if do_mr:
        try:
            sha1 = sha1_file(path) if path and os.path.exists(path) else None
            pid  = mr_find_project(sha1, mod_id, name, mr_type)
            if pid:
                vs = mr_get_versions(pid, mc_ver, loader)
                if vs:
                    version_obj = vs[0]
                    for fi in vs[0].get("files", []):
                        if fi.get("primary") or not dl_url:
                            dl_url, dl_fname, source = fi["url"], fi["filename"], "Modrinth"
                            if fi.get("primary"): break
                    log_cb(f"  ✓ Modrinth: {dl_fname}", "ok")
                else:
                    log_cb(f"  Modrinth: {mc_ver}/{loader} 対応なし", "warn")
            else:
                log_cb(f"  Modrinth: 見つからず", "warn")
        except Exception as e:
            log_cb(f"  Modrinth エラー: {e}", "err")

    if do_cf and not dl_url:
        try:
            cf_id = cf_search(name, cf_key, cf_class)
            if cf_id:
                fi = cf_get_file(cf_id, mc_ver, loader, cf_key)
                if fi:
                    dl_url, dl_fname, source = fi.get("downloadUrl"), fi.get("fileName"), "CurseForge"
                    log_cb(f"  ✓ CurseForge: {dl_fname}", "ok")
                else:
                    log_cb(f"  CurseForge: {mc_ver}/{loader} 対応なし", "warn")
            else:
                log_cb(f"  CurseForge: 見つからず", "warn")
        except Exception as e:
            log_cb(f"  CurseForge エラー: {e}", "err")

    return dl_url, dl_fname, source, version_obj

# ══════════════════════════════════════════════════════════════
# リスト用ウィジェット
# ══════════════════════════════════════════════════════════════
class FileListPanel(ttk.Frame):
    """Mod / RP / Shader 共通のリストパネル"""

    def __init__(self, parent, label, mr_type, cf_class,
                 file_ext, load_fn, update_fn, **kw):
        super().__init__(parent, **kw)
        self.label    = label
        self.mr_type  = mr_type
        self.cf_class = cf_class
        self.file_ext = file_ext   # ".jar" or ".zip"
        self._load_fn   = load_fn
        self._update_fn = update_fn
        self.items = []   # [{filename, name, path, mod_id, version, loader}]
        self._build()

    def _build(self):
        # ── ツールバー ──
        top = ttk.Frame(self); top.pack(fill="x", padx=6, pady=4)
        ttk.Button(top, text="全選択",  command=lambda: self._sel_all(True)).pack(side="left", padx=(0,4))
        ttk.Button(top, text="全解除",  command=lambda: self._sel_all(False)).pack(side="left", padx=(0,12))
        ttk.Button(top, text=f"📂 読み込む",
                    command=self._load_fn).pack(side="left", padx=(0,6))
        ttk.Button(top, text=f"⬇ アップデート",
                    command=self._update_fn).pack(side="left")
        self._sel_label = ttk.Label(top, text="0 / 0 件")
        self._sel_label.pack(side="right", padx=6)

        # ── ツリー ──
        if self.mr_type == MR_TYPE_MOD:
            cols = ("chk","name","mod_id","version","loader")
            heads = [("chk","✔",38),("name","名前",220),
                     ("mod_id","Mod ID",150),("version","バージョン",100),("loader","Loader",75)]
        else:
            cols = ("chk","name","version")
            heads = [("chk","✔",38),("name","名前",300),("version","バージョン",100)]

        self._tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="none")
        for cid, lbl, w in heads:
            self._tree.heading(cid, text=lbl)
            self._tree.column(cid, width=w, anchor="center" if cid=="chk" else "w",
                               stretch=(cid=="name"))
        self._tree.tag_configure("even", background=BG2)
        self._tree.tag_configure("odd",  background="#f0f0eb")
        self._tree.tag_configure("dep",  background="#dbeafe")

        vsb = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(6,0), pady=(0,6))
        vsb.pack(side="left", fill="y", pady=(0,6), padx=(0,6))
        self._tree.bind("<Button-1>", self._on_click)

    def populate(self, items):
        """items: [{filename, name, path, mod_id, version, loader}]"""
        for row in self._tree.get_children():
            self._tree.delete(row)
        self.items = items
        for i, it in enumerate(items):
            tag = "even" if i % 2 == 0 else "odd"
            iid = it["filename"]
            if self.mr_type == MR_TYPE_MOD:
                vals = ("☑", it.get("name", iid), it.get("mod_id","?"),
                        it.get("version","?"), it.get("loader","?"))
            else:
                vals = ("☑", it.get("name", iid), it.get("version","?"))
            self._tree.insert("", "end", iid=iid, tags=(tag,), values=vals)
        self._upd_label()

    def add_item(self, item, tag="dep"):
        iid = item["filename"]
        if self._tree.exists(iid): return
        self.items.append(item)
        if self.mr_type == MR_TYPE_MOD:
            vals = ("☑", item.get("name", iid), item.get("mod_id",""),
                    item.get("version",""), item.get("loader",""))
        else:
            vals = ("☑", item.get("name", iid), item.get("version",""))
        self._tree.insert("", "end", iid=iid, tags=(tag,), values=vals)
        self._upd_label()

    def get_selected(self):
        return [it for it in self.items
                if self._tree.exists(it["filename"]) and
                   self._tree.set(it["filename"],"chk") == "☑"]

    def _on_click(self, e):
        row = self._tree.identify_row(e.y)
        col = self._tree.identify_column(e.x)
        if row and col == "#1":
            cur = self._tree.set(row, "chk")
            self._tree.set(row, "chk", "☑" if cur == "☐" else "☐")
            self._upd_label()

    def _sel_all(self, v):
        for row in self._tree.get_children():
            self._tree.set(row, "chk", "☑" if v else "☐")
        self._upd_label()

    def _upd_label(self):
        rows = self._tree.get_children()
        sel  = sum(1 for r in rows if self._tree.set(r,"chk") == "☑")
        self._sel_label.config(text=f"{sel} / {len(rows)} 件選択")


# ══════════════════════════════════════════════════════════════
# メインアプリ
# ══════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("⛏ MC Mod Updater")
        self.geometry("1100x760")
        self.configure(bg=BG)
        self.resizable(True, True)

        cfg = load_config()
        self.target_version = tk.StringVar(value=cfg.get("target_version","1.21.4"))
        self.target_loader  = tk.StringVar(value=cfg.get("target_loader","fabric"))
        self.cf_api_key     = tk.StringVar(value=cfg.get("cf_api_key",""))
        self.dl_mode        = tk.StringVar(value=cfg.get("dl_mode", DL_MODE_BOTH))
        # フォルダ（起動構成 or 個別）
        self.profile_dir    = tk.StringVar(value=cfg.get("profile_dir",""))
        self.mods_dir       = tk.StringVar(value=cfg.get("mods_dir",""))
        self.rp_dir         = tk.StringVar(value=cfg.get("rp_dir",""))
        self.shader_dir     = tk.StringVar(value=cfg.get("shader_dir",""))
        # オプション
        self.delete_old     = tk.BooleanVar(value=cfg.get("delete_old",False))
        self.delete_failed  = tk.BooleanVar(value=cfg.get("delete_failed",False))
        self.auto_deps      = tk.BooleanVar(value=cfg.get("auto_deps",True))

        self._cf_key_showing = False
        self._running        = False

        self._apply_style()
        self._build_ui()
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
        s.map("Treeview",               background=[("selected",BG3)])
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
        ttk.Label(self, text="⛏  MC Mod Updater", style="Hdr.TLabel").pack(pady=(12,2))
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

        # 下部バー
        bar = ttk.Frame(self); bar.pack(fill="x", padx=12, pady=(0,8))
        self._progress   = ttk.Progressbar(bar, mode="determinate")
        self._progress.pack(side="left", fill="x", expand=True, padx=(0,10))
        self._prog_label = ttk.Label(bar, text="", width=34)
        self._prog_label.pack(side="left")

    # ── 設定タブ ──────────────────────────────────────────────
    def _build_settings(self, p):
        f = ttk.Frame(p); f.pack(fill="both", expand=True, padx=14, pady=10)

        # ── 起動構成フォルダ ──
        lf0 = ttk.LabelFrame(f, text="🚀  起動構成フォルダ（1つ指定で mods / resourcepacks / shaderpacks を自動検出）")
        lf0.pack(fill="x", pady=(0,8))
        r0 = ttk.Frame(lf0); r0.pack(fill="x", padx=10, pady=8)
        ttk.Entry(r0, textvariable=self.profile_dir).pack(
            side="left", fill="x", expand=True, padx=(0,6))
        ttk.Button(r0, text="参照",
                    command=lambda: self._browse(self.profile_dir)).pack(side="left", padx=(0,6))
        ttk.Button(r0, text="自動検出して読み込む",
                    command=self._load_from_profile).pack(side="left")

        # ── 個別フォルダ ──
        lf1 = ttk.LabelFrame(f, text="📁  個別フォルダ指定")
        lf1.pack(fill="x", pady=(0,8))
        folders = [
            ("🧩 Mods",         self.mods_dir),
            ("🎨 ResourcePacks", self.rp_dir),
            ("✨ Shaders",       self.shader_dir),
        ]
        for lbl, var in folders:
            row = ttk.Frame(lf1); row.pack(fill="x", padx=10, pady=3)
            ttk.Label(row, text=lbl, width=18).pack(side="left")
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=(0,6))
            ttk.Button(row, text="参照",
                        command=lambda v=var: self._browse(v)).pack(side="left")

        # ── バージョン ──
        lf2 = ttk.LabelFrame(f, text="🎯  アップデート先")
        lf2.pack(fill="x", pady=(0,8))
        r2 = ttk.Frame(lf2); r2.pack(fill="x", padx=10, pady=8)
        ttk.Label(r2, text="MCバージョン:").pack(side="left")
        self._ver_cb = ttk.Combobox(r2, textvariable=self.target_version,
                                     values=MC_VERSIONS_FALLBACK, width=12, state="readonly")
        self._ver_cb.pack(side="left", padx=(4,4))
        self._ver_status = ttk.Label(r2, text="🔄 取得中...",
                                      foreground=YEL, background=BG, font=("Segoe UI",8))
        self._ver_status.pack(side="left", padx=(0,18))
        ttk.Label(r2, text="Mod Loader:").pack(side="left")
        ttk.Combobox(r2, textvariable=self.target_loader,
                      values=LOADERS, width=12, state="readonly").pack(side="left", padx=(4,0))

        # ── DL設定 ──
        lf3 = ttk.LabelFrame(f, text="🌐  ダウンロード設定")
        lf3.pack(fill="x", pady=(0,8))
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
        self._cf_entry = ttk.Entry(r4, textvariable=self.cf_api_key, show="*", width=40)
        self._cf_entry.pack(side="left", padx=(6,6))
        self._cf_show_btn = ttk.Button(r4, text="表示",
                                        command=self._toggle_cf_show, width=5)
        self._cf_show_btn.pack(side="left", padx=(0,6))
        ttk.Button(r4, text="取得方法 ↗",
                    command=lambda: __import__("webbrowser").open(
                        "https://console.curseforge.com/")).pack(side="left")
        self._update_mode_ui()

        # ── オプション ──
        lf4 = ttk.LabelFrame(f, text="⚙  オプション")
        lf4.pack(fill="x", pady=(0,10))
        for txt, var in [
            ("アップデート後に古いファイルを削除する",             self.delete_old),
            ("ダウンロード失敗したファイルを削除する（壊れたファイル除去）", self.delete_failed),
            ("前提Modが足りなければ自動でダウンロードする",        self.auto_deps),
        ]:
            ttk.Checkbutton(lf4, text=txt, variable=var).pack(padx=10, pady=2, anchor="w")

        # ── 一括ボタン ──
        br = ttk.Frame(f); br.pack(fill="x", pady=(4,0))
        ttk.Button(br, text="🔄 全て一括アップデート",
                    command=self._start_all).pack(side="left")

    # ── 一覧タブ（3列） ───────────────────────────────────────
    def _build_lists(self, p):
        # 横に3分割
        self._mod_panel = FileListPanel(
            p, "Mod", MR_TYPE_MOD, CF_CLASS_MOD, ".jar",
            load_fn=self._load_mods,
            update_fn=lambda: self._start_panel(self._mod_panel))
        self._rp_panel = FileListPanel(
            p, "ResourcePack", MR_TYPE_RP, CF_CLASS_RP, ".zip",
            load_fn=self._load_rp,
            update_fn=lambda: self._start_panel(self._rp_panel))
        self._shader_panel = FileListPanel(
            p, "Shader", MR_TYPE_SHADER, CF_CLASS_SHADER, ".zip",
            load_fn=self._load_shader,
            update_fn=lambda: self._start_panel(self._shader_panel))

        # ラベル付きで横並び
        for panel, lbl, col in [
            (self._mod_panel,    "🧩 Mod",         0),
            (self._rp_panel,     "🎨 ResourcePack", 1),
            (self._shader_panel, "✨ Shader",        2),
        ]:
            wrapper = ttk.LabelFrame(p, text=f"  {lbl}  ")
            wrapper.grid(row=0, column=col, sticky="nsew", padx=5, pady=5)
            panel.pack(in_=wrapper, fill="both", expand=True)

        p.columnconfigure(0, weight=1)
        p.columnconfigure(1, weight=1)
        p.columnconfigure(2, weight=1)
        p.rowconfigure(0, weight=1)

    # ── ログタブ ──────────────────────────────────────────────
    def _build_log(self, p):
        self._log_box = scrolledtext.ScrolledText(
            p, bg="#ffffff", fg=FG, insertbackground=FG,
            font=("Consolas",9), relief="flat", wrap="word")
        self._log_box.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, color in [("ok",GRN),("err",RED),("info",ACC),("warn",YEL)]:
            self._log_box.tag_config(tag, foreground=color)
        ttk.Button(p, text="ログをクリア",
                    command=lambda: self._log_box.delete("1.0","end")).pack(pady=(0,8))

    # ── ヘルパー ──────────────────────────────────────────────
    def _update_mode_ui(self):
        mode = self.dl_mode.get()
        desc = {
            DL_MODE_BOTH:       "Modrinthで検索 → なければCurseForgeも検索",
            DL_MODE_MODRINTH:   "Modrinthのみ（APIキー不要）",
            DL_MODE_CURSEFORGE: "CurseForgeのみ（APIキー必須）",
        }.get(mode, "")
        self._mode_desc.config(text=f"  ℹ {desc}")
        need_cf = mode in (DL_MODE_BOTH, DL_MODE_CURSEFORGE)
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

    def _log(self, msg, tag=""):
        def _do():
            self._log_box.insert("end", msg+"\n", tag)
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

    def _validate_cf(self):
        mode = self.dl_mode.get()
        if mode in (DL_MODE_BOTH, DL_MODE_CURSEFORGE) and not self.cf_api_key.get().strip():
            messagebox.showerror("エラー", "CurseForgeを使用するにはAPIキーが必要です")
            return False
        return True

    # ── 読み込み ──────────────────────────────────────────────
    def _load_from_profile(self):
        """起動構成フォルダから mods / resourcepacks / shaderpacks を自動検出"""
        base = self.profile_dir.get().strip()
        if not base or not os.path.isdir(base):
            messagebox.showerror("エラー", "有効な起動構成フォルダを指定してください")
            return
        # サブフォルダ候補
        mapping = {
            "mods":         self.mods_dir,
            "resourcepacks":self.rp_dir,
            "shaderpacks":  self.shader_dir,
        }
        found = []
        for sub, var in mapping.items():
            path = os.path.join(base, sub)
            if os.path.isdir(path):
                var.set(path)
                found.append(sub)
        if not found:
            messagebox.showwarning("確認",
                "mods / resourcepacks / shaderpacks フォルダが見つかりませんでした\n"
                f"場所: {base}")
            return
        self._log(f"🚀 起動構成を検出: {base}", "info")
        for sub in found:
            self._log(f"   ✓ {sub}", "ok")
        # 全部読み込む
        self._load_mods()
        self._load_rp()
        self._load_shader()

    def _load_dir(self, dir_var, ext, panel, kind_label):
        d = dir_var.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror("エラー", f"有効な{kind_label}フォルダを指定してください\n（設定タブでフォルダを選択してください）")
            return
        files = [f for f in os.listdir(d) if f.lower().endswith(ext)]
        if not files:
            messagebox.showinfo("情報", f"{ext}ファイルが見つかりませんでした")
            return
        self._log(f"📂 {kind_label}: {len(files)} 個を解析中...", "info")
        items = []
        for f in sorted(files):
            path = os.path.join(d, f)
            if ext == ".jar":
                info = read_jar_meta(path)
            else:
                name = os.path.splitext(f)[0]
                info = {"filename": f, "path": path, "name": name,
                        "mod_id": "", "version": "", "loader": ""}
            items.append(info)
        panel.populate(items)
        self._log(f"✅ {kind_label}: {len(items)} 件読み込み完了", "ok")

    def _load_mods(self):
        self._load_dir(self.mods_dir, ".jar", self._mod_panel, "Mod")

    def _load_rp(self):
        self._load_dir(self.rp_dir, ".zip", self._rp_panel, "ResourcePack")

    def _load_shader(self):
        self._load_dir(self.shader_dir, ".zip", self._shader_panel, "Shader")

    # ── アップデート ──────────────────────────────────────────
    def _build_tasks(self, panel):
        """パネルの選択済みアイテムをタスクリストに変換"""
        dir_map = {
            MR_TYPE_MOD:    self.mods_dir.get(),
            MR_TYPE_RP:     self.rp_dir.get(),
            MR_TYPE_SHADER: self.shader_dir.get(),
        }
        out_dir = dir_map[panel.mr_type]
        return [(it, out_dir, panel.mr_type, panel.cf_class)
                for it in panel.get_selected()]

    def _start_panel(self, panel):
        if not self._validate_cf(): return
        tasks = self._build_tasks(panel)
        if not tasks:
            messagebox.showinfo("情報", "アイテムが選択されていません"); return
        self._run_tasks(tasks)

    def _start_all(self):
        if not self._validate_cf(): return
        tasks = (self._build_tasks(self._mod_panel) +
                 self._build_tasks(self._rp_panel) +
                 self._build_tasks(self._shader_panel))
        if not tasks:
            messagebox.showinfo("情報", "アイテムが選択されていません"); return
        self._run_tasks(tasks)

    def _run_tasks(self, tasks):
        if self._running:
            messagebox.showwarning("実行中", "現在アップデート中です"); return
        self._running = True
        self._set_progress(0, len(tasks))
        self._nb.select(2)
        mc_ver = self.target_version.get()
        loader = self.target_loader.get()
        mode   = self.dl_mode.get()
        cf_key = self.cf_api_key.get().strip()
        threading.Thread(target=self._worker,
                          args=(tasks, mc_ver, loader, mode, cf_key),
                          daemon=True).start()

    # ── ワーカー ──────────────────────────────────────────────
    def _worker(self, tasks, mc_ver, loader, mode, cf_key):
        delete_old    = self.delete_old.get()
        delete_failed = self.delete_failed.get()
        auto_deps     = self.auto_deps.get()
        ok_list = []; fail_list = []
        done_deps = set()

        for i, (item, out_dir, mr_type, cf_class) in enumerate(tasks):
            name = item.get("name", item["filename"])
            kind = {"mod":"Mod","resourcepack":"RP","shader":"Shader"}.get(mr_type, mr_type)
            self._set_status(f"{i+1}/{len(tasks)}: [{kind}] {name[:22]}")
            self._log(f"\n── [{kind}] {name} ──", "info")

            dl_url, dl_fname, source, version_obj = find_dl_info(
                name, item.get("mod_id",""), item.get("path"),
                mc_ver, loader, mode, cf_key,
                mr_type, cf_class, self._log)

            if dl_url and dl_fname:
                dest    = os.path.join(out_dir, dl_fname)
                success = self._do_download(dl_url, dest, name, source,
                                             item.get("path"), delete_old, delete_failed)
                if success:
                    ok_list.append(f"[{kind}] {name}")
                    # 前提Mod
                    if mr_type == MR_TYPE_MOD and auto_deps and version_obj:
                        for dep_pid in mr_get_deps(version_obj, mc_ver, loader):
                            if dep_pid in done_deps: continue
                            done_deps.add(dep_pid)
                            self._log(f"  🔗 依存Mod: {dep_pid}", "info")
                            try:
                                vs = mr_get_versions(dep_pid, mc_ver, loader)
                                if vs:
                                    dep_files = vs[0].get("files", [])
                                    du = df = None
                                    for fi in dep_files:
                                        if fi.get("primary") or not du:
                                            du, df = fi["url"], fi["filename"]
                                            if fi.get("primary"): break
                                    if du and df:
                                        ddest = os.path.join(out_dir, df)
                                        if os.path.exists(ddest):
                                            self._log(f"  🔗 既存: {df}", "ok")
                                        else:
                                            self._do_download(du, ddest, df, "Modrinth",
                                                               None, False, delete_failed)
                                            dep_item = {"filename": df, "path": ddest,
                                                        "name": df, "mod_id":"", "version":"","loader":""}
                                            self.after(0, lambda di=dep_item:
                                                self._mod_panel.add_item(di, "dep"))
                                            ok_list.append(f"[依存] {df}")
                            except Exception as e:
                                self._log(f"  🔗 依存エラー: {e}", "err")
                else:
                    fail_list.append(name)
            else:
                fail_list.append(name)
                self._log(f"  ❌ スキップ（対応バージョンなし）", "err")
                if delete_failed and item.get("path") and os.path.exists(item["path"]):
                    try:
                        os.remove(item["path"])
                        self._log(f"  🗑 失敗ファイル削除: {item['filename']}", "warn")
                    except Exception: pass

            self._set_progress(i + 1)

        # サマリー
        self._log(f"\n{'═'*50}", "info")
        self._log(f"✅ 成功: {len(ok_list)} 件", "ok")
        for n in ok_list: self._log(f"   ✓ {n}", "ok")
        if fail_list:
            self._log(f"\n❌ 失敗: {len(fail_list)} 件", "err")
            for n in fail_list: self._log(f"   ✗ {n}", "err")
        else:
            self._log("\n🎉 全て完了しました！", "ok")
        self._set_status("完了")
        self._running = False
        msg = f"✅ 成功: {len(ok_list)} 件\n❌ 失敗: {len(fail_list)} 件"
        if fail_list:
            msg += "\n\n失敗:\n" + "\n".join(f"• {n}" for n in fail_list)
        self.after(0, lambda: messagebox.showinfo("完了", msg))

    def _do_download(self, url, dest, name, source, old_path, delete_old, delete_failed):
        try:
            self._log(f"  ⬇ DL中 [{source}]: {os.path.basename(dest)}")
            def _pcb(p):
                self._set_status(f"DL: {name[:18]} {p*100:.0f}%")
            download_file(url, dest, _pcb)
            if delete_old and old_path and os.path.exists(old_path):
                if os.path.abspath(dest) != os.path.abspath(old_path):
                    os.remove(old_path)
                    self._log(f"  🗑 旧ファイル削除: {os.path.basename(old_path)}")
            self._log(f"  ✅ 完了", "ok")
            return True
        except Exception as e:
            self._log(f"  ❌ DL失敗: {e}", "err")
            if os.path.exists(dest):
                try: os.remove(dest)
                except Exception: pass
            if delete_failed and old_path and os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    self._log(f"  🗑 失敗ファイル削除: {os.path.basename(old_path)}", "warn")
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
            if versions == MC_VERSIONS_FALLBACK:
                self._ver_status.config(text="⚠ オフライン（固定リスト）", foreground=YEL)
                self._log("⚠ バージョン取得失敗 → フォールバック使用", "warn")
            else:
                self._ver_status.config(text=f"✅ {len(versions)} 件", foreground=GRN)
                self._log(f"✅ MCバージョン {len(versions)} 件取得（最新: {versions[0]}）", "ok")
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
