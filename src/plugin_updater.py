import os, re, sys, json, zipfile, threading, tkinter as tk
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

THEMES = {
    "light": {"BG":"#f4f4f0","BG2":"#e8e8e3","BG3":"#d0d0c8","FG":"#1e1e1e","ACC":"#1d4ed8",
              "GRN":"#15803d","RED":"#dc2626","YEL":"#92400e","LOG":"#ffffff",
              "SEL":"#bfdbfe","SEL_FG":"#1e1e1e","BTN_FG":"#ffffff",
              "BTN_ACT":"#3b82f6","BTN_DIS":"#d0d0c8","TREE_SEL":"#bfdbfe","ICON":"🌙"},
    "dark":  {"BG":"#1e1e2e","BG2":"#2a2a3e","BG3":"#45475a","FG":"#cdd6f4","ACC":"#89b4fa",
              "GRN":"#a6e3a1","RED":"#f38ba8","YEL":"#f9e2af","LOG":"#181825",
              "SEL":"#313244","SEL_FG":"#cdd6f4","BTN_FG":"#1e1e2e",
              "BTN_ACT":"#74c7ec","BTN_DIS":"#45475a","TREE_SEL":"#45475a","ICON":"☀️"},
}
BG=BG2=BG3=FG=ACC=GRN=RED=YEL=""

def _apply_theme_globals(theme):
    global BG,BG2,BG3,FG,ACC,GRN,RED,YEL
    t=THEMES[theme]; BG,BG2,BG3,FG,ACC,GRN,RED,YEL=t["BG"],t["BG2"],t["BG3"],t["FG"],t["ACC"],t["GRN"],t["RED"],t["YEL"]
_apply_theme_globals("light")

def load_config():
    try:
        with open(CONFIG_FILE,encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def save_config(data):
    try:
        with open(CONFIG_FILE,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
    except Exception: pass

def http_get(url,headers=None):
    req=urllib.request.Request(url,headers=headers or {})
    req.add_header("User-Agent","Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    req.add_header("Accept","application/json,text/plain,*/*")
    req.add_header("Accept-Language","ja,en-US;q=0.9,en;q=0.8")
    req.add_header("Referer","https://api.spiget.org/")
    with urllib.request.urlopen(req,timeout=15) as r: return json.loads(r.read().decode())

def download_file(url,dest,progress_cb=None):
    req=urllib.request.Request(url)
    req.add_header("User-Agent","Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    req.add_header("Accept","application/octet-stream,*/*")
    req.add_header("Accept-Language","ja,en-US;q=0.9,en;q=0.8")
    req.add_header("Referer","https://api.spiget.org/")
    with urllib.request.urlopen(req,timeout=60) as r:
        total=int(r.headers.get("Content-Length",0)); done=0
        with open(dest,"wb") as f:
            while chunk:=r.read(65536):
                f.write(chunk); done+=len(chunk)
                if progress_cb and total: progress_cb(done/total)

def fetch_mc_versions():
    try:
        data=http_get(f"{MODRINTH_API}/tag/game_version")
        releases=[v["version"] for v in data if v.get("version_type")=="release" and "." in v.get("version","")]
        releases.sort(key=lambda v:tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]",v)),reverse=True)
        return releases or ["1.21.4","1.20.1","1.19.4","1.18.2"]
    except Exception: return ["1.21.4","1.20.1","1.19.4","1.18.2"]

def clean_plugin_name(raw):
    n=re.sub(r'[-_]v?\d+[\.\d]*[a-zA-Z\-]*$','',raw,flags=re.I)
    n=re.sub(r'[-_](velocity|bukkit|paper|spigot|bungee|fabric|forge|folia)$','',n,flags=re.I)
    return n.strip("-_ ") or raw

def read_jar_meta(jar_path):
    fname=os.path.basename(jar_path)
    base_name=clean_plugin_name(os.path.splitext(fname)[0])
    info={"filename":fname,"path":jar_path,"name":base_name,"version":"","depend":[]}
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names=zf.namelist()
            if "velocity-plugin.json" in names:
                d=json.loads(zf.read("velocity-plugin.json").decode("utf-8",errors="ignore"))
                info["name"]=d.get("name") or d.get("id") or base_name
                info["version"]=d.get("version","")
                info["depend"]=list(d.get("dependencies",{}).keys())
                return info
            yml=next((n for n in ("plugin.yml","paper-plugin.yml","bungee.yml") if n in names),None)
            if yml:
                raw=zf.read(yml).decode("utf-8",errors="ignore")
                for line in raw.splitlines():
                    line=line.strip()
                    if line.startswith("name:"): info["name"]=line.split(":",1)[1].strip().strip('"\'')
                    elif line.startswith("version:"): info["version"]=line.split(":",1)[1].strip().strip('"\'')
                    elif line.startswith("depend:"):
                        ds=line.split(":",1)[1].strip().strip("[]")
                        info["depend"]=[d.strip().strip('"\'') for d in ds.split(",") if d.strip()]
    except Exception: pass
    return info

# ── Spiget API ────────────────────────────────────────────────
def spiget_search(name):
    """完全一致優先でリソースIDを取得"""
    try:
        encoded=urllib.parse.quote(name,safe="")
        params=urllib.parse.urlencode({"size":10,"sort":"-downloads","fields":"id,name,external"})
        results=http_get(f"{SPIGET_API}/search/resources/{encoded}?{params}")
        if not isinstance(results,list) or not results: return None
        name_l=name.lower()
        for r in results:
            if r.get("name","").lower()==name_l:
                return int(r["id"])
        for r in results:
            if name_l in r.get("name","").lower() and not r.get("external"):
                return int(r["id"])
        if not results[0].get("external"):
            return int(results[0]["id"])
        return None
    except Exception: return None

def spiget_get_latest(rid):
    try: return http_get(f"{SPIGET_API}/resources/{rid}/versions/latest")
    except Exception: return None

def spiget_get_versions(rid,size=30):
    try:
        params=urllib.parse.urlencode({"size":size,"sort":"-releaseDate"})
        return http_get(f"{SPIGET_API}/resources/{rid}/versions?{params}")
    except Exception: return []

def spiget_download_url(rid,version_id=None):
    if version_id:
        return f"{SPIGET_API}/resources/{rid}/versions/{version_id}/download"
    return f"{SPIGET_API}/resources/{rid}/versions/latest/download"

# ── Modrinth API ──────────────────────────────────────────────
def mr_search_plugin(name):
    try:
        params=urllib.parse.urlencode({"query":name,"limit":5,"facets":json.dumps([["project_type:plugin"]])})
        hits=http_get(f"{MODRINTH_API}/search?{params}").get("hits",[])
        if not hits: return None
        name_l=name.lower()
        for h in hits:
            if h.get("title","").lower()==name_l: return h["project_id"]
        return hits[0]["project_id"]
    except Exception: return None

def mr_get_plugin_versions(pid):
    try:
        params=urllib.parse.urlencode({"loaders":json.dumps(["paper","spigot","bukkit","purpur","folia","waterfall","velocity"])})
        return http_get(f"{MODRINTH_API}/project/{pid}/version?{params}")
    except Exception: return []

def mr_best_file(vo):
    du=df=None
    for fi in vo.get("files",[]):
        if fi.get("primary") or not du: du,df=fi["url"],fi["filename"]
        if fi.get("primary"): break
    return du,df

# ── 統合検索 ──────────────────────────────────────────────────
def find_plugin(name,mode,log_cb,ver_id=None,spiget_rid=None):
    do_mr=mode in (DL_BOTH_MR,DL_BOTH_SP,DL_MR)
    do_sp=mode in (DL_BOTH_MR,DL_BOTH_SP,DL_SP)
    sp_first=mode==DL_BOTH_SP
    dl_url=dl_fname=source=res_info=None

    def _try_mr():
        nonlocal dl_url,dl_fname,source,res_info
        try:
            pid=mr_search_plugin(name)
            if not pid: log_cb("  Modrinth: 見つからず","warn"); return
            if ver_id:
                v_data=http_get(f"{MODRINTH_API}/version/{ver_id}")
                vs=[v_data]
            else:
                vs=mr_get_plugin_versions(pid)
            if not vs: log_cb("  Modrinth: 対応なし","warn"); return
            dl_url,dl_fname=mr_best_file(vs[0]); source="Modrinth"
            res_info={"type":"modrinth","id":pid,"version_obj":vs[0]}
            log_cb(f"  ✓ Modrinth: {dl_fname}","ok")
        except Exception as e: log_cb(f"  Modrinth エラー: {e}","err")

    def _try_sp():
        nonlocal dl_url,dl_fname,source,res_info
        try:
            rid=spiget_rid or spiget_search(name)
            if not rid: log_cb("  Spiget: 見つからず","warn"); return
            latest=spiget_get_latest(rid)
            ver_name=latest.get("name","") if latest else ""
            sp_ver_id=latest.get("id") if latest else None
            if ver_id: sp_ver_id=ver_id
            dl_url=spiget_download_url(rid,sp_ver_id)
            res_name=name
            dl_fname=f"{res_name}-{ver_name}.jar".replace(" ","_")
            source="Spiget"
            res_info={"type":"spiget","id":rid,"ver_id":sp_ver_id}
            log_cb(f"  ✓ Spiget: {res_name} v{ver_name}","ok")
        except Exception as e: log_cb(f"  Spiget エラー: {e}","err")

    if sp_first:
        if do_sp: _try_sp()
        if do_mr and not dl_url: _try_mr()
    else:
        if do_mr: _try_mr()
        if do_sp and not dl_url: _try_sp()
    return dl_url,dl_fname,source,res_info

# ══════════════════════════════════════════════════════════════
class PluginUpdaterApp(ttk.Frame):
    def __init__(self,parent,theme="light",icon_path=None,parent_app=None,**kw):
        super().__init__(parent,**kw)
        self._theme=theme; self._icon_path=icon_path; self._parent_app=parent_app
        self._running=False; self._cancel_flag=False
        _apply_theme_globals(theme)
        cfg=load_config()
        self.plugins_dir   =tk.StringVar(value=cfg.get("plugins_dir",""))
        self.dl_mode       =tk.StringVar(value=cfg.get("dl_mode",DL_BOTH_MR))
        self.delete_old    =tk.BooleanVar(value=cfg.get("delete_old",False))
        self.delete_failed =tk.BooleanVar(value=cfg.get("delete_failed",False))
        self.auto_deps     =tk.BooleanVar(value=cfg.get("auto_deps",True))
        self.plugin_list   =[]
        self._ver_overrides={}
        self._current_iid  =None
        self._versions_cache=[]
        self._spiget_rid_cache={}  # filename -> spiget resource id
        self._settings_scroll_init=False
        self._build()

    def _build(self):
        nb=ttk.Notebook(self); nb.pack(fill="both",expand=True)
        t_set=ttk.Frame(nb); nb.add(t_set,text=" ⚙ 設定 ")
        t_lst=ttk.Frame(nb); nb.add(t_lst,text=" 🔌 プラグイン一覧 ")
        t_log=ttk.Frame(nb); nb.add(t_log,text=" 📋 ログ ")
        self._nb=nb
        self._build_settings(t_set)
        self._build_list(t_lst)
        self._build_log(t_log)
        bar=ttk.Frame(self); bar.pack(fill="x",padx=8,pady=(0,6))
        self._progress=ttk.Progressbar(bar,mode="determinate")
        self._progress.pack(side="left",fill="x",expand=True,padx=(0,8))
        self._prog_label=ttk.Label(bar,text="",width=30); self._prog_label.pack(side="left")
        self._cancel_btn=ttk.Button(bar,text="⏹ 中止",command=self._cancel,state="disabled")
        self._cancel_btn.pack(side="left",padx=(6,0))

    def _build_settings(self,p):
        t=THEMES[self._theme]
        canvas=tk.Canvas(p,bg=t["BG"],highlightthickness=0)
        vsb=ttk.Scrollbar(p,orient="vertical",command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right",fill="y"); canvas.pack(side="left",fill="both",expand=True)
        self._settings_canvas=canvas
        f=ttk.Frame(canvas)
        wid=canvas.create_window((0,0),window=f,anchor="nw")
        def _update_scroll(e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            if not self._settings_scroll_init:
                canvas.yview_moveto(0); self._settings_scroll_init=True
        f.bind("<Configure>",lambda e: self.after(10,_update_scroll))
        canvas.bind("<Configure>",lambda e: canvas.itemconfig(wid,width=e.width))
        def _wheel(e):
            if isinstance(e.widget,ttk.Combobox): return
            try:
                if e.widget.winfo_toplevel()!=self.winfo_toplevel(): return
            except Exception: return
            canvas.yview_scroll(int(-1*(e.delta/120)),"units")
        canvas.bind_all("<MouseWheel>",_wheel)
        PAD=dict(padx=12,pady=(0,8))

        lf0=ttk.LabelFrame(f,text="🔌  Pluginsフォルダ"); lf0.pack(fill="x",padx=12,pady=(8,8))
        r0=ttk.Frame(lf0); r0.pack(fill="x",padx=10,pady=8)
        ttk.Entry(r0,textvariable=self.plugins_dir).pack(side="left",fill="x",expand=True,padx=(0,6))
        ttk.Button(r0,text="参照",command=lambda:self._browse(self.plugins_dir)).pack(side="left",padx=(0,6))
        ttk.Button(r0,text="📂 読み込む",command=self._load_plugins).pack(side="left",padx=(0,6))
        ttk.Button(r0,text="⬇ ダウンロード",command=self._start_update).pack(side="left",padx=(0,6))
        ttk.Button(r0,text="✕",command=lambda:self.plugins_dir.set(""),width=3).pack(side="left")

        lf3=ttk.LabelFrame(f,text="🌐  ダウンロード設定"); lf3.pack(fill="x",**PAD)
        r3=ttk.Frame(lf3); r3.pack(fill="x",padx=10,pady=(8,4))
        ttk.Label(r3,text="モード:").pack(side="left")
        self._dl_cb=ttk.Combobox(r3,textvariable=self.dl_mode,values=DL_MODES,width=24,state="readonly")
        self._dl_cb.pack(side="left",padx=(4,0))
        self._dl_cb.bind("<<ComboboxSelected>>",lambda _:self._update_mode_ui())
        self._mode_desc=ttk.Label(lf3,text="",foreground=t["YEL"],background=t["BG"],font=("Yu Gothic UI",9))
        self._mode_desc.pack(anchor="w",padx=10,pady=(0,8))
        self._update_mode_ui()

        lf4=ttk.LabelFrame(f,text="⚙  オプション"); lf4.pack(fill="x",**PAD)
        for txt,var in [
            ("アップデート後に古いファイルを削除する",self.delete_old),
            ("ダウンロード失敗したファイルを削除する（壊れたファイル除去）",self.delete_failed),
            ("前提プラグインが足りなければ自動でダウンロードする",self.auto_deps),
        ]:
            ttk.Checkbutton(lf4,text=txt,variable=var).pack(padx=10,pady=2,anchor="w")

        # 注意書き
        lf5=ttk.LabelFrame(f,text="⚠  注意"); lf5.pack(fill="x",**PAD)
        msg=("このツールはプラグインのバージョンを選択または最新版にアップデートする機能を提供しますが、"
             "お使いのMinecraftサーバーのバージョンで正常に動作するとは限りません。"
             "アップデート前に必ずバックアップを取り、自己責任でご使用ください。")
        ttk.Label(lf5,text=msg,wraplength=580,justify="left",
                   foreground=t["RED"],background=t["BG"],
                   font=("Yu Gothic UI",9)).pack(padx=10,pady=8,anchor="w")

        ttk.Frame(f,height=10).pack()

    def _build_list(self,p):
        top=ttk.Frame(p); top.pack(fill="x",padx=6,pady=(6,2))
        for text,w,cmd in [("全選択",6,lambda:self._sel_all(True)),("全解除",6,lambda:self._sel_all(False))]:
            ttk.Button(top,text=text,width=w,command=cmd).pack(side="left",padx=(0,3))
        ttk.Separator(top,orient="vertical").pack(side="left",fill="y",padx=(0,6),pady=2)
        ttk.Button(top,text="📂 読込",width=7,command=self._load_plugins).pack(side="left",padx=(0,3))
        ttk.Button(top,text="⬇ 更新",width=7,command=self._start_update).pack(side="left")
        self._sel_label=ttk.Label(top,text="0 / 0 件",width=12,anchor="e"); self._sel_label.pack(side="right",padx=4)

        body=ttk.Frame(p); body.pack(fill="both",expand=True)
        left=ttk.Frame(body); left.pack(side="left",fill="both",expand=True)
        cols=("chk","name","version")
        heads=[("chk","✔",36),("name","プラグイン名",220),("version","バージョン",90)]
        self._tree=ttk.Treeview(left,columns=cols,show="headings",selectmode="none")
        for cid,lbl,w in heads:
            self._tree.heading(cid,text=lbl)
            self._tree.column(cid,width=w,minwidth=w if cid!="name" else 80,
                               anchor="center" if cid=="chk" else "w",stretch=(cid=="name"))
        vsb=ttk.Scrollbar(left,orient="vertical",command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left",fill="both",expand=True,padx=(4,0),pady=(0,4))
        vsb.pack(side="left",fill="y",pady=(0,4),padx=(0,4))
        self._tree.bind("<Button-1>",self._on_click)
        self._tree.bind("<ButtonRelease-1>",self._on_select)

        # サイドパネル
        self._side=ttk.LabelFrame(body,text="  📋 詳細  ")
        self._side.pack(side="left",fill="y",padx=(4,4),pady=(0,4))
        self._side.configure(width=220); self._side.pack_propagate(False)
        sc=tk.Canvas(self._side,highlightthickness=0); sv=ttk.Scrollbar(self._side,orient="vertical",command=sc.yview)
        sc.configure(yscrollcommand=sv.set); sv.pack(side="right",fill="y"); sc.pack(side="left",fill="both",expand=True)
        sf=ttk.Frame(sc); sw=sc.create_window((0,0),window=sf,anchor="nw")
        sf.bind("<Configure>",lambda e:sc.configure(scrollregion=sc.bbox("all")))
        sc.bind("<Configure>",lambda e:sc.itemconfig(sw,width=e.width))
        sc.bind("<MouseWheel>",lambda e:sc.yview_scroll(int(-1*(e.delta/120)),"units"))
        self._side_canvas=sc

        ttk.Label(sf,text="選択中:",font=("Yu Gothic UI",8)).pack(anchor="w",padx=8,pady=(8,0))
        self._side_name=ttk.Label(sf,text="—",wraplength=195,font=("Yu Gothic UI",9,"bold"))
        self._side_name.pack(anchor="w",padx=8,pady=(0,6))
        ttk.Separator(sf,orient="horizontal").pack(fill="x",padx=8,pady=4)
        ttk.Label(sf,text="バージョン:").pack(anchor="w",padx=8,pady=(0,2))
        self._ver_var=tk.StringVar(value="最新")
        self._ver_combo=ttk.Combobox(sf,textvariable=self._ver_var,state="readonly",width=24)
        self._ver_combo.pack(padx=8,pady=(0,2),fill="x")
        self._ver_combo.bind("<<ComboboxSelected>>",self._on_ver_select)
        self._ver_status_side=ttk.Label(sf,text="",foreground=YEL,font=("Yu Gothic UI",8))
        self._ver_status_side.pack(anchor="w",padx=8,pady=(0,4))
        ttk.Button(sf,text="🔄 バージョン取得",command=self._fetch_versions_side).pack(padx=8,pady=(0,8),fill="x")

    def _build_log(self,p):
        t=THEMES[self._theme]
        self._log_box=scrolledtext.ScrolledText(p,bg=t["LOG"],fg=t["FG"],
            selectbackground=t["SEL"],selectforeground=t["SEL_FG"],
            insertbackground=t["FG"],font=("Consolas",9),relief="flat",wrap="word")
        self._log_box.pack(fill="both",expand=True,padx=8,pady=8)
        for tag,color in [("ok",t["GRN"]),("err",t["RED"]),("info",t["ACC"]),("warn",t["YEL"])]:
            self._log_box.tag_config(tag,foreground=color)
        ttk.Button(p,text="クリア",command=lambda:self._log_box.delete("1.0","end")).pack(pady=(0,8))

    def _log(self,msg,tag=""):
        def _do(): self._log_box.insert("end",msg+"\n",tag); self._log_box.see("end")
        self.after(0,_do)
    def _set_status(self,msg): self.after(0,lambda:self._prog_label.config(text=msg))
    def _set_progress(self,v,maximum=None):
        def _do():
            if maximum is not None: self._progress.configure(maximum=maximum)
            self._progress.configure(value=v)
        self.after(0,_do)

    def _update_mode_ui(self):
        mode=self.dl_mode.get()
        desc={DL_BOTH_MR:"Modrinthで検索 → なければSpigetも",DL_BOTH_SP:"Spigetで検索 → なければModrinthも",
              DL_MR:"Modrinthのみ",DL_SP:"Spigetのみ"}.get(mode,"")
        self._mode_desc.config(text=f"  ℹ {desc}")

    def _browse(self,var):
        d=filedialog.askdirectory()
        if d: var.set(d)

    def _cancel(self):
        self._cancel_flag=True; self._set_status("中止中...")
        self._cancel_btn.config(state="disabled")

    def _on_click(self,e):
        row=self._tree.identify_row(e.y)
        if row and self._tree.identify_column(e.x)=="#1":
            cur=self._tree.set(row,"chk"); self._tree.set(row,"chk","☑" if cur=="☐" else "☐")
            self._upd_label()
        if row: self._tree.selection_set(row); self._on_select(e)

    def _on_select(self,e=None):
        rows=self._tree.selection()
        if not rows: return
        row=rows[0]
        if row==self._current_iid: return
        self._current_iid=row
        item=next((it for it in self.plugin_list if it["filename"]==row),None)
        if not item: return
        self._side_name.config(text=item.get("name",row))
        self._ver_combo["values"]=["最新"]
        self._ver_var.set("最新")
        self._ver_status_side.config(text="← バージョン取得ボタンで一覧を取得")
        self._versions_cache=[]

    def _fetch_versions_side(self):
        if not self._current_iid: return
        item=next((it for it in self.plugin_list if it["filename"]==self._current_iid),None)
        if not item: return
        self._ver_status_side.config(text="🔄 取得中...",foreground=YEL)
        self._ver_combo.config(state="disabled")
        mode=self.dl_mode.get()

        def _fetch():
            results=[]
            # Modrinthバージョン取得
            try:
                if mode in (DL_BOTH_MR,DL_BOTH_SP,DL_MR):
                    pid=mr_search_plugin(item.get("name",""))
                    if pid:
                        vs=mr_get_plugin_versions(pid)
                        for v in vs:
                            results.append({"label":f"[MR] {v.get('version_number','?')}","id":v["id"],"source":"modrinth"})
            except Exception: pass
            # Spigetバージョン取得
            try:
                if mode in (DL_BOTH_MR,DL_BOTH_SP,DL_SP):
                    rid=self._spiget_rid_cache.get(item["filename"]) or spiget_search(item.get("name",""))
                    if rid:
                        self._spiget_rid_cache[item["filename"]]=rid
                        versions=spiget_get_versions(rid)
                        for v in versions:
                            results.append({"label":f"[SP] {v.get('name','?')}","id":v.get("id"),"source":"spiget"})
            except Exception: pass
            self.after(0,lambda r=results:self._update_ver_combo(r))

        threading.Thread(target=_fetch,daemon=True).start()

    def _update_ver_combo(self,results):
        self._versions_cache=results
        labels=["最新"]+[r["label"] for r in results]
        self._ver_combo["values"]=labels; self._ver_combo.config(state="readonly")
        self._ver_var.set("最新")
        self._ver_status_side.config(
            text=f"✅ {len(results)} 件取得" if results else "⚠ バージョンなし",
            foreground=GRN if results else RED)

    def _on_ver_select(self,e=None):
        if not self._current_iid: return
        label=self._ver_var.get()
        if label=="最新": self._ver_overrides.pop(self._current_iid,None)
        else:
            ver=next((v for v in self._versions_cache if v["label"]==label),None)
            self._ver_overrides[self._current_iid]=ver
        self._ver_status_side.config(
            text="✅ 最新でDL" if label=="最新" else f"✅ {label} を選択",foreground=GRN)

    def _sel_all(self,v):
        mark="☑" if v else "☐"
        for row in self._tree.get_children(): self._tree.set(row,"chk",mark)
        self._upd_label()

    def _upd_label(self):
        rows=self._tree.get_children()
        sel=sum(1 for r in rows if self._tree.set(r,"chk")=="☑")
        self._sel_label.config(text=f"{sel} / {len(rows)} 件選択")

    def _disable_combobox_wheel(self):
        def _block(e): return "break"
        def _bind(w):
            if isinstance(w,ttk.Combobox):
                for ev in ("<MouseWheel>","<Button-4>","<Button-5>"): w.bind(ev,_block)
            for c in w.winfo_children(): _bind(c)
        _bind(self)

    def _load_plugins(self):
        d=self.plugins_dir.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror("エラー","有効なpluginsフォルダを指定してください"); return
        jars=sorted(f for f in os.listdir(d) if f.lower().endswith(".jar"))
        if not jars: messagebox.showinfo("情報","JARファイルが見つかりませんでした"); return
        for row in self._tree.get_children(): self._tree.delete(row)
        self.plugin_list=[]; self._ver_overrides.clear(); self._current_iid=None
        self._side_name.config(text="—"); self._ver_combo["values"]=["最新"]; self._ver_var.set("最新")
        self._log(f"📂 {len(jars)} 個のJARを解析中...","info")
        for fname in jars:
            info=read_jar_meta(os.path.join(d,fname)); self.plugin_list.append(info)
        self.plugin_list.sort(key=lambda x:x.get("name","").lower())
        for it in self.plugin_list:
            self._tree.insert("","end",iid=it["filename"],
                               values=("☑",it.get("name",it["filename"]),it.get("version","?")))
        self._upd_label()
        self._log(f"✅ {len(jars)} 件読み込み完了","ok")
        app=self._parent_app
        if app and hasattr(app,"auto_switch_tab"):
            if app.auto_switch_tab.get(): self._nb.select(1)
        else: self._nb.select(1)
        if app and hasattr(app,"_show_toast"): app._show_toast("プラグインを読み込みました。")

    def _start_update(self):
        selected=[it for it in self.plugin_list
                  if self._tree.exists(it["filename"]) and self._tree.set(it["filename"],"chk")=="☑"]
        if not selected: messagebox.showinfo("情報","プラグインが選択されていません"); return
        if self._running: messagebox.showwarning("実行中","現在アップデート中です"); return
        self._running=True; self._cancel_flag=False
        self._set_progress(0,len(selected)); self._nb.select(2)
        self.after(0,lambda:self._cancel_btn.config(state="normal"))
        threading.Thread(target=self._worker,args=(selected,self.dl_mode.get()),daemon=True).start()

    def _worker(self,plugins,mode):
        delete_old=self.delete_old.get(); delete_fail=self.delete_failed.get()
        auto_deps=self.auto_deps.get(); out_dir=self.plugins_dir.get()
        done_deps=set(); ok_list=[]; fail_list=[]
        for i,plugin in enumerate(plugins):
            if self._cancel_flag: self._log("\n⏹ 中止されました","warn"); break
            name=plugin.get("name",plugin["filename"])
            override=self._ver_overrides.get(plugin["filename"])
            self._set_status(f"{i+1}/{len(plugins)}: {name[:24]}")
            self._log(f"\n── {name} ──","info")
            def _log(msg,tag=""): self._log(msg,tag)
            # バージョン指定の解決
            mr_ver_id=None; sp_ver_id=None; sp_rid=self._spiget_rid_cache.get(plugin["filename"])
            if override:
                src=override.get("source","")
                if src=="modrinth": mr_ver_id=override["id"]
                elif src=="spiget": sp_ver_id=override["id"]
            dl_url,dl_fname,source,res_info=find_plugin(name,mode,_log,mr_ver_id,sp_rid)
            # Spigetの場合はver_id上書き
            if override and override.get("source")=="spiget" and res_info and res_info.get("type")=="spiget":
                rid=res_info["id"]
                dl_url=spiget_download_url(rid,sp_ver_id)
            if dl_url and dl_fname:
                dest=os.path.join(out_dir,dl_fname)
                if self._do_download(dl_url,dest,name,source,plugin.get("path"),delete_old,delete_fail):
                    ok_list.append(name)
                    if auto_deps:
                        for dep_name in plugin.get("depend",[]):
                            if not dep_name or dep_name in done_deps: continue
                            done_deps.add(dep_name)
                            if any(p.get("name","").lower()==dep_name.lower() for p in self.plugin_list):
                                self._log(f"  🔗 前提プラグイン既存: {dep_name}","ok"); continue
                            self._log(f"  🔗 前提プラグイン DL: {dep_name}","info")
                            du,df,src,_=find_plugin(dep_name,mode,_log)
                            if du and df and not os.path.exists(os.path.join(out_dir,df)):
                                self._do_download(du,os.path.join(out_dir,df),dep_name,src,None,False,delete_fail)
                                ok_list.append(f"[前提] {dep_name}")
                else: fail_list.append(name)
            else:
                fail_list.append(name)
                self._log("  ❌ スキップ","err")
                if delete_fail and plugin.get("path") and os.path.exists(plugin["path"]):
                    try: os.remove(plugin["path"]); self._log("  🗑 失敗ファイル削除","warn")
                    except Exception: pass
            self._set_progress(i+1)
        self._log(f"\n{'═'*40}","info")
        self._log(f"✅ 成功: {len(ok_list)} 件","ok")
        for n in ok_list: self._log(f"   ✓ {n}","ok")
        if fail_list:
            self._log(f"❌ 失敗: {len(fail_list)} 件","err")
            for n in fail_list: self._log(f"   ✗ {n}","err")
        else: self._log("🎉 全て完了！","ok")
        self._set_status("完了" if not self._cancel_flag else "中止")
        self._running=False; self.after(0,lambda:self._cancel_btn.config(state="disabled"))
        msg=f"✅ 成功: {len(ok_list)} 件\n❌ 失敗: {len(fail_list)} 件"
        if fail_list: msg+="\n\n失敗:\n"+"\n".join(f"  • {n}" for n in fail_list)
        self.after(0,lambda:messagebox.showinfo("完了",msg))

    def _do_download(self,url,dest,name,source,old_path,delete_old,delete_fail):
        try:
            self._log(f"  ⬇ DL中 [{source}]: {os.path.basename(dest)}")
            download_file(url,dest,lambda p:self._set_status(f"DL: {name[:18]} {p*100:.0f}%"))
            if delete_old and old_path and os.path.exists(old_path):
                if os.path.abspath(dest)!=os.path.abspath(old_path):
                    os.remove(old_path); self._log(f"  🗑 旧ファイル削除: {os.path.basename(old_path)}","warn")
            self._log("  ✅ 完了","ok"); return True
        except Exception as e:
            self._log(f"  ❌ DL失敗: {e}","err")
            if os.path.exists(dest):
                try: os.remove(dest)
                except Exception: pass
            if delete_fail and old_path and os.path.exists(old_path):
                try: os.remove(old_path); self._log("  🗑 失敗ファイル削除","warn")
                except Exception: pass
            return False

    def apply_theme(self,theme):
        self._theme=theme; t=THEMES[theme]
        self._settings_canvas.config(bg=t["BG"])
        self._log_box.config(bg=t["LOG"],fg=t["FG"],selectbackground=t["SEL"],
                              selectforeground=t["SEL_FG"],insertbackground=t["FG"])
        for tag,color in [("ok",t["GRN"]),("err",t["RED"]),("info",t["ACC"]),("warn",t["YEL"])]:
            self._log_box.tag_config(tag,foreground=color)
        self._tree.configure(background=t["BG2"],foreground=t["FG"],fieldbackground=t["BG2"])
        self._mode_desc.config(foreground=t["YEL"],background=t["BG"])

    def save_config(self):
        cfg=load_config()
        cfg.update({"plugins_dir":self.plugins_dir.get(),"dl_mode":self.dl_mode.get(),
                     "delete_old":self.delete_old.get(),"delete_failed":self.delete_failed.get(),
                     "auto_deps":self.auto_deps.get()})
        save_config(cfg)

# ── スタンドアロン ────────────────────────────────────────────
class StandaloneApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🔌 MC Plugin Updater"); self.geometry("900x700")
        self.configure(bg=BG); self.resizable(True,True)
        cfg=load_config(); self._theme=cfg.get("theme","light")
        _apply_theme_globals(self._theme)
        try:
            import ctypes; ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MCPluginUpdater.App.1.0")
        except Exception: pass
        try:
            base=getattr(sys,"_MEIPASS",os.path.dirname(os.path.abspath(__file__)))
            ip=os.path.join(base,"icon.ico"); self._icon_path=ip if os.path.exists(ip) else None
            if self._icon_path: self.iconbitmap(default=self._icon_path)
        except Exception: self._icon_path=None
        self._apply_style(); self._build_ui()
        self.protocol("WM_DELETE_WINDOW",self._on_close)

    def _apply_style(self):
        t=THEMES[self._theme]; B,B2,B3,F,A=t["BG"],t["BG2"],t["BG3"],t["FG"],t["ACC"]
        s=ttk.Style(self); s.theme_use("clam")
        s.configure("TFrame",background=B); s.configure("TLabel",background=B,foreground=F,font=("Yu Gothic UI",10))
        s.configure("Hdr.TLabel",background=B,foreground=A,font=("Yu Gothic UI",13,"bold"))
        s.configure("Sub.TLabel",background=B,foreground=F,font=("Yu Gothic UI",9))
        s.configure("TButton",background=A,foreground=t["BTN_FG"],font=("Yu Gothic UI",10,"bold"),relief="flat",padding=(8,5))
        s.map("TButton",background=[("active",t["BTN_ACT"]),("disabled",t["BTN_DIS"])],foreground=[("disabled","#6c7086")])
        s.configure("TEntry",fieldbackground=B2,foreground=F,insertcolor=F,relief="flat",padding=4)
        s.configure("TCheckbutton",background=B,foreground=F,font=("Yu Gothic UI",10)); s.map("TCheckbutton",background=[("active",B)])
        s.configure("TCombobox",fieldbackground=B2,foreground=F,selectbackground=B2,selectforeground=F,padding=4)
        s.map("TCombobox",fieldbackground=[("readonly",B2),("disabled",B3)],foreground=[("readonly",F),("disabled","#6c7086")],
              selectbackground=[("readonly",B2)],selectforeground=[("readonly",F)])
        s.configure("Treeview",background=B2,foreground=F,fieldbackground=B2,rowheight=26,font=("Yu Gothic UI",9))
        s.configure("Treeview.Heading",background=B,foreground=A,font=("Yu Gothic UI",9,"bold"),relief="flat")
        s.map("Treeview",background=[("selected",t["TREE_SEL"])],foreground=[("selected",t["SEL_FG"])])
        s.map("Treeview.Heading",background=[("active",B2),("pressed",B2)],foreground=[("active",A),("pressed",A)],
              relief=[("active","flat"),("pressed","flat")])
        s.configure("TProgressbar",troughcolor=B2,background=A,thickness=8)
        s.configure("TNotebook",background=B,tabmargins=0)
        s.configure("TNotebook.Tab",background=B2,foreground=F,padding=[14,7],font=("Yu Gothic UI",10))
        s.map("TNotebook.Tab",background=[("selected",B)],foreground=[("selected",A)])
        s.configure("TLabelframe",background=B,relief="solid",borderwidth=1,bordercolor=B3)
        s.configure("TLabelframe.Label",background=B,foreground=A,font=("Yu Gothic UI",10,"bold"))
        s.configure("TSeparator",background=B3); self.configure(bg=B)

    def _build_ui(self):
        t=THEMES[self._theme]
        hdr=ttk.Frame(self); hdr.pack(fill="x",padx=12,pady=(12,0))
        hdr.columnconfigure(0,weight=1); hdr.columnconfigure(1,weight=1); hdr.columnconfigure(2,weight=1)
        ttk.Label(hdr,text="🔌  MC Plugin Updater",style="Hdr.TLabel").grid(row=0,column=1)
        self._theme_btn=ttk.Button(hdr,text=t["ICON"],command=self._toggle_theme,width=3)
        self._theme_btn.grid(row=0,column=2,sticky="e")
        ttk.Label(self,text="Spigot / Paper / Bukkit プラグインを一括アップデート",style="Sub.TLabel").pack(pady=(2,8))
        self._plugin_app=PluginUpdaterApp(self,theme=self._theme,icon_path=self._icon_path)
        self._plugin_app.pack(fill="both",expand=True,padx=12,pady=(0,4))
        self._plugin_app._disable_combobox_wheel()

    def _toggle_theme(self):
        self._theme="dark" if self._theme=="light" else "light"
        _apply_theme_globals(self._theme); self._apply_style()
        self._theme_btn.config(text=THEMES[self._theme]["ICON"])
        self._plugin_app.apply_theme(self._theme)

    def _on_close(self):
        self._plugin_app.save_config()
        cfg=load_config(); cfg["theme"]=self._theme; save_config(cfg)
        self.destroy()

if __name__=="__main__":
    app=StandaloneApp(); app.mainloop()
