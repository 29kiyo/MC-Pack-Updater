import os
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

# ── 定数 ──────────────────────────────────────────────
MODRINTH_API   = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"
CONFIG_FILE    = os.path.join(os.path.expanduser("~"), ".mc_mod_updater_config.json")

MC_VERSIONS_FALLBACK = [
    "1.21.4","1.21.3","1.21.1","1.21",
    "1.20.6","1.20.4","1.20.2","1.20.1","1.20",
    "1.19.4","1.19.3","1.19.2","1.19.1","1.19",
    "1.18.2","1.18.1","1.18",
    "1.17.1","1.17",
    "1.16.5","1.16.4","1.16.3","1.16.2","1.16.1",
    "1.15.2","1.12.2",
]

def fetch_mc_versions():
    """ModrinthのAPIからリリース済みMCバージョン一覧を取得する"""
    try:
        import re
        data = http_get(f"{MODRINTH_API}/tag/game_version")
        # type=="release" のみ、バージョン番号でソート（新しい順）
        releases = [v["version"] for v in data if v.get("version_type") == "release"]
        def ver_key(v):
            parts = re.split(r"[.\-]", v)
            return tuple(int(x) if x.isdigit() else 0 for x in parts)
        releases.sort(key=ver_key, reverse=True)
        return releases if releases else MC_VERSIONS_FALLBACK
    except Exception:
        return MC_VERSIONS_FALLBACK
LOADERS = ["fabric", "forge", "neoforge", "quilt"]

# ダウンロードモード
DL_MODE_BOTH       = "両方（Modrinth優先）"
DL_MODE_MODRINTH   = "Modrinthのみ"
DL_MODE_CURSEFORGE = "CurseForgeのみ"
DL_MODES = [DL_MODE_BOTH, DL_MODE_MODRINTH, DL_MODE_CURSEFORGE]

CF_LOADER_MAP = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
CF_GAME_ID    = 432

# ── 設定の保存・読み込み ────────────────────────────────
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

# ── ユーティリティ ──────────────────────────────────────
def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent", "MC-Mod-Updater/2.0 (github)")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

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
            # Fabric / Quilt
            for meta in ("fabric.mod.json", "quilt.mod.json"):
                if meta in names:
                    d = json.loads(zf.read(meta).decode("utf-8", errors="ignore"))
                    info.update({
                        "mod_id": d.get("id", ""),
                        "name":   d.get("name", info["filename"]),
                        "version": d.get("version", ""),
                        "loader": "quilt" if meta.startswith("quilt") else "fabric",
                    })
                    return info
            # Forge / NeoForge
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

# ── Modrinth ────────────────────────────────────────────
def mr_find_project(sha1, mod_id):
    """SHA1ハッシュ → Modrinthプロジェクトを逆引き、なければスラッグ検索"""
    try:
        d = http_get(f"{MODRINTH_API}/version_file/{sha1}?algorithm=sha1")
        pid = d.get("project_id")
        if pid:
            return pid
    except Exception:
        pass
    if mod_id:
        try:
            d = http_get(f"{MODRINTH_API}/project/{mod_id}")
            return d.get("id")
        except Exception:
            pass
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

# ── CurseForge ──────────────────────────────────────────
def _cf_req(url, api_key):
    req = urllib.request.Request(url)
    req.add_header("User-Agent",  "MC-Mod-Updater/2.0")
    req.add_header("x-api-key",   api_key)
    req.add_header("Accept",      "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def cf_search_by_name(name, api_key):
    """Mod名でCurseForgeを検索し最も近いmod IDを返す"""
    params = urllib.parse.urlencode({
        "gameId":       CF_GAME_ID,
        "classId":      6,          # Mods
        "searchFilter": name,
        "pageSize":     5,
        "sortField":    2,          # Popularity
        "sortOrder":    "desc",
    })
    try:
        d = _cf_req(f"{CURSEFORGE_API}/mods/search?{params}", api_key)
        results = d.get("data", [])
        if not results:
            return None
        # 名前が一致するものを優先
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
        "gameVersion":     mc_ver,
        "modLoaderType":   loader_id,
        "pageSize":        10,
    })
    try:
        d = _cf_req(f"{CURSEFORGE_API}/mods/{cf_mod_id}/files?{params}", api_key)
        files = d.get("data", [])
        # releaseType: 1=Release 2=Beta 3=Alpha — Releaseを優先
        files.sort(key=lambda f: (f.get("releaseType", 9), -f.get("id", 0)))
        return files[0] if files else None
    except Exception:
        return None

# ── ダウンロード ────────────────────────────────────────
def download_file(url, dest_path, progress_cb=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "MC-Mod-Updater/2.0")
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

# ══════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════
BG   = "#1e1e2e"
BG2  = "#2a2a3e"
BG3  = "#313244"
FG   = "#cdd6f4"
ACC  = "#89b4fa"
GRN  = "#a6e3a1"
RED  = "#f38ba8"
YEL  = "#f9e2af"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("⛏ MC Mod Updater")
        self.geometry("920x700")
        self.configure(bg=BG)
        self.resizable(True, True)

        cfg = load_config()

        self.mods_dir        = tk.StringVar(value=cfg.get("mods_dir", ""))
        self.target_version  = tk.StringVar(value=cfg.get("target_version", "1.21.1"))
        self.target_loader   = tk.StringVar(value=cfg.get("target_loader", "fabric"))
        self.cf_api_key      = tk.StringVar(value=cfg.get("cf_api_key", ""))
        self.dl_mode         = tk.StringVar(value=cfg.get("dl_mode", DL_MODE_BOTH))
        self.delete_old      = tk.BooleanVar(value=cfg.get("delete_old", False))

        self.mod_list = []
        self._apply_style()   # スタイルを先に適用してからUI構築
        self._build_ui()

        # 終了時に設定保存
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 起動後にバックグラウンドでMCバージョン一覧を取得
        threading.Thread(target=self._fetch_versions_bg, daemon=True).start()

    # ── スタイル ──
    def _apply_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",          background=BG)
        s.configure("TLabel",          background=BG, foreground=FG, font=("Segoe UI", 10))
        s.configure("Hdr.TLabel",      background=BG, foreground=ACC, font=("Segoe UI", 13, "bold"))
        s.configure("Sub.TLabel",      background=BG, foreground=FG,  font=("Segoe UI", 9))
        s.configure("TButton",         background=ACC, foreground=BG,
                     font=("Segoe UI", 10, "bold"), relief="flat", padding=(8,5))
        s.map("TButton",               background=[("active","#74c7ec"),("disabled",BG3)],
                                       foreground=[("disabled","#585b70")])
        s.configure("Red.TButton",     background=RED, foreground=BG,
                     font=("Segoe UI", 10, "bold"), relief="flat", padding=(8,5))
        s.map("Red.TButton",           background=[("active","#eba0ac")])
        s.configure("TEntry",          fieldbackground=BG2, foreground=FG,
                     insertcolor=FG, relief="flat", padding=4)
        s.configure("TCheckbutton",    background=BG, foreground=FG, font=("Segoe UI", 10))
        s.map("TCheckbutton",          background=[("active",BG)])
        s.configure("TCombobox",       fieldbackground=BG2, foreground=FG,
                     selectbackground=BG2, selectforeground=FG, padding=4)
        s.configure("Treeview",        background=BG2, foreground=FG,
                     fieldbackground=BG2, rowheight=26, font=("Segoe UI", 9))
        s.configure("Treeview.Heading",background=BG,  foreground=ACC,
                     font=("Segoe UI", 9, "bold"), relief="flat")
        s.map("Treeview",              background=[("selected", BG3)])
        s.configure("TProgressbar",    troughcolor=BG2, background=ACC, thickness=8)
        s.configure("TNotebook",       background=BG, tabmargins=0)
        s.configure("TNotebook.Tab",   background=BG2, foreground=FG,
                     padding=[14,7], font=("Segoe UI", 10))
        s.map("TNotebook.Tab",         background=[("selected",BG)],
                                       foreground=[("selected",ACC)])
        s.configure("TLabelframe",     background=BG, relief="solid", borderwidth=1,
                     bordercolor=BG3)
        s.configure("TLabelframe.Label",background=BG, foreground=ACC,
                     font=("Segoe UI", 10, "bold"))
        s.configure("TSeparator",      background=BG3)

    # ── UI構築 ──
    def _build_ui(self):
        ttk.Label(self, text="⛏  MC Mod Updater", style="Hdr.TLabel").pack(pady=(14,2))
        ttk.Label(self, text="modsフォルダを読み込んで、指定バージョンに一括アップデート",
                   style="Sub.TLabel").pack(pady=(0,10))

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True, padx=14, pady=(0,4))

        t1 = ttk.Frame(self._nb); self._nb.add(t1, text=" ⚙ 設定 ")
        t2 = ttk.Frame(self._nb); self._nb.add(t2, text=" 📦 Mod一覧 ")
        t3 = ttk.Frame(self._nb); self._nb.add(t3, text=" 📋 ログ ")

        self._build_tab_settings(t1)
        self._build_tab_modlist(t2)
        self._build_tab_log(t3)

        # 下部バー
        bar = ttk.Frame(self); bar.pack(fill="x", padx=14, pady=(0,10))
        self._progress   = ttk.Progressbar(bar, length=400, mode="determinate")
        self._progress.pack(side="left", fill="x", expand=True, padx=(0,10))
        self._prog_label = ttk.Label(bar, text="", width=30)
        self._prog_label.pack(side="left")

    # ── Tab: 設定 ──
    def _build_tab_settings(self, p):
        f = ttk.Frame(p); f.pack(fill="both", expand=True, padx=16, pady=12)

        # modsフォルダ
        lf = ttk.LabelFrame(f, text="📁  Modsフォルダ")
        lf.pack(fill="x", pady=(0,10))
        row = ttk.Frame(lf); row.pack(fill="x", padx=10, pady=8)
        ttk.Entry(row, textvariable=self.mods_dir).pack(
            side="left", fill="x", expand=True, padx=(0,6))
        ttk.Button(row, text="参照", command=self._browse).pack(side="left")

        # アップデート先
        lf2 = ttk.LabelFrame(f, text="🎯  アップデート先バージョン")
        lf2.pack(fill="x", pady=(0,10))
        row2 = ttk.Frame(lf2); row2.pack(fill="x", padx=10, pady=8)
        ttk.Label(row2, text="MCバージョン:").pack(side="left")
        self._ver_cb = ttk.Combobox(row2, textvariable=self.target_version,
                      values=MC_VERSIONS_FALLBACK, width=13, state="readonly")
        self._ver_cb.pack(side="left", padx=(4,24))
        self._ver_status = ttk.Label(row2, text="🔄 取得中...", foreground=YEL,
                                      background=BG, font=("Segoe UI", 8))
        self._ver_status.pack(side="left")
        ttk.Label(row2, text="Mod Loader:").pack(side="left")
        ttk.Combobox(row2, textvariable=self.target_loader,
                      values=LOADERS, width=13, state="readonly").pack(
            side="left", padx=(4,0))

        # ダウンロード設定
        lf3 = ttk.LabelFrame(f, text="🌐  ダウンロード設定")
        lf3.pack(fill="x", pady=(0,10))

        # ── モード選択 ──
        mf = ttk.Frame(lf3); mf.pack(fill="x", padx=10, pady=(10,4))
        ttk.Label(mf, text="ダウンロードモード:").pack(side="left")
        self._dl_mode_cb = ttk.Combobox(mf, textvariable=self.dl_mode,
                                         values=DL_MODES, width=26, state="readonly")
        self._dl_mode_cb.pack(side="left", padx=(6,0))
        self._dl_mode_cb.bind("<<ComboboxSelected>>", self._on_mode_change)

        # モード説明
        self._mode_desc = ttk.Label(lf3, text="", foreground=YEL,
                                     background=BG, font=("Segoe UI", 9))
        self._mode_desc.pack(anchor="w", padx=10, pady=(0,6))

        ttk.Separator(lf3, orient="horizontal").pack(fill="x", padx=10, pady=4)

        # ── CurseForge APIキー ──
        cf_frame = ttk.Frame(lf3); cf_frame.pack(fill="x", padx=10, pady=(4,10))
        ttk.Label(cf_frame, text="CurseForge APIキー:").pack(side="left")
        self._cf_entry = ttk.Entry(cf_frame, textvariable=self.cf_api_key,
                                    show="*", width=44)
        self._cf_entry.pack(side="left", padx=(6,6))

        self._cf_show_btn = ttk.Button(cf_frame, text="表示",
                                        command=self._toggle_cf_show, width=5)
        self._cf_show_btn.pack(side="left", padx=(0,6))

        ttk.Button(cf_frame, text="取得方法 ↗",
                    command=lambda: self._open_url(
                        "https://console.curseforge.com/")).pack(side="left")

        self._cf_key_showing = False
        self._update_mode_ui()

        # オプション
        lf4 = ttk.LabelFrame(f, text="🗑  オプション")
        lf4.pack(fill="x", pady=(0,14))
        ttk.Checkbutton(lf4, text="アップデート後に古いJARファイルを削除する",
                         variable=self.delete_old).pack(padx=10, pady=8, anchor="w")

        # ボタン行
        brow = ttk.Frame(f); brow.pack(fill="x")
        ttk.Button(brow, text="📂  Modを読み込む",
                    command=self._load_mods).pack(side="left", padx=(0,10))
        self._start_btn = ttk.Button(brow, text="⬇  アップデート開始",
                                      command=self._start, state="disabled")
        self._start_btn.pack(side="left")

    # ── Tab: Mod一覧 ──
    def _build_tab_modlist(self, p):
        top = ttk.Frame(p); top.pack(fill="x", padx=8, pady=6)
        ttk.Button(top, text="全選択",  command=lambda: self._sel_all(True)).pack(side="left", padx=(0,6))
        ttk.Button(top, text="全解除",  command=lambda: self._sel_all(False)).pack(side="left")
        self._sel_label = ttk.Label(top, text="0 / 0 件"); self._sel_label.pack(side="right", padx=8)

        cols = ("chk","name","mod_id","version","loader","src")
        self._tree = ttk.Treeview(p, columns=cols, show="headings", selectmode="none")
        hd = [("chk","✔",40), ("name","Mod名",230), ("mod_id","Mod ID",160),
              ("version","現バージョン",110), ("loader","Loader",80), ("src","認識元",120)]
        for cid, label, w in hd:
            self._tree.heading(cid, text=label)
            self._tree.column(cid, width=w, anchor="center" if cid=="chk" else "w",
                               stretch=(cid=="name"))
        self._tree.tag_configure("even", background=BG2)
        self._tree.tag_configure("odd",  background="#252535")

        vsb = ttk.Scrollbar(p, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(8,0), pady=(0,8))
        vsb.pack(side="left", fill="y", pady=(0,8), padx=(0,8))
        self._tree.bind("<Button-1>", self._on_tree_click)

    # ── Tab: ログ ──
    def _build_tab_log(self, p):
        self._log_box = scrolledtext.ScrolledText(
            p, bg="#181825", fg=FG, insertbackground=FG,
            font=("Consolas", 9), relief="flat", wrap="word"
        )
        self._log_box.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, color in [("ok",GRN),("err",RED),("info",ACC),("warn",YEL)]:
            self._log_box.tag_config(tag, foreground=color)
        ttk.Button(p, text="ログをクリア",
                    command=lambda: self._log_box.delete("1.0","end")).pack(pady=(0,8))

    # ── モード変更 ──
    def _on_mode_change(self, _=None):
        self._update_mode_ui()

    def _update_mode_ui(self):
        mode = self.dl_mode.get()
        desc = {
            DL_MODE_BOTH:       "Modrinthで検索 → 見つからない場合はCurseForgeも検索",
            DL_MODE_MODRINTH:   "Modrinthのみで検索（APIキー不要）",
            DL_MODE_CURSEFORGE: "CurseForgeのみで検索（APIキー必須）",
        }.get(mode, "")
        self._mode_desc.config(text=f"  ℹ {desc}")
        need_cf = mode in (DL_MODE_BOTH, DL_MODE_CURSEFORGE)
        state = "normal" if need_cf else "disabled"
        # 選択値を退避してからstate変更 → 復元（stateの変更で選択が消えるのを防ぐ）
        ver = self.target_version.get()
        ldr = self.target_loader.get()
        self._cf_entry.config(state=state)
        self._cf_show_btn.config(state=state)
        self.target_version.set(ver)
        self.target_loader.set(ldr)

    def _toggle_cf_show(self):
        self._cf_key_showing = not self._cf_key_showing
        self._cf_entry.config(show="" if self._cf_key_showing else "*")
        self._cf_show_btn.config(text="隠す" if self._cf_key_showing else "表示")

    def _open_url(self, url):
        import webbrowser
        webbrowser.open(url)

    # ── Mod読み込み ──
    def _browse(self):
        d = filedialog.askdirectory(title="modsフォルダを選択")
        if d:
            self.mods_dir.set(d)

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
            tag = "even" if i % 2 == 0 else "odd"
            src = {"fabric":"fabric.mod.json","quilt":"quilt.mod.json",
                   "forge":"mods.toml","neoforge":"neoforge.mods.toml"}.get(
                info.get("loader",""), "不明")
            self._tree.insert("", "end", iid=jar, tags=(tag,),
                               values=("☑", info.get("name",jar),
                                       info.get("mod_id","?"),
                                       info.get("version","?"),
                                       info.get("loader","?"), src))

        self._update_sel_label()
        self._log(f"✅ {len(jars)} 件読み込み完了", "ok")
        self._start_btn.config(state="normal")
        self._nb.select(1)

    # ── ツリー操作 ──
    def _on_tree_click(self, e):
        row = self._tree.identify_row(e.y)
        col = self._tree.identify_column(e.x)
        if row and col == "#1":
            cur = self._tree.set(row, "chk")
            self._tree.set(row, "chk", "☑" if cur == "☐" else "☐")
            self._update_sel_label()

    def _sel_all(self, v):
        mark = "☑" if v else "☐"
        for row in self._tree.get_children():
            self._tree.set(row, "chk", mark)
        self._update_sel_label()

    def _update_sel_label(self):
        rows = self._tree.get_children()
        sel = sum(1 for r in rows if self._tree.set(r,"chk") == "☑")
        self._sel_label.config(text=f"{sel} / {len(rows)} 件選択")

    # ── ログ ──
    def _log(self, msg, tag=""):
        def _do():
            self._log_box.insert("end", msg+"\n", tag)
            self._log_box.see("end")
        self.after(0, _do)

    def _set_status(self, msg):
        self.after(0, lambda: self._prog_label.config(text=msg))

    def _set_progress(self, v):
        self.after(0, lambda: self._progress.configure(value=v))

    # ── アップデート開始 ──
    def _start(self):
        mode    = self.dl_mode.get()
        cf_key  = self.cf_api_key.get().strip()
        mc_ver  = self.target_version.get()
        loader  = self.target_loader.get()

        if mode in (DL_MODE_BOTH, DL_MODE_CURSEFORGE) and not cf_key:
            messagebox.showerror("エラー",
                "CurseForgeを使用するにはAPIキーが必要です\n"
                "「ダウンロードモード」を変更するか、APIキーを入力してください")
            return

        selected = [m for m in self.mod_list
                    if self._tree.exists(m["filename"]) and
                       self._tree.set(m["filename"],"chk") == "☑"]
        if not selected:
            messagebox.showinfo("情報", "Modが選択されていません"); return

        self._start_btn.config(state="disabled")
        self._progress.configure(value=0, maximum=len(selected))
        self._nb.select(2)  # ログタブ

        threading.Thread(target=self._worker,
                          args=(selected, mc_ver, loader, mode, cf_key),
                          daemon=True).start()

    # ── ワーカースレッド ──
    def _worker(self, mods, mc_ver, loader, mode, cf_key):
        out_dir    = self.mods_dir.get()
        delete_old = self.delete_old.get()
        do_mr      = mode in (DL_MODE_BOTH, DL_MODE_MODRINTH)
        do_cf      = mode in (DL_MODE_BOTH, DL_MODE_CURSEFORGE)

        ok_list   = []
        fail_list = []

        for i, mod in enumerate(mods):
            name = mod.get("name", mod["filename"])
            self._set_status(f"{i+1}/{len(mods)}: {name[:28]}")
            self._log(f"\n── {name} ──", "info")

            dl_url = None; dl_fname = None; source = ""

            # ── Modrinth ──
            if do_mr:
                try:
                    sha1 = sha1_file(mod["path"])
                    pid  = mr_find_project(sha1, mod.get("mod_id",""))
                    if pid:
                        vs = mr_get_versions(pid, mc_ver, loader)
                        if vs:
                            for finfo in vs[0].get("files", []):
                                if finfo.get("primary") or not dl_url:
                                    dl_url   = finfo["url"]
                                    dl_fname = finfo["filename"]
                                    source   = "Modrinth"
                                    if finfo.get("primary"):
                                        break
                            self._log(f"  ✓ Modrinth: {dl_fname}", "ok")
                        else:
                            self._log(f"  Modrinth: {mc_ver}/{loader} 対応バージョンなし", "warn")
                    else:
                        self._log(f"  Modrinth: プロジェクト見つからず", "warn")
                except Exception as e:
                    self._log(f"  Modrinth エラー: {e}", "err")

            # ── CurseForge (fallback or primary) ──
            if do_cf and dl_url is None:
                try:
                    cf_id = cf_search_by_name(name, cf_key)
                    if cf_id:
                        finfo = cf_get_file(cf_id, mc_ver, loader, cf_key)
                        if finfo:
                            dl_url   = finfo.get("downloadUrl")
                            dl_fname = finfo.get("fileName")
                            source   = "CurseForge"
                            self._log(f"  ✓ CurseForge: {dl_fname}", "ok")
                        else:
                            self._log(f"  CurseForge: {mc_ver}/{loader} 対応バージョンなし", "warn")
                    else:
                        self._log(f"  CurseForge: Mod見つからず", "warn")
                except Exception as e:
                    self._log(f"  CurseForge エラー: {e}", "err")

            # ── ダウンロード ──
            if dl_url and dl_fname:
                dest = os.path.join(out_dir, dl_fname)
                try:
                    self._log(f"  ⬇ DL中 [{source}]: {dl_fname}")

                    def _pcb(p, _n=name):
                        self._set_status(f"DL: {_n[:20]} {p*100:.0f}%")

                    download_file(dl_url, dest, _pcb)

                    if delete_old and os.path.abspath(dest) != os.path.abspath(mod["path"]):
                        if os.path.exists(mod["path"]):
                            os.remove(mod["path"])
                            self._log(f"  🗑 旧ファイル削除: {mod['filename']}")

                    ok_list.append(name)
                    self._log(f"  ✅ 完了", "ok")
                except Exception as e:
                    fail_list.append((name, f"DLエラー: {e}"))
                    self._log(f"  ❌ DL失敗: {e}", "err")
            else:
                fail_list.append((name, "対応バージョンが見つかりませんでした"))
                self._log(f"  ❌ スキップ（対応バージョンなし）", "err")

            self._set_progress(i + 1)

        # ── サマリー ──
        self._log(f"\n{'═'*50}", "info")
        self._log(f"✅ 成功: {len(ok_list)} 件", "ok")
        for n in ok_list:
            self._log(f"   ✓ {n}", "ok")
        if fail_list:
            self._log(f"\n❌ 失敗: {len(fail_list)} 件（手動DLが必要）", "err")
            for n, r in fail_list:
                self._log(f"   ✗ {n}  →  {r}", "err")
        else:
            self._log("\n🎉 全Modの更新が完了しました！", "ok")

        self._set_status("完了")

        msg = f"✅ 成功: {len(ok_list)} 件\n❌ 失敗: {len(fail_list)} 件"
        if fail_list:
            msg += "\n\n手動DLが必要なMod:\n" + "\n".join(f"• {n}" for n,_ in fail_list)
        self.after(0, lambda: messagebox.showinfo("完了", msg))
        self.after(0, lambda: self._start_btn.config(state="normal"))

    # ── MCバージョン一覧をバックグラウンド取得 ──
    def _fetch_versions_bg(self):
        versions = fetch_mc_versions()
        def _update():
            self._ver_cb.config(values=versions)
            # 保存済みバージョンがリストにあればそのまま、なければ先頭を選択
            if self.target_version.get() not in versions:
                self.target_version.set(versions[0])
            self._ver_status.config(text=f"✅ {len(versions)} 件", foreground=GRN)
        self.after(0, _update)

    # ── 終了処理 ──
    def _on_close(self):
        save_config({
            "mods_dir":       self.mods_dir.get(),
            "target_version": self.target_version.get(),
            "target_loader":  self.target_loader.get(),
            "cf_api_key":     self.cf_api_key.get(),
            "dl_mode":        self.dl_mode.get(),
            "delete_old":     self.delete_old.get(),
        })
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
