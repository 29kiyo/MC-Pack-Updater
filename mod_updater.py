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
import urllib.error

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

CF_LOADER_MAP = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
CF_GAME_ID    = 432
# CurseForge classId
CF_CLASS_MOD   = 6
CF_CLASS_RP    = 12      # Resource Packs
CF_CLASS_SHADER = 6552  # Shaders

# Modrinth project_type
MR_TYPE_MOD    = "mod"
MR_TYPE_RP     = "resourcepack"
MR_TYPE_SHADER = "shader"

# ── カラー ────────────────────────────────────────────────────
BG   = "#f4f4f0"
BG2  = "#e8e8e3"
BG3  = "#d0d0c8"
FG   = "#1e1e1e"
ACC  = "#1d4ed8"
GRN  = "#15803d"
RED  = "#dc2626"
YEL  = "#92400e"

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
    req.add_header("User-Agent", "MC-Mod-Updater/3.0")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def download_file(url, dest_path, progress_cb=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MC-Mod-Updater/3.0")
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        done  = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(done / total)

# ── MCバージョン取得 ──────────────────────────────────────────
def fetch_mc_versions():
    try:
        data = http_get(f"{MODRINTH_API}/tag/game_version")
        releases = [
            v["version"] for v in data
            if v.get("version_type") == "release" and "." in v.get("version", "")
        ]
        def ver_key(v):
            parts = re.split(r"[.\-]", v)
            return tuple(int(x) if x.isdigit() else 0 for x in parts)
        releases.sort(key=ver_key, reverse=True)
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
                    info.update({
                        "mod_id":  d.get("id", ""),
                        "name":    d.get("name", info["filename"]),
                        "version": d.get("version", ""),
                        "loader":  "quilt" if meta.startswith("quilt") else "fabric",
                    })
                    return info
            for meta in ("META-INF/mods.toml", "META-INF/neoforge.mods.toml"):
                if meta in names:
                    raw = zf.read(meta).decode("utf-8", errors="ignore")
                    info["loader"] = "neoforge" if "neoforge" in meta else "forge"
                    in_mods = False
                    for line in raw.splitlines():
                        line = line.strip()
                        if line.startswith("[[mods]]"):
                            in_mods = True
                        if in_mods:
                            if line.startswith("modId"):
                                info["mod_id"] = line.split("=",1)[1].strip().strip('"')
                            elif line.startswith("displayName"):
                                info["name"] = line.split("=",1)[1].strip().strip('"')
                            elif line.startswith("version"):
                                v = line.split("=",1)[1].strip().strip('"')
                                if not v.startswith("$"):
                                    info["version"] = v
                    return info
    except Exception:
        pass
    return info

# ── Modrinth API ──────────────────────────────────────────────
def mr_find_project_by_hash(sha1):
    try:
        d = http_get(f"{MODRINTH_API}/version_file/{sha1}?algorithm=sha1")
        return d.get("project_id")
    except Exception:
        return None

def mr_find_project_by_slug(slug):
    try:
        d = http_get(f"{MODRINTH_API}/project/{slug}")
        return d.get("id")
    except Exception:
        return None

def mr_search_by_name(name, project_type):
    """名前でModrinthを検索してproject_idを返す"""
    try:
        params = urllib.parse.urlencode({
            "query":        name,
            "facets":       json.dumps([["project_type:" + project_type]]),
            "limit":        5,
        })
        d = http_get(f"{MODRINTH_API}/search?{params}")
        hits = d.get("hits", [])
        if not hits:
            return None
        name_lower = name.lower()
        for h in hits:
            if h.get("title","").lower() == name_lower:
                return h["project_id"]
        return hits[0]["project_id"]
    except Exception:
        return None

def mr_get_versions(project_id, mc_ver, loader):
    try:
        params = urllib.parse.urlencode({
            "game_versions": json.dumps([mc_ver]),
            "loaders":       json.dumps([loader]),
        })
        return http_get(f"{MODRINTH_API}/project/{project_id}/version?{params}")
    except Exception:
        return []

def mr_get_dependencies(version_obj, mc_ver, loader):
    """バージョンオブジェクトから required な依存プロジェクトのIDリストを返す"""
    deps = []
    for dep in version_obj.get("dependencies", []):
        if dep.get("dependency_type") == "required":
            pid = dep.get("project_id") or dep.get("version_id")
            if pid:
                deps.append(pid)
    return deps

# ── CurseForge API ────────────────────────────────────────────
def _cf_req(url, api_key):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MC-Mod-Updater/3.0")
    req.add_header("x-api-key",  api_key)
    req.add_header("Accept",     "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def cf_search_by_name(name, api_key, class_id=CF_CLASS_MOD):
    params = urllib.parse.urlencode({
        "gameId":       CF_GAME_ID,
        "classId":      class_id,
        "searchFilter": name,
        "pageSize":     5,
        "sortField":    2,
        "sortOrder":    "desc",
    })
    try:
        d = _cf_req(f"{CURSEFORGE_API}/mods/search?{params}", api_key)
        results = d.get("data", [])
        if not results:
            return None
        name_lower = name.lower()
        for r in results:
            if r.get("name","").lower() == name_lower:
                return r["id"]
        return results[0]["id"]
    except Exception:
        return None

def cf_get_file(cf_mod_id, mc_ver, loader, api_key):
    loader_id = CF_LOADER_MAP.get(loader, 0)
    params = urllib.parse.urlencode({
        "gameVersion":   mc_ver,
        "modLoaderType": loader_id,
        "pageSize":      10,
    })
    try:
        d = _cf_req(f"{CURSEFORGE_API}/mods/{cf_mod_id}/files?{params}", api_key)
        files = d.get("data", [])
        files.sort(key=lambda f: (f.get("releaseType", 9), -f.get("id", 0)))
        return files[0] if files else None
    except Exception:
        return None

# ── 統合検索・DL ──────────────────────────────────────────────
def find_and_get_dl_info(name, name_for_search, mod_id, path,
                          mc_ver, loader, mode, cf_key,
                          project_type=MR_TYPE_MOD,
                          cf_class=CF_CLASS_MOD,
                          log_cb=None):
    """
    Modrinth / CurseForge を検索して (url, filename, source, version_obj) を返す。
    見つからなければ (None, None, None, None)。
    """
    def log(msg, tag=""):
        if log_cb:
            log_cb(msg, tag)

    do_mr = mode in (DL_MODE_BOTH, DL_MODE_MODRINTH)
    do_cf = mode in (DL_MODE_BOTH, DL_MODE_CURSEFORGE)

    dl_url = None; dl_fname = None; source = ""; version_obj = None

    # ── Modrinth ──
    if do_mr:
        try:
            pid = None
            # JARがあればハッシュ検索
            if path and os.path.exists(path):
                sha1 = sha1_file(path)
                pid  = mr_find_project_by_hash(sha1)
            # mod_idでスラッグ検索
            if not pid and mod_id:
                pid = mr_find_project_by_slug(mod_id)
            # 名前で検索
            if not pid:
                pid = mr_search_by_name(name_for_search, project_type)

            if pid:
                vs = mr_get_versions(pid, mc_ver, loader)
                if vs:
                    version_obj = vs[0]
                    for finfo in vs[0].get("files", []):
                        if finfo.get("primary") or not dl_url:
                            dl_url   = finfo["url"]
                            dl_fname = finfo["filename"]
                            source   = "Modrinth"
                            if finfo.get("primary"):
                                break
                    log(f"  ✓ Modrinth: {dl_fname}", "ok")
                else:
                    log(f"  Modrinth: {mc_ver}/{loader} 対応バージョンなし", "warn")
            else:
                log(f"  Modrinth: プロジェクト見つからず", "warn")
        except Exception as e:
            log(f"  Modrinth エラー: {e}", "err")

    # ── CurseForge ──
    if do_cf and dl_url is None:
        try:
            cf_id = cf_search_by_name(name_for_search, cf_key, cf_class)
            if cf_id:
                finfo = cf_get_file(cf_id, mc_ver, loader, cf_key)
                if finfo:
                    dl_url   = finfo.get("downloadUrl")
                    dl_fname = finfo.get("fileName")
                    source   = "CurseForge"
                    log(f"  ✓ CurseForge: {dl_fname}", "ok")
                else:
                    log(f"  CurseForge: {mc_ver}/{loader} 対応バージョンなし", "warn")
            else:
                log(f"  CurseForge: 見つからず", "warn")
        except Exception as e:
            log(f"  CurseForge エラー: {e}", "err")

    return dl_url, dl_fname, source, version_obj

# ══════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("⛏ MC Mod Updater")
        self.geometry("960x740")
        self.configure(bg=BG)
        self.resizable(True, True)

        cfg = load_config()
        self.target_version  = tk.StringVar(value=cfg.get("target_version", "1.21.4"))
        self.target_loader   = tk.StringVar(value=cfg.get("target_loader", "fabric"))
        self.cf_api_key      = tk.StringVar(value=cfg.get("cf_api_key", ""))
        self.dl_mode         = tk.StringVar(value=cfg.get("dl_mode", DL_MODE_BOTH))
        # フォルダ
        self.mods_dir        = tk.StringVar(value=cfg.get("mods_dir", ""))
        self.rp_dir          = tk.StringVar(value=cfg.get("rp_dir", ""))
        self.shader_dir      = tk.StringVar(value=cfg.get("shader_dir", ""))
        # オプション
        self.delete_old      = tk.BooleanVar(value=cfg.get("delete_old", False))
        self.delete_failed   = tk.BooleanVar(value=cfg.get("delete_failed", False))
        self.auto_deps       = tk.BooleanVar(value=cfg.get("auto_deps", True))

        self.mod_list = []
        self._cf_key_showing = False

        self._apply_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._fetch_versions_bg, daemon=True).start()

    # ── スタイル ──────────────────────────────────────────────
    def _apply_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",           background=BG)
        s.configure("TLabel",           background=BG, foreground=FG, font=("Segoe UI", 10))
        s.configure("Hdr.TLabel",       background=BG, foreground=ACC, font=("Segoe UI", 13, "bold"))
        s.configure("Sub.TLabel",       background=BG, foreground=FG,  font=("Segoe UI", 9))
        s.configure("TButton",          background=ACC, foreground="#ffffff",
                     font=("Segoe UI", 10, "bold"), relief="flat", padding=(8,5))
        s.map("TButton",                background=[("active","#3b82f6"),("disabled",BG3)],
                                        foreground=[("disabled","#9ca3af")])
        s.configure("TEntry",           fieldbackground=BG2, foreground=FG,
                     insertcolor=FG, relief="flat", padding=4)
        s.configure("TCheckbutton",     background=BG, foreground=FG, font=("Segoe UI", 10))
        s.map("TCheckbutton",           background=[("active",BG)])
        s.configure("TCombobox",        fieldbackground=BG2, foreground=FG,
                     selectbackground=BG2, selectforeground=FG, padding=4)
        s.map("TCombobox",
              fieldbackground=[("readonly",BG2),("disabled",BG3)],
              foreground=[("readonly",FG),("disabled","#9ca3af")],
              selectbackground=[("readonly",BG2)],
              selectforeground=[("readonly",FG)])
        s.configure("Treeview",         background=BG2, foreground=FG,
                     fieldbackground=BG2, rowheight=26, font=("Segoe UI", 9))
        s.configure("Treeview.Heading", background=BG,  foreground=ACC,
                     font=("Segoe UI", 9, "bold"), relief="flat")
        s.map("Treeview",               background=[("selected",BG3)])
        s.configure("TProgressbar",     troughcolor=BG2, background=ACC, thickness=8)
        s.configure("TNotebook",        background=BG, tabmargins=0)
        s.configure("TNotebook.Tab",    background=BG2, foreground=FG,
                     padding=[14,7], font=("Segoe UI", 10))
        s.map("TNotebook.Tab",          background=[("selected",BG)],
                                        foreground=[("selected",ACC)])
        s.configure("TLabelframe",      background=BG, relief="solid",
                     borderwidth=1, bordercolor=BG3)
        s.configure("TLabelframe.Label",background=BG, foreground=ACC,
                     font=("Segoe UI", 10, "bold"))
        s.configure("TSeparator",       background=BG3)

    # ── UI構築 ────────────────────────────────────────────────
    def _build_ui(self):
        ttk.Label(self, text="⛏  MC Mod Updater", style="Hdr.TLabel").pack(pady=(14,2))
        ttk.Label(self, text="Mod / リソースパック / シェーダーを一括アップデート",
                   style="Sub.TLabel").pack(pady=(0,10))

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True, padx=14, pady=(0,4))

        t1 = ttk.Frame(self._nb); self._nb.add(t1, text=" ⚙ 設定 ")
        t2 = ttk.Frame(self._nb); self._nb.add(t2, text=" 📦 Mod一覧 ")
        t3 = ttk.Frame(self._nb); self._nb.add(t3, text=" 📋 ログ ")

        self._build_tab_settings(t1)
        self._build_tab_modlist(t2)
        self._build_tab_log(t3)

        bar = ttk.Frame(self); bar.pack(fill="x", padx=14, pady=(0,10))
        self._progress   = ttk.Progressbar(bar, mode="determinate")
        self._progress.pack(side="left", fill="x", expand=True, padx=(0,10))
        self._prog_label = ttk.Label(bar, text="", width=32)
        self._prog_label.pack(side="left")

    # ── Tab: 設定 ─────────────────────────────────────────────
    def _build_tab_settings(self, p):
        f = ttk.Frame(p); f.pack(fill="both", expand=True, padx=16, pady=12)

        # ── フォルダ設定 ──
        lf_dir = ttk.LabelFrame(f, text="📁  フォルダ設定")
        lf_dir.pack(fill="x", pady=(0,10))

        folders = [
            ("🧩 Modsフォルダ",          self.mods_dir,   "mods"),
            ("🎨 ResourcePacksフォルダ",  self.rp_dir,     "resourcepacks"),
            ("✨ Shadersフォルダ",        self.shader_dir, "shaderpacks"),
        ]
        for label, var, key in folders:
            row = ttk.Frame(lf_dir); row.pack(fill="x", padx=10, pady=4)
            ttk.Label(row, text=label, width=24).pack(side="left")
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=(0,6))
            ttk.Button(row, text="参照",
                        command=lambda v=var: self._browse(v)).pack(side="left")

        # ── バージョン ──
        lf2 = ttk.LabelFrame(f, text="🎯  アップデート先バージョン")
        lf2.pack(fill="x", pady=(0,10))
        row2 = ttk.Frame(lf2); row2.pack(fill="x", padx=10, pady=8)
        ttk.Label(row2, text="MCバージョン:").pack(side="left")
        self._ver_cb = ttk.Combobox(row2, textvariable=self.target_version,
                                     values=MC_VERSIONS_FALLBACK, width=13, state="readonly")
        self._ver_cb.pack(side="left", padx=(4,6))
        self._ver_status = ttk.Label(row2, text="🔄 取得中...",
                                      foreground=YEL, background=BG, font=("Segoe UI", 8))
        self._ver_status.pack(side="left", padx=(0,20))
        ttk.Label(row2, text="Mod Loader:").pack(side="left")
        ttk.Combobox(row2, textvariable=self.target_loader,
                      values=LOADERS, width=13, state="readonly").pack(side="left", padx=(4,0))

        # ── ダウンロード設定 ──
        lf3 = ttk.LabelFrame(f, text="🌐  ダウンロード設定")
        lf3.pack(fill="x", pady=(0,10))
        mf = ttk.Frame(lf3); mf.pack(fill="x", padx=10, pady=(10,4))
        ttk.Label(mf, text="ダウンロードモード:").pack(side="left")
        self._dl_mode_cb = ttk.Combobox(mf, textvariable=self.dl_mode,
                                         values=DL_MODES, width=26, state="readonly")
        self._dl_mode_cb.pack(side="left", padx=(6,0))
        self._dl_mode_cb.bind("<<ComboboxSelected>>", lambda _: self._update_mode_ui())

        self._mode_desc = ttk.Label(lf3, text="", foreground=YEL,
                                     background=BG, font=("Segoe UI", 9))
        self._mode_desc.pack(anchor="w", padx=10, pady=(0,4))

        ttk.Separator(lf3, orient="horizontal").pack(fill="x", padx=10, pady=4)

        cf_row = ttk.Frame(lf3); cf_row.pack(fill="x", padx=10, pady=(4,10))
        ttk.Label(cf_row, text="CurseForge APIキー:").pack(side="left")
        self._cf_entry = ttk.Entry(cf_row, textvariable=self.cf_api_key, show="*", width=42)
        self._cf_entry.pack(side="left", padx=(6,6))
        self._cf_show_btn = ttk.Button(cf_row, text="表示",
                                        command=self._toggle_cf_show, width=5)
        self._cf_show_btn.pack(side="left", padx=(0,6))
        ttk.Button(cf_row, text="取得方法 ↗",
                    command=lambda: __import__("webbrowser").open(
                        "https://console.curseforge.com/")).pack(side="left")
        self._update_mode_ui()

        # ── オプション ──
        lf4 = ttk.LabelFrame(f, text="⚙  オプション")
        lf4.pack(fill="x", pady=(0,14))
        opts = [
            ("アップデート後に古いファイルを削除する",         self.delete_old),
            ("ダウンロード失敗したファイルを削除する（壊れたファイル除去）", self.delete_failed),
            ("前提Modが足りなければ自動でダウンロードする",    self.auto_deps),
        ]
        for text, var in opts:
            ttk.Checkbutton(lf4, text=text, variable=var).pack(
                padx=10, pady=3, anchor="w")

        # ── ボタン ──
        brow = ttk.Frame(f); brow.pack(fill="x", pady=(4,0))
        ttk.Button(brow, text="📂 Modを読み込む",
                    command=self._load_mods).pack(side="left", padx=(0,10))
        self._start_btn = ttk.Button(brow, text="⬇ Modをアップデート",
                                      command=lambda: self._start("mod"), state="disabled")
        self._start_btn.pack(side="left", padx=(0,10))
        ttk.Button(brow, text="🔄 全て一括アップデート",
                    command=lambda: self._start("all")).pack(side="left")

    # ── Tab: Mod一覧 ──────────────────────────────────────────
    def _build_tab_modlist(self, p):
        top = ttk.Frame(p); top.pack(fill="x", padx=8, pady=6)
        ttk.Button(top, text="全選択",  command=lambda: self._sel_all(True)).pack(side="left", padx=(0,6))
        ttk.Button(top, text="全解除",  command=lambda: self._sel_all(False)).pack(side="left")
        self._sel_label = ttk.Label(top, text="0 / 0 件")
        self._sel_label.pack(side="right", padx=8)

        cols = ("chk","name","mod_id","version","loader","src")
        self._tree = ttk.Treeview(p, columns=cols, show="headings", selectmode="none")
        for cid, label, w in [
            ("chk","✔",40), ("name","Mod名",230), ("mod_id","Mod ID",160),
            ("version","現バージョン",110), ("loader","Loader",80), ("src","認識元",120)
        ]:
            self._tree.heading(cid, text=label)
            self._tree.column(cid, width=w, anchor="center" if cid=="chk" else "w",
                               stretch=(cid=="name"))
        self._tree.tag_configure("even", background=BG2)
        self._tree.tag_configure("odd",  background="#f0f0eb")
        self._tree.tag_configure("dep",  background="#dbeafe")  # 依存Mod（水色）

        vsb = ttk.Scrollbar(p, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(8,0), pady=(0,8))
        vsb.pack(side="left", fill="y", pady=(0,8), padx=(0,8))
        self._tree.bind("<Button-1>", self._on_tree_click)

    # ── Tab: ログ ─────────────────────────────────────────────
    def _build_tab_log(self, p):
        self._log_box = scrolledtext.ScrolledText(
            p, bg="#ffffff", fg=FG, insertbackground=FG,
            font=("Consolas", 9), relief="flat", wrap="word")
        self._log_box.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, color in [("ok",GRN),("err",RED),("info",ACC),("warn",YEL)]:
            self._log_box.tag_config(tag, foreground=color)
        ttk.Button(p, text="ログをクリア",
                    command=lambda: self._log_box.delete("1.0","end")).pack(pady=(0,8))

    # ── ヘルパー ──────────────────────────────────────────────
    def _update_mode_ui(self):
        mode = self.dl_mode.get()
        desc = {
            DL_MODE_BOTH:       "Modrinthで検索 → 見つからない場合はCurseForgeも検索",
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
        if d:
            var.set(d)

    def _log(self, msg, tag=""):
        def _do():
            self._log_box.insert("end", msg+"\n", tag)
            self._log_box.see("end")
        self.after(0, _do)

    def _set_status(self, msg):
        self.after(0, lambda: self._prog_label.config(text=msg))

    def _set_progress(self, v, total=None):
        def _do():
            if total is not None:
                self._progress.configure(maximum=total)
            self._progress.configure(value=v)
        self.after(0, _do)

    def _on_tree_click(self, e):
        row = self._tree.identify_row(e.y)
        col = self._tree.identify_column(e.x)
        if row and col == "#1":
            cur = self._tree.set(row, "chk")
            self._tree.set(row, "chk", "☑" if cur == "☐" else "☐")
            self._update_sel_label()

    def _sel_all(self, v):
        for row in self._tree.get_children():
            self._tree.set(row, "chk", "☑" if v else "☐")
        self._update_sel_label()

    def _update_sel_label(self):
        rows = self._tree.get_children()
        sel  = sum(1 for r in rows if self._tree.set(r,"chk") == "☑")
        self._sel_label.config(text=f"{sel} / {len(rows)} 件選択")

    # ── Mod読み込み ───────────────────────────────────────────
    def _load_mods(self):
        d = self.mods_dir.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror("エラー", "有効なmodsフォルダを選択してください"); return

        jars = [f for f in os.listdir(d) if f.lower().endswith(".jar")]
        if not jars:
            messagebox.showinfo("情報", "JARファイルが見つかりませんでした"); return

        for row in self._tree.get_children():
            self._tree.delete(row)
        self.mod_list = []
        self._log(f"📂 {len(jars)} 個のJARを解析中...", "info")

        for i, jar in enumerate(sorted(jars)):
            path = os.path.join(d, jar)
            info = read_jar_meta(path)
            self.mod_list.append(info)
            src = {"fabric":"fabric.mod.json","quilt":"quilt.mod.json",
                   "forge":"mods.toml","neoforge":"neoforge.mods.toml"}.get(
                info.get("loader",""), "不明")
            tag = "even" if i % 2 == 0 else "odd"
            self._tree.insert("", "end", iid=jar, tags=(tag,),
                               values=("☑", info.get("name",jar), info.get("mod_id","?"),
                                       info.get("version","?"), info.get("loader","?"), src))

        self._update_sel_label()
        self._log(f"✅ {len(jars)} 件読み込み完了", "ok")
        self._start_btn.config(state="normal")
        self._nb.select(1)

    # ── バリデーション ────────────────────────────────────────
    def _validate(self):
        mode   = self.dl_mode.get()
        cf_key = self.cf_api_key.get().strip()
        if mode in (DL_MODE_BOTH, DL_MODE_CURSEFORGE) and not cf_key:
            messagebox.showerror("エラー",
                "CurseForgeを使用するにはAPIキーが必要です")
            return False
        return True

    # ── アップデート開始 ──────────────────────────────────────
    def _start(self, target):
        if not self._validate():
            return

        mc_ver = self.target_version.get()
        loader = self.target_loader.get()
        mode   = self.dl_mode.get()
        cf_key = self.cf_api_key.get().strip()

        tasks = []  # [(type, name, mod_id, path, out_dir, mr_type, cf_class)]

        if target in ("mod", "all"):
            selected = [m for m in self.mod_list
                        if self._tree.exists(m["filename"]) and
                           self._tree.set(m["filename"],"chk") == "☑"]
            if not selected and target == "mod":
                messagebox.showinfo("情報", "Modが選択されていません"); return
            for m in selected:
                tasks.append(("mod", m.get("name", m["filename"]),
                               m.get("mod_id",""), m["path"],
                               self.mods_dir.get(),
                               MR_TYPE_MOD, CF_CLASS_MOD))

        if target == "all":
            # ResourcePack
            rp = self.rp_dir.get().strip()
            if rp and os.path.isdir(rp):
                for f in os.listdir(rp):
                    if f.lower().endswith(".zip"):
                        name = os.path.splitext(f)[0]
                        tasks.append(("rp", name, "", os.path.join(rp, f),
                                       rp, MR_TYPE_RP, CF_CLASS_RP))
            # Shader
            sh = self.shader_dir.get().strip()
            if sh and os.path.isdir(sh):
                for f in os.listdir(sh):
                    if f.lower().endswith(".zip"):
                        name = os.path.splitext(f)[0]
                        tasks.append(("shader", name, "", os.path.join(sh, f),
                                       sh, MR_TYPE_SHADER, CF_CLASS_SHADER))

        if not tasks:
            messagebox.showinfo("情報", "アップデート対象がありません"); return

        self._start_btn.config(state="disabled")
        self._set_progress(0, len(tasks))
        self._nb.select(2)

        threading.Thread(target=self._worker,
                          args=(tasks, mc_ver, loader, mode, cf_key),
                          daemon=True).start()

    # ── ワーカー ──────────────────────────────────────────────
    def _worker(self, tasks, mc_ver, loader, mode, cf_key):
        delete_old    = self.delete_old.get()
        delete_failed = self.delete_failed.get()
        auto_deps     = self.auto_deps.get()

        ok_list   = []
        fail_list = []
        # 依存Modを重複DLしないために追跡
        downloaded_pids = set()

        total = len(tasks)

        for i, task in enumerate(tasks):
            kind, name, mod_id, path, out_dir, mr_type, cf_class = task
            kind_label = {"mod":"Mod","rp":"RP","shader":"Shader"}.get(kind, kind)
            self._set_status(f"{i+1}/{total}: [{kind_label}] {name[:24]}")
            self._log(f"\n── [{kind_label}] {name} ──", "info")

            dl_url, dl_fname, source, version_obj = find_and_get_dl_info(
                name, name, mod_id, path,
                mc_ver, loader, mode, cf_key,
                mr_type, cf_class,
                log_cb=self._log
            )

            if dl_url and dl_fname:
                dest = os.path.join(out_dir, dl_fname)
                success = self._do_download(dl_url, dest, name, source,
                                             path, out_dir, delete_old, delete_failed)
                if success:
                    ok_list.append(f"[{kind_label}] {name}")

                    # ── 前提Mod自動DL（Modのみ） ──
                    if kind == "mod" and auto_deps and version_obj:
                        dep_pids = mr_get_dependencies(version_obj, mc_ver, loader)
                        for dep_pid in dep_pids:
                            if dep_pid in downloaded_pids:
                                continue
                            downloaded_pids.add(dep_pid)
                            self._log(f"  🔗 依存Mod検索中: {dep_pid}", "info")
                            try:
                                vs = mr_get_versions(dep_pid, mc_ver, loader)
                                if vs:
                                    dep_v = vs[0]
                                    dep_url = None; dep_fname = None
                                    for finfo in dep_v.get("files", []):
                                        if finfo.get("primary") or not dep_url:
                                            dep_url   = finfo["url"]
                                            dep_fname = finfo["filename"]
                                            if finfo.get("primary"):
                                                break
                                    if dep_url and dep_fname:
                                        dep_dest = os.path.join(out_dir, dep_fname)
                                        if os.path.exists(dep_dest):
                                            self._log(f"  🔗 依存Modはすでに存在: {dep_fname}", "ok")
                                        else:
                                            self._log(f"  🔗 依存Mod DL中: {dep_fname}", "info")
                                            self._do_download(dep_url, dep_dest,
                                                               dep_fname, "Modrinth",
                                                               None, out_dir, False, delete_failed)
                                            # ツリーに追加（水色）
                                            self.after(0, lambda fn=dep_fname: self._tree.insert(
                                                "", "end", iid=fn, tags=("dep",),
                                                values=("☑", fn, "（依存）", "", "", "自動追加")))
                                            ok_list.append(f"[依存] {dep_fname}")
                                else:
                                    self._log(f"  🔗 依存Mod: {mc_ver}/{loader}向けなし", "warn")
                            except Exception as e:
                                self._log(f"  🔗 依存Modエラー: {e}", "err")
                else:
                    fail_list.append(name)
            else:
                fail_list.append(name)
                self._log(f"  ❌ スキップ（対応バージョンなし）", "err")
                if delete_failed and path and os.path.exists(path):
                    os.remove(path)
                    self._log(f"  🗑 失敗ファイル削除: {os.path.basename(path)}", "warn")

            self._set_progress(i + 1)

        # ── サマリー ──
        self._log(f"\n{'═'*50}", "info")
        self._log(f"✅ 成功: {len(ok_list)} 件", "ok")
        for n in ok_list:
            self._log(f"   ✓ {n}", "ok")
        if fail_list:
            self._log(f"\n❌ 失敗: {len(fail_list)} 件", "err")
            for n in fail_list:
                self._log(f"   ✗ {n}", "err")
        else:
            self._log("\n🎉 全て完了しました！", "ok")

        self._set_status("完了")
        msg = f"✅ 成功: {len(ok_list)} 件\n❌ 失敗: {len(fail_list)} 件"
        if fail_list:
            msg += "\n\n失敗:\n" + "\n".join(f"• {n}" for n in fail_list)
        self.after(0, lambda: messagebox.showinfo("完了", msg))
        self.after(0, lambda: self._start_btn.config(state="normal"))

    def _do_download(self, url, dest, name, source, old_path, out_dir,
                     delete_old, delete_failed):
        try:
            self._log(f"  ⬇ DL中 [{source}]: {os.path.basename(dest)}")
            def _pcb(p, _n=name):
                self._set_status(f"DL: {_n[:20]} {p*100:.0f}%")
            download_file(url, dest, _pcb)

            if delete_old and old_path and os.path.exists(old_path):
                if os.path.abspath(dest) != os.path.abspath(old_path):
                    os.remove(old_path)
                    self._log(f"  🗑 旧ファイル削除: {os.path.basename(old_path)}")

            self._log(f"  ✅ 完了", "ok")
            return True
        except Exception as e:
            self._log(f"  ❌ DL失敗: {e}", "err")
            # 失敗したら中途半端なファイルを消す
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except Exception:
                    pass
            if delete_failed and old_path and os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    self._log(f"  🗑 失敗ファイル削除: {os.path.basename(old_path)}", "warn")
                except Exception:
                    pass
            return False

    # ── MCバージョン取得 ──────────────────────────────────────
    def _fetch_versions_bg(self):
        versions = fetch_mc_versions()
        def _update():
            current = self.target_version.get()
            self._ver_cb["values"] = versions
            self._ver_cb.set(current if current in versions else versions[0])
            self.target_version.set(self._ver_cb.get())
            is_fallback = (versions == MC_VERSIONS_FALLBACK)
            if is_fallback:
                self._ver_status.config(text="⚠ オフライン（固定リスト）", foreground=YEL)
                self._log("⚠ MCバージョン取得失敗 → フォールバックリストを使用", "warn")
            else:
                self._ver_status.config(text=f"✅ {len(versions)} 件", foreground=GRN)
                self._log(f"✅ MCバージョン {len(versions)} 件取得（最新: {versions[0]}）", "ok")
        self.after(0, _update)

    # ── 終了 ──────────────────────────────────────────────────
    def _on_close(self):
        save_config({
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
