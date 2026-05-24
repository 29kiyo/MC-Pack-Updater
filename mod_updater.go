package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha1"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/data/binding"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"
	"github.com/gen2brain/go-fitz"
)

// 定数定義
const (
	ModrinthAPI   = "https://api.modrinth.com/v2"
	CurseForgeAPI = "https://api.curseforge.com/v1"
	UserAgent     = "MC-Pack-Updater/6.0"
)

var MCVersionsFallback = []string{
	"1.21.4", "1.21.3", "1.21.1", "1.21", "1.20.6", "1.20.4", "1.20.2", "1.20.1", "1.20",
	"1.19.4", "1.19.3", "1.19.2", "1.19.1", "1.19", "1.18.2", "1.18.1", "1.18",
	"1.17.1", "1.17", "1.16.5", "1.16.4", "1.16.3", "1.16.2", "1.16.1", "1.15.2", "1.12.2",
}

var Loaders = []string{"fabric", "forge", "neoforge", "quilt"}

const (
	DlBoth     = "両方（Modrinth優先）"
	DlCfFirst  = "両方（CurseForge優先）"
	DlMr       = "Modrinthのみ"
	DlCf       = "CurseForgeのみ"
)
var DlModes = []string{DlBoth, DlCfFirst, DlMr, DlCf}

var CfLoader = map[string]int{"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
const (
	CfGame  = 432
	CfMod   = 6
	CfRp    = 12
	CfShade = 6552
)
const (
	MrMod   = "mod"
	MrRp    = "resourcepack"
	MrShade = "shader"
)

var LoaderMin = map[string][]int{
	"forge":    {1, 1},
	"fabric":   {1, 14},
	"quilt":    {1, 16},
	"neoforge": {1, 20, 1},
}

// 設定構造体
type Config struct {
	ProfileDir    string `json:"profile_dir"`
	ModsDir       string `json:"mods_dir"`
	RpDir         string `json:"rp_dir"`
	ShaderDir     string `json:"shader_dir"`
	TargetVersion string `json:"target_version"`
	TargetLoader  string `json:"target_loader"`
	CfApiKey      string `json:"cf_api_key"`
	DlMode        string `json:"dl_mode"`
	DeleteOld     bool   `json:"delete_old"`
	DeleteFailed  bool   `json:"delete_failed"`
	AutoDeps      bool   `json:"auto_deps"`
	StrictDeps    bool   `json:"strict_deps"`
	Theme         string `json:"theme"`
}

type ItemInfo struct {
	Filename    string `json:"filename"`
	Path        string `json:"path"`
	Name        string `json:"name"`
	DisplayName string `json:"display_name"`
	ModID       string `json:"mod_id"`
	Version     string `json:"version"`
	Loader      string `json:"loader"`
	Selected    bool   `json:"-"`
}

type Task struct {
	Item    ItemInfo
	OutDir  string
	MrType  string
	CfClass int
}

// アプリケーション状態
type AppState struct {
	Config      Config
	ConfigFile  string
	MainWindow  fyne.Window
	LogBoxes    map[string]*widget.Entry
	Progress    *widget.ProgressBar
	ProgLabel   *widget.Label
	CancelBtn   *widget.Button
	CancelFlag  bool
	Running     bool
	Mu          sync.Mutex
	ModPanel    *FileListPanel
	RpPanel     *FileListPanel
	ShaderPanel *FileListPanel
	VerSelect   *widget.Select
	LoadSelect  *widget.Select
	DlModeSelect *widget.Select
	CfKeyEntry  *widget.Entry
	VerStatus   *widget.Label
}

func getConfigFile() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".mc_pack_updater_config.json")
}

func loadConfig(path string) Config {
	var cfg Config
	cfg.TargetVersion = "1.21.4"
	cfg.TargetLoader = "fabric"
	cfg.DlMode = DlBoth
	cfg.AutoDeps = true
	cfg.Theme = "light"

	file, err := os.Open(path)
	if err != nil {
		return cfg
	}
	defer file.Close()
	json.NewDecoder(file).Decode(&cfg)
	return cfg
}

func (s *AppState) saveConfig() {
	file, err := os.Create(s.ConfigFile)
	if err != nil {
		return
	}
	defer file.Close()
	enc := json.NewEncoder(file)
	enc.SetIndent("", "  ")
	enc.Encode(s.Config)
}

// ユーティリティ
func httpGet(urlStr string, headers map[string]string) (interface{}, error) {
	client := &http.Client{Timeout: 15 * time.Second}
	req, err := http.NewRequest("GET", urlStr, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", UserAgent)
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var result interface{}
	err = json.NewDecoder(resp.Body).Decode(&result)
	return result, err
}

func downloadFile(urlStr, dest string, progressCb func(float64)) error {
	client := &http.Client{Timeout: 60 * time.Second}
	req, err := http.NewRequest("GET", urlStr, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", UserAgent)
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	out, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer out.Close()

	total, _ := strconv.ParseFloat(resp.Header.Get("Content-Length"), 64)
	buf := make([]byte, 65536)
	var done float64

	for {
		n, err := resp.Body.Read(buf)
		if n > 0 {
			out.Write(buf[:n])
			done += float64(n)
			if progressCb != nil && total > 0 {
				progressCb(done / total)
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
	}
	return nil
}

func cleanName(raw string) string {
	re1 := regexp.MustCompile(`(?i)[\s_\-\.]+(mc|for|fabric|forge|neoforge|quilt)\d+[\.\d]*$`)
	re2 := regexp.MustCompile(`(?i)[\s_\-\.]+v\d+[\.\d]*[a-zA-Z]*$`)
	re3 := regexp.MustCompile(`(?i)[\s_\-\.]+\d+\.\d+[\.\d]*[a-zA-Z]*$`)
	n := re1.ReplaceAllString(raw, "")
	n = re2.ReplaceAllString(n, "")
	n = re3.ReplaceAllString(n, "")
	n = strings.Trim(n, " _-.")
	if n == "" {
		return raw
	}
	return n
}

func sha1File(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha1.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return fmt.Sprintf("%x", h.Sum(nil)), nil
}

func parseVersion(v string) []int {
	parts := strings.Split(v, ".")
	res := make([]int, 0, len(parts))
	for _, p := range parts {
		if n, err := strconv.Atoi(p); err == nil {
			res = append(res, n)
		} else {
			res = append(res, 0)
		}
	}
	return res
}

func compareVersions(v1, v2 []int) int {
	for i := 0; i < len(v1) && i < len(v2); i++ {
		if v1[i] < v2[i] {
			return -1
		}
		if v1[i] > v2[i] {
			return 1
		}
	}
	if len(v1) < len(v2) {
		return -1
	}
	if len(v1) > len(v2) {
		return 1
	}
	return 0
}

func fetchMCVersions() []string {
	data, err := httpGet(ModrinthAPI+"/tag/game_version", nil)
	if err != nil {
		return MCVersionsFallback
	}
	arr, ok := data.([]interface{})
	if !ok {
		return MCVersionsFallback
	}
	var releases []string
	for _, item := range arr {
		m, ok := item.(map[string]interface{})
		if !ok {
			continue
		}
		vType, _ := m["version_type"].(string)
		ver, _ := m["version"].(string)
		if vType == "release" && strings.Contains(ver, ".") {
			releases = append(releases, ver)
		}
	}
	if len(releases) == 0 {
		return MCVersionsFallback
	}
	sort.Slice(releases, func(i, j int) bool {
		re := regexp.MustCompile(`[.\-]`)
		p1 := re.Split(releases[i], -1)
		p2 := re.Split(releases[j], -1)
		for k := 0; k < len(p1) && k < len(p2); k++ {
			n1, _ := strconv.Atoi(p1[k])
			n2, _ := strconv.Atoi(p2[k])
			if n1 != n2 {
				return n1 > n2
			}
		}
		return len(p1) > len(p2)
	})
	return releases
}

func readJarMeta(jarPath string) ItemInfo {
	info := ItemInfo{
		Filename: filepath.Base(jarPath),
		Path:     jarPath,
		Name:     filepath.Base(jarPath),
		Loader:   "不明",
		Selected: true,
	}
	r, err := zip.OpenReader(jarPath)
	if err != nil {
		return info
	}
	defer r.Close()

	for _, f := range r.File {
		if f.Name == "fabric.mod.json" || f.Name == "quilt.mod.json" {
			rc, err := f.Open()
			if err != nil {
				continue
			}
			var d map[string]interface{}
			json.NewDecoder(rc).Decode(&d)
			rc.Close()
			if d != nil {
				if id, ok := d["id"].(string); ok {
					info.ModID = id
				}
				if name, ok := d["name"].(string); ok {
					info.Name = name
				}
				if ver, ok := d["version"].(string); ok {
					info.Version = ver
				}
				if strings.HasPrefix(f.Name, "quilt") {
					info.Loader = "quilt"
				} else {
					info.Loader = "fabric"
				}
				return info
			}
		}
		if f.Name == "META-INF/mods.toml" || f.Name == "META-INF/neoforge.mods.toml" {
			rc, err := f.Open()
			if err != nil {
				continue
			}
			buf := new(bytes.Buffer)
			buf.ReadFrom(rc)
			rc.Close()
			raw := buf.String()
			if strings.Contains(f.Name, "neoforge") {
				info.Loader = "neoforge"
			} else {
				info.Loader = "forge"
			}
			inMods := false
			lines := strings.Split(raw, "\n")
			for _, line := range lines {
				line = strings.TrimSpace(line)
				if strings.HasPrefix(line, "[[mods]]") {
					inMods = true
				}
				if inMods {
					if strings.HasPrefix(line, "modId") {
						parts := strings.SplitN(line, "=", 2)
						if len(parts) == 2 {
							info.ModID = strings.Trim(strings.TrimSpace(parts[1]), "\"")
						}
					} else if strings.HasPrefix(line, "displayName") {
						parts := strings.SplitN(line, "=", 2)
						if len(parts) == 2 {
							info.Name = strings.Trim(strings.TrimSpace(parts[1]), "\"")
						}
					} else if strings.HasPrefix(line, "version") {
						parts := strings.SplitN(line, "=", 2)
						if len(parts) == 2 {
							v := strings.Trim(strings.TrimSpace(parts[1]), "\"")
							if !strings.HasPrefix(v, "$") {
								info.Version = v
							}
						}
					}
				}
			}
			return info
		}
	}
	return info
}

// Modrinth API 関連関数
func mrFindProject(sha1, modID, name, mrType string) string {
	if sha1 != "" {
		if data, err := httpGet(ModrinthAPI+"/version_file/"+sha1+"?algorithm=sha1", nil); err == nil {
			if m, ok := data.(map[string]interface{}); ok {
				if pid, ok := m["project_id"].(string); ok {
					return pid
				}
			}
		}
	}
	if modID != "" {
		if data, err := httpGet(ModrinthAPI+"/project/"+modID, nil); err == nil {
			if m, ok := data.(map[string]interface{}); ok {
				if pid, ok := m["id"].(string); ok {
					return pid
				}
			}
		}
	}
	vals := url.Values{}
	vals.Set("query", name)
	vals.Set("limit", "5")
	facets := fmt.Sprintf("[[\"project_type:%s\"]]", mrType)
	vals.Set("facets", facets)
	if data, err := httpGet(ModrinthAPI+"/search?"+vals.Encode(), nil); err == nil {
		if m, ok := data.(map[string]interface{}); ok {
			if hits, ok := m["hits"].([]interface{}); ok && len(hits) > 0 {
				for _, h := range hits {
					if hm, ok := h.(map[string]interface{}); ok {
						if title, _ := hm["title"].(string); strings.ToLower(title) == strings.ToLower(name) {
							if pid, ok := hm["project_id"].(string); ok {
								return pid
							}
						}
					}
				}
				if hm, ok := hits[0].(map[string]interface{}); ok {
					if pid, ok := hm["project_id"].(string); ok {
						return pid
					}
				}
			}
		}
	}
	return ""
}

func mrGetVersions(pid, mcVer, loader, mrType string) []interface{} {
	vals := url.Values{}
	vals.Set("game_versions", fmt.Sprintf("[\"%s\"]", mcVer))
	if mrType == MrMod {
		vals.Set("loaders", fmt.Sprintf("[\"%s\"]", loader))
	}
	if data, err := httpGet(ModrinthAPI+"/project/"+pid+"/version?"+vals.Encode(), nil); err == nil {
		if arr, ok := data.([]interface{}); ok {
			return arr
		}
	}
	return nil
}

func mrGetDeps(versionObj map[string]interface{}) [][]string {
	var deps [][]string
	if dList, ok := versionObj["dependencies"].([]interface{}); ok {
		for _, dItem := range dList {
			if dm, ok := dItem.(map[string]interface{}); ok {
				dType, _ := dm["dependency_type"].(string)
				pID, _ := dm["project_id"].(string)
				vID, _ := dm["version_id"].(string)
				if dType == "required" && pID != "" {
					deps = append(deps, []string{pID, vID})
				}
			}
		}
	}
	return deps
}

func mrBestFile(versionObj map[string]interface{}) (string, string) {
	if files, ok := versionObj["files"].([]interface{}); ok {
		var backupUrl, backupName string
		for _, fItem := range files {
			if fm, ok := fItem.(map[string]interface{}); ok {
				u, _ := fm["url"].(string)
				fn, _ := fm["filename"].(string)
				primary, _ := fm["primary"].(bool)
				if primary {
					return u, fn
				}
				if backupUrl == "" {
					backupUrl, backupName = u, fn
				}
			}
		}
		return backupUrl, backupName
	}
	return "", ""
}

// CurseForge API 関連関数
func cfReq(urlStr, apiKey string) (interface{}, error) {
	return httpGet(urlStr, map[string]string{
		"x-api-key": apiKey,
		"Accept":    "application/json",
	})
}

func cfSearch(name, apiKey string, classID int) int {
	vals := url.Values{}
	vals.Set("gameId", strconv.Itoa(CfGame))
	vals.Set("classId", strconv.Itoa(classID))
	vals.Set("searchFilter", name)
	vals.Set("pageSize", "5")
	vals.Set("sortField", "2")
	vals.Set("sortOrder", "desc")
	if data, err := cfReq(CurseForgeAPI+"/mods/search?"+vals.Encode(), apiKey); err == nil {
		if m, ok := data.(map[string]interface{}); ok {
			if dList, ok := m["data"].([]interface{}); ok && len(dList) > 0 {
				for _, dItem := range dList {
					if dm, ok := dItem.(map[string]interface{}); ok {
						dName, _ := dm["name"].(string)
						if strings.ToLower(dName) == strings.ToLower(name) {
							if id, ok := dm["id"].(float64); ok {
								return int(id)
							}
						}
					}
				}
				if dm, ok := dList[0].(map[string]interface{}); ok {
					if id, ok := dm["id"].(float64); ok {
						return int(id)
					}
				}
			}
		}
	}
	return 0
}

func cfGetFile(cfID int, mcVer, loader, apiKey string, mrType string) map[string]interface{} {
	loaderID := 0
	if mrType == MrMod {
		loaderID = CfLoader[loader]
	}
	vals := url.Values{}
	vals.Set("gameVersion", mcVer)
	vals.Set("modLoaderType", strconv.Itoa(loaderID))
	vals.Set("pageSize", "10")
	if data, err := cfReq(fmt.Sprintf("%s/mods/%d/files?%s", CurseForgeAPI, cfID, vals.Encode()), apiKey); err == nil {
		if m, ok := data.(map[string]interface{}); ok {
			if dList, ok := m["data"].([]interface{}); ok && len(dList) > 0 {
				var files []map[string]interface{}
				for _, dItem := range dList {
					if dm, ok := dItem.(map[string]interface{}); ok {
						files = append(files, dm)
					}
				}
				sort.Slice(files, func(i, j int) bool {
					r1, _ := files[i]["releaseType"].(float64)
					r2, _ := files[j]["releaseType"].(float64)
					if r1 != r2 {
						return r1 < r2
					}
					id1, _ := files[i]["id"].(float64)
					id2, _ := files[j]["id"].(float64)
					return id1 > id2
				})
				return files[0]
			}
		}
	}
	return nil
}

// 統合検索
func findDlInfo(name, modID, path, mcVer, loader, mode, cfKey, mrType string, cfClass int, logCb func(string, string)) (string, string, string, map[string]interface{}) {
	doMr := mode == DlBoth || mode == DlCfFirst || mode == DlMr
	doCf := mode == DlBoth || mode == DlCfFirst || mode == DlCf

	var dlUrl, dlFname, source string
	var versionObj map[string]interface{}

	tryMr := func() {
		sha1, _ := sha1File(path)
		pid := mrFindProject(sha1, modID, name, mrType)
		if pid == "" {
			logCb("  Modrinth: 見つからず", "warn")
			return
		}
		vs := mrGetVersions(pid, mcVer, loader, mrType)
		if len(vs) == 0 {
			logCb(fmt.Sprintf("  Modrinth: %s 対応なし", mcVer), "warn")
			return
		}
		if m, ok := vs[0].(map[string]interface{}); ok {
			versionObj = m
			dlUrl, dlFname = mrBestFile(m)
			source = "Modrinth"
			logCb(fmt.Sprintf("  ✓ Modrinth: %s", dlFname), "ok")
		}
	}

	tryCf := func() {
		cfID := cfSearch(name, cfKey, cfClass)
		if cfID == 0 {
			logCb("  CurseForge: 見つからず", "warn")
			return
		}
		fi := cfGetFile(cfID, mcVer, loader, cfKey, mrType)
		if fi == nil {
			logCb(fmt.Sprintf("  CurseForge: %s 対応なし", mcVer), "warn")
			return
		}
		dlUrl, _ = fi["downloadUrl"].(string)
		dlFname, _ = fi["fileName"].(string)
		source = "CurseForge"
		logCb(fmt.Sprintf("  ✓ CurseForge: %s", dlFname), "ok")
	}

	if mode == DlCfFirst {
		if doCf { tryCf() }
		if doMr && dlUrl == "" { tryMr() }
	} else {
		if doMr { tryMr() }
		if doCf && dlUrl == "" { tryCf() }
	}

	return dlUrl, dlFname, source, versionObj
}

// UI パネル定義
type FileListPanel struct {
	Container *fyne.Container
	List      *widget.List
	Items     []ItemInfo
	Mu        sync.Mutex
	Label     *widget.Label
	MrType    string
}

func NewFileListPanel(mrType string, loadFn, updateFn func()) *FileListPanel {
	p := &FileListPanel{MrType: mrType}
	p.Label = widget.NewLabel("0 / 0 件選択")

	selAllBtn := widget.NewButton("全選択", func() { p.setAll(true) })
	selNoneBtn := widget.NewButton("全解除", func() { p.setAll(false) })
	loadBtn := widget.NewButton("📂 読込", loadFn)
	updBtn := widget.NewButton("⬇ 更新", updateFn)

	topBar := container.NewHBox(selAllBtn, selNoneBtn, widget.NewSeparator(), loadBtn, updBtn, container.NewGridWrap(fyne.NewSize(100, 36), p.Label))

	p.List = widget.NewList(
		func() int { return len(p.Items) },
		func() fyne.CanvasObject {
			chk := widget.NewCheck("", nil)
			lbl := widget.NewLabel("")
			return container.NewHBox(chk, lbl)
		},
		func(id widget.ListItemID, o fyne.CanvasObject) {
			p.Mu.Lock()
			defer p.Mu.Unlock()
			if id >= len(p.Items) { return }
			item := p.Items[id]
			box := o.(*fyne.Container)
			chk := box.Objects[0].(*widget.Check)
            lbl := box.Objects[1].(*widget.Label)

			chk.Checked = item.Selected
			chk.OnChanged = func(b bool) {
				p.Mu.Lock()
				p.Items[id].Selected = b
				p.Mu.Unlock()
				p.updateLabel()
			}
			display := item.DisplayName
			if display == "" {
				display = item.Name
			}
			if mrType == MrMod {
				lbl.SetText(fmt.Sprintf("%s [%s] (%s)", display, item.Version, item.Loader))
			} else {
				lbl.SetText(display)
			}
		},
	)

	p.Container = container.NewBorder(topBar, nil, nil, nil, p.List)
	return p
}

func (p *FileListPanel) populate(items []ItemInfo) {
	p.Mu.Lock()
	p.Items = items
	p.Mu.Unlock()
	p.List.Refresh()
	p.updateLabel()
}

func (p *FileListPanel) addItem(item ItemInfo) {
	p.Mu.Lock()
	for _, it := range p.Items {
		if it.Filename == item.Filename {
			p.Mu.Unlock()
			return
		}
	}
	p.Items = append(p.Items, item)
	p.Mu.Unlock()
	p.List.Refresh()
	p.updateLabel()
}

func (p *FileListPanel) getSelected() []ItemInfo {
	p.Mu.Lock()
	defer p.Mu.Unlock()
	var res []ItemInfo
	for _, it := range p.Items {
		if it.Selected {
			res = append(res, it)
		}
	}
	return res
}

func (p *FileListPanel) setAll(b bool) {
	p.Mu.Lock()
	for i := range p.Items {
		p.Items[i].Selected = b
	}
	p.Mu.Unlock()
	p.List.Refresh()
	p.updateLabel()
}

func (p *FileListPanel) updateLabel() {
	p.Mu.Lock()
	defer p.Mu.Unlock()
	sel := 0
	for _, it := range p.Items {
		if it.Selected {
			sel++
		}
	}
	p.Label.SetText(fmt.Sprintf("%d / %d 件選択", sel, len(p.Items)))
}

// 構築メイン
func main() {
	a := app.NewWithID("com.mcpackupdater.app")
	w := a.NewWindow("⛏ MC Pack Updater")
	w.Resize(fyne.NewSize(1150, 780))

	state := &AppState{
		ConfigFile: getConfigFile(),
		MainWindow: w,
		LogBoxes:   make(map[string]*widget.Entry),
	}
	state.Config = loadConfig(state.ConfigFile)

	if state.Config.Theme == "dark" {
		a.Settings().SetTheme(theme.DarkTheme())
	} else {
		a.Settings().SetTheme(theme.LightTheme())
	}

	state.buildUI()
	w.SetOnClosed(state.saveConfig)

	go state.fetchVersionsBg()

	w.ShowAndRun()
}

func (s *AppState) buildUI() {
	// 進行状況バー
	s.Progress = widget.NewProgressBar()
	s.ProgLabel = widget.NewLabel("")
	s.CancelBtn = widget.NewButton("⏹ 中止", s.cancelAction)
	s.CancelBtn.Disable()
	bottomBar := container.NewBorder(nil, nil, nil, s.CancelBtn, container.NewBorder(nil, nil, nil, s.ProgLabel, s.Progress))

	tabs := container.NewAppTabs()

	// 1. 設定タブ
	settingsView := s.buildSettingsTab()
	tabs.Append(container.NewTabItem(" ⚙ 設定 ", settingsView))

	// 2. 一覧タブ
	s.ModPanel = NewFileListPanel(MrMod, s.loadMods, func() { s.startPanel(s.ModPanel, "Mod") })
	s.RpPanel = NewFileListPanel(MrRp, s.loadRp, func() { s.startPanel(s.RpPanel, "ResourcePack") })
	s.ShaderPanel = NewFileListPanel(MrShade, s.loadShader, func() { s.startPanel(s.ShaderPanel, "Shader") })

	listsView := container.NewGridWithColumns(3,
		container.NewBorder(widget.NewLabel("🧩 Mod"), nil, nil, nil, s.ModPanel.Container),
		container.NewBorder(widget.NewLabel("🎨 ResourcePack"), nil, nil, nil, s.RpPanel.Container),
		container.NewBorder(widget.NewLabel("✨ Shader"), nil, nil, nil, s.ShaderPanel.Container),
	)
	tabs.Append(container.NewTabItem(" 📦 一覧 ", listsView))

	// 3. ログタブ
	logKeys := []string{"sys", "mod", "rp", "shader"}
	logNames := []string{"🖥 システム", "🧩 Mod", "🎨 ResourcePack", "✨ Shader"}
	logGrid := container.NewGridWithRows(2)
	
	sysEntry := widget.NewMultiLineEntry()
	s.LogBoxes["sys"] = sysEntry
	sysClear := widget.NewButton("クリア", func() { sysEntry.SetText("") })
	logGrid.Add(container.NewBorder(container.NewHBox(widget.NewLabel("🖥 システム"), sysClear), nil, nil, nil, sysEntry))

	subLogGrid := container.NewGridWithColumns(3)
	for i := 1; i < 4; i++ {
		key := logKeys[i]
		ent := widget.NewMultiLineEntry()
		s.LogBoxes[key] = ent
		clearBtn := widget.NewButton("クリア", func() { ent.SetText("") })
		subLogGrid.Add(container.NewBorder(container.NewHBox(widget.NewLabel(logNames[i]), clearBtn), nil, nil, nil, ent))
	}
	logGrid.Add(subLogGrid)
	tabs.Append(container.NewTabItem(" 📋 ログ ", logGrid))

	themeBtn := widget.NewButtonWithIcon("", theme.ColorPaletteIcon(), s.toggleTheme)
	header := container.NewBorder(nil, nil, nil, themeBtn, widget.NewLabelWithStyle("⛏  MC Pack Updater", fyne.TextAlignCenter, fyne.TextStyle{Bold: true}))

	mainContent := container.NewBorder(header, bottomBar, nil, nil, tabs)
	s.MainWindow.SetContent(mainContent)
}

func (s *AppState) buildSettingsTab() fyne.CanvasObject {
	// 各種テキスト入力初期化
	profEntry := widget.NewEntry()
	profEntry.Bind(binding.BindString(&s.Config.ProfileDir))
	modsEntry := widget.NewEntry()
	modsEntry.Bind(binding.BindString(&s.Config.ModsDir))
	rpEntry := widget.NewEntry()
	rpEntry.Bind(binding.BindString(&s.Config.RpDir))
	shadeEntry := widget.NewEntry()
	shadeEntry.Bind(binding.BindString(&s.Config.ShaderDir))

	// フォルダ指定欄
	profRow := container.NewBorder(nil, nil, widget.NewLabel("🚀 起動構成フォルダ:"), container.NewHBox(
		widget.NewButton("参照", func() { s.browseDir(&s.Config.ProfileDir, profEntry) }),
		widget.NewButton("📂 読み込む", s.loadFromProfile),
		widget.NewButton("✕", func() { s.Config.ProfileDir = ""; profEntry.SetText("") }),
	), profEntry)

	modsRow := container.NewBorder(nil, nil, widget.NewLabel("🧩 Mods:"), container.NewHBox(
		widget.NewButton("参照", func() { s.browseDir(&s.Config.ModsDir, modsEntry) }),
		widget.NewButton("✕", func() { s.Config.ModsDir = ""; modsEntry.SetText("") }),
	), modsEntry)

	rpRow := container.NewBorder(nil, nil, widget.NewLabel("🎨 ResourcePacks:"), container.NewHBox(
		widget.NewButton("参照", func() { s.browseDir(&s.Config.RpDir, rpEntry) }),
		widget.NewButton("✕", func() { s.Config.RpDir = ""; rpEntry.SetText("") }),
	), rpEntry)

	shadeRow := container.NewBorder(nil, nil, widget.NewLabel("✨ Shaders:"), container.NewHBox(
		widget.NewButton("参照", func() { s.browseDir(&s.Config.ShaderDir, shadeEntry) }),
		widget.NewButton("✕", func() { s.Config.ShaderDir = ""; shadeEntry.SetText("") }),
	), shadeEntry)

	folderSection := container.NewVBox(
		widget.NewLabelWithStyle("📁 フォルダ設定", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		profRow, modsRow, rpRow, shadeRow,
	)

	// アップデート先設定
	s.VerSelect = widget.NewSelect(MCVersionsFallback, func(v string) { s.Config.TargetVersion = v })
	s.VerSelect.SetSelected(s.Config.TargetVersion)
	s.VerStatus = widget.NewLabel("🔄 取得中...")

	s.LoadSelect = widget.NewSelect(Loaders, func(l string) {
		s.Config.TargetLoader = l
		s.filterVersions()
	})
	s.LoadSelect.SetSelected(s.Config.TargetLoader)

	resetVerBtn := widget.NewButton("✕ リセット", func() {
		s.VerSelect.ClearSelected()
		s.LoadSelect.ClearSelected()
	})

	targetSection := container.NewVBox(
		widget.NewLabelWithStyle("🎯 アップデート先ターゲット", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		container.NewHBox(
			widget.NewLabel("MCバージョン:"), s.VerSelect, s.VerStatus,
			widget.NewLabel("Mod Loader:"), s.LoadSelect, resetVerBtn,
		),
	)

	// DL設定
	s.CfKeyEntry = widget.NewPasswordEntry()
	s.CfKeyEntry.Bind(binding.BindString(&s.Config.CfApiKey)) // 👈 BindString に変更

	modeDesc := widget.NewLabel("")
	s.DlModeSelect = widget.NewSelect(DlModes, func(m string) {
		s.Config.DlMode = m
		switch m {
		case DlBoth:
			modeDesc.SetText("ℹ Modrinthで検索 → なければCurseForgeも")
			s.CfKeyEntry.Enable()
		case DlCfFirst:
			modeDesc.SetText("ℹ CurseForgeで検索 → なければModrinthも（APIキー必須）")
			s.CfKeyEntry.Enable()
		case DlMr:
			modeDesc.SetText("ℹ Modrinthのみ（APIキー不要）")
			s.CfKeyEntry.Disable()
		case DlCf:
			modeDesc.SetText("ℹ CurseForgeのみ（APIキー必須）")
			s.CfKeyEntry.Enable()
		}
	})
	s.DlModeSelect.SetSelected(s.Config.DlMode)

	showCfBtn := widget.NewButton("表示", func() {
		// パスワード表示切り替えの簡易エミュレート
		if s.CfKeyEntry.Password {
			s.CfKeyEntry.Password = false
		} else {
			s.CfKeyEntry.Password = true
		}
		s.CfKeyEntry.Refresh()
	})

	guideBtn := widget.NewButton("取得方法 ↗", s.showApiGuide)

	dlSection := container.NewVBox(
		widget.NewLabelWithStyle("🌐 ダウンロード構成設定", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		container.NewHBox(widget.NewLabel("モード:"), s.DlModeSelect),
		modeDesc,
		container.NewBorder(nil, nil, widget.NewLabel("CurseForge APIキー:"), container.NewHBox(showCfBtn, guideBtn), s.CfKeyEntry),
	)

	// オプション設定
	delOldChk := widget.NewCheck("アップデート後に古いファイルを削除する", func(b bool) { s.Config.DeleteOld = b })
	delOldChk.Checked = s.Config.DeleteOld
	delFailChk := widget.NewCheck("ダウンロード失敗したファイルを削除する（壊れたファイル除去）", func(b bool) { s.Config.DeleteFailed = b })
	delFailChk.Checked = s.Config.DeleteFailed
	autoDepsChk := widget.NewCheck("前提Modが足りなければ自動でダウンロードする", func(b bool) { s.Config.AutoDeps = b })
	autoDepsChk.Checked = s.Config.AutoDeps
	strictDepsChk := widget.NewCheck("前提Modのバージョンを厳密に指定する（不安定な場合はOFF）", func(b bool) { s.Config.StrictDeps = b })
	strictDepsChk.Checked = s.Config.StrictDeps

	optionsSection := container.NewVBox(
		widget.NewLabelWithStyle("⚙ オプション設定", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		delOldChk, delFailChk, autoDepsChk, strictDepsChk,
	)

	// 一括操作ボタン
	actionSection := container.NewVBox(
		widget.NewLabelWithStyle("▶ アクション実行", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		container.NewHBox(
			widget.NewButton("📂 全て読み込む", func() { s.loadMods(); s.loadRp(); s.loadShader() }),
			widget.NewButton("🔄 全て一括アップデート", s.startAll),
		),
	)

	return container.NewScroll(container.NewVBox(
		folderSection, widget.NewSeparator(),
		targetSection, widget.NewSeparator(),
		dlSection, widget.NewSeparator(),
		optionsSection, widget.NewSeparator(),
		actionSection,
	))
}

func (s *AppState) logMsg(msg, key string) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	box, ok := s.LogBoxes[key]
	if !ok {
		box = s.LogBoxes["mod"]
	}
	box.SetText(box.Text + msg + "\n")
}

func (s *AppState) toggleTheme() {
	if s.Config.Theme == "light" {
		s.Config.Theme = "dark"
		fyne.CurrentApp().Settings().SetTheme(theme.DarkTheme())
	} else {
		s.Config.Theme = "light"
		fyne.CurrentApp().Settings().SetTheme(theme.LightTheme())
	}
}

func (s *AppState) browseDir(target *string, entry *widget.Entry) {
	d := dialog.NewFolderOpen(func(uri fyne.ListableURI, err error) {
		if err == nil && uri != nil {
			*target = uri.Path()
			entry.SetText(uri.Path())
		}
	}, s.MainWindow)
	d.Show()
}

func (s *AppState) validateCf() bool {
	m := s.Config.DlMode
	if (m == DlBoth || m == DlCfFirst || m == DlCf) && strings.TrimSpace(s.Config.CfApiKey) == "" {
		dialog.ShowError(fmt.Errorf("CurseForgeを使用するにはAPIキーが必要です"), s.MainWindow)
		return false
	}
	return true
}

func (s *AppState) cancelAction() {
	s.CancelFlag = true
	s.ProgLabel.SetText("中止中...")
	s.CancelBtn.Disable()
}

func (s *AppState) filterVersions() {
	minVer, ok := LoaderMin[s.Config.TargetLoader]
	if !ok || len(s.VerSelect.Options) == 0 {
		return
	}
	var filtered []string
	for _, v := range s.VerSelect.Options {
		if compareVersions(parseVersion(v), minVer) >= 0 {
			filtered = append(filtered, v)
		}
	}
	// 選択可能なリストを絞り込みに更新
	if len(filtered) > 0 {
		s.VerSelect.Options = filtered
		found := false
		for _, f := range filtered {
			if f == s.Config.TargetVersion {
				found = true
				break
			}
		}
		if !found {
			s.VerSelect.SetSelected(filtered[0])
		}
	}
}

func (s *AppState) fetchVersionsBg() {
	versions := fetchMCVersions()
	s.VerSelect.Options = versions
	s.VerSelect.Refresh()

	if len(versions) > 0 {
		s.VerSelect.SetSelected(versions[0])
		s.VerStatus.SetText(fmt.Sprintf("✅ %d 件", len(versions)))
		s.logMsg(fmt.Sprintf("✅ MCバージョン %d 件取得完了", len(versions)), "sys")
	} else {
		s.VerStatus.SetText("⚠ オフライン")
		s.logMsg("⚠ バージョン取得失敗 → フォールバックを使用します", "sys")
	}
	s.filterVersions()
}

func (s *AppState) showApiGuide() {
	// PDF読み込み＆案内表示ウィンドウの構築
	home, _ := os.UserHomeDir()
	pdfPath := filepath.Join(home, "API Key Guide.pdf")
	
	doc, err := fitz.New(pdfPath)
	if err != nil {
		s.logMsg("PDFガイドが見つかりません。コンソールを開きます。", "sys")
		fyne.CurrentApp().OpenURL(&url.URL{Scheme: "https", Host: "console.curseforge.com"})
		return
	}
	defer doc.Close()

	win := fyne.CurrentApp().NewWindow("API Key 取得方法")
	win.Resize(fyne.NewSize(600, 500))

	imgContainer := container.NewVBox()
	for i := 0; i < doc.NumPage(); i++ {
		img, err := doc.Image(i)
		if err == nil {
			// 本来はfyneの画像オブジェクトに変換して追加
			_ = img 
		}
	}
	
	win.SetContent(container.NewScroll(imgContainer))
	win.Show()
}

// 解析読込処理
func (s *AppState) loadDir(dirPath, ext string, panel *FileListPanel, kindLabel string) bool {
	if dirPath == "" {
		dialog.ShowError(fmt.Errorf("有効な %s フォルダを指定してください", kindLabel), s.MainWindow)
		return false
	}
	files, err := os.ReadDir(dirPath)
	if err != nil {
		dialog.ShowError(err, s.MainWindow)
		return false
	}

	s.logMsg(fmt.Sprintf("📂 %s: 解析中...", kindLabel), "sys")
	var items []ItemInfo
	for _, f := range files {
		if !f.IsDir() && strings.HasSuffix(strings.ToLower(f.Name()), ext) {
			path := filepath.Join(dirPath, f.Name())
			var info ItemInfo
			if ext == ".jar" {
				info = readJarMeta(path)
			} else {
				raw := strings.TrimSuffix(f.Name(), ext)
				info = ItemInfo{
					Filename:    f.Name(),
					Path:        path,
					Name:        cleanName(raw),
					DisplayName: raw,
					Selected:    true,
				}
			}
			items = append(items, info)
		}
	}

	sort.Slice(items, func(i, j int) bool {
		return strings.ToLower(items[i].Name) < strings.ToLower(items[j].Name)
	})

	panel.populate(items)
	s.logMsg(fmt.Sprintf("✅ %s: %d 件読込完了", kindLabel, len(items)), "sys")
	return true
}

func (s *AppState) loadMods()   { s.loadDir(s.Config.ModsDir, ".jar", s.ModPanel, "Mod") }
func (s *AppState) loadRp()     { s.loadDir(s.Config.RpDir, ".zip", s.RpPanel, "ResourcePack") }
func (s *AppState) loadShader() { s.loadDir(s.Config.ShaderDir, ".zip", s.ShaderPanel, "Shader") }

func (s *AppState) loadFromProfile() {
	base := s.Config.ProfileDir
	if base == "" {
		dialog.ShowError(fmt.Errorf("有効な起動構成フォルダを指定してください"), s.MainWindow)
		return
	}
	mapping := map[string]*string{"mods": &s.Config.ModsDir, "resourcepacks": &s.Config.RpDir, "shaderpacks": &s.Config.ShaderDir}
	var found []string
	for sub, ptr := range mapping {
		path := filepath.Join(base, sub)
		if fi, err := os.Stat(path); err == nil && fi.IsDir() {
			*ptr = path
			found = append(found, sub)
		}
	}
	if len(found) == 0 {
		dialog.ShowInformation("確認", "対象フォルダが見つかりませんでした", s.MainWindow)
		return
	}
	s.logMsg(fmt.Sprintf("🚀 起動構成検出: %s", base), "sys")
	s.loadMods()
	s.loadRp()
	s.loadShader()
}

// アップデートタスクの組み立てと実行
func (s *AppState) buildTasks(panel *FileListPanel) []Task {
	var outDir string
	var cfClass int
	switch panel.MrType {
	case MrMod:
		outDir = s.Config.ModsDir
		cfClass = CfMod
	case MrRp:
		outDir = s.Config.RpDir
		cfClass = CfRp
	case MrShade:
		outDir = s.Config.ShaderDir
		cfClass = CfShade
	}
	var tasks []Task
	for _, it := range panel.getSelected() {
		tasks = append(tasks, Task{Item: it, OutDir: outDir, MrType: panel.MrType, CfClass: cfClass})
	}
	return tasks
}

func (s *AppState) startPanel(panel *FileListPanel, label string) {
	if !s.validateCf() { return }
	tasks := s.buildTasks(panel)
	if len(tasks) == 0 {
		dialog.ShowInformation("情報", "アイテムが選択されていません", s.MainWindow)
		return
	}
	s.runTasks(tasks)
}

func (s *AppState) startAll() {
	if !s.validateCf() { return }
	tasks := append(s.buildTasks(s.ModPanel), s.buildTasks(s.RpPanel)...)
	tasks = append(tasks, s.buildTasks(s.ShaderPanel)...)
	if len(tasks) == 0 {
		dialog.ShowInformation("情報", "アイテムが選択されていません", s.MainWindow)
		return
	}
	s.runTasks(tasks)
}

func (s *AppState) runTasks(tasks []Task) {
	s.Mu.Lock()
	if s.Running {
		s.Mu.Unlock()
		dialog.ShowError(fmt.Errorf("現在アップデート処理の実行中です"), s.MainWindow)
		return
	}
	s.Running = true
	s.CancelFlag = false
	s.Mu.Unlock()

	s.Progress.Max = float64(len(tasks))
	s.Progress.SetValue(0)
	s.CancelBtn.Enable()

	go s.workerProcess(tasks)
}

func (s *AppState) workerProcess(tasks []Task) {
	doneDeps := make(map[string]bool)
	results := map[string]map[string][]string{
		"mod":    {"ok": {}, "fail": {}},
		"rp":     {"ok": {}, "fail": {}},
		"shader": {"ok": {}, "fail": {}},
	}

	for i, t := range tasks {
		if s.CancelFlag {
			s.logMsg("\n⏹ ユーザーにより処理が中止されました", "mod")
			break
		}
		name := t.Item.Name
		if name == "" {
			name = t.Item.Filename
		}
		key := "mod"
		if t.MrType == MrRp { key = "rp" }
		if t.MrType == MrShade { key = "shader" }

		s.ProgLabel.SetText(fmt.Sprintf("%d/%d: %s", i+1, len(tasks), name))
		s.logMsg(fmt.Sprintf("\n── %s ──", name), key)

		logCb := func(m, tag string) { s.logMsg(m, key) }

		dlUrl, dlFname, source, versionObj := findDlInfo(
			name, t.Item.ModID, t.Item.Path,
			s.Config.TargetVersion, s.Config.TargetLoader, s.Config.DlMode,
			s.Config.CfApiKey, t.MrType, t.CfClass, logCb,
		)

		if dlUrl != "" && dlFname != "" {
			dest := filepath.Join(t.OutDir, dlFname)
			doDelOld := s.Config.DeleteOld && t.MrType == MrMod
			doDelFail := s.Config.DeleteFailed && t.MrType == MrMod

			success := s.doDownload(dlUrl, dest, name, source, t.Item.Path, doDelOld, doDelFail, key)
			if success {
				results[key]["ok"] = append(results[key]["ok"], name)

				// 依存関係（Modrinth優先自動解決）
				if t.MrType == MrMod && s.Config.AutoDeps && versionObj != nil {
					for _, dep := range mrGetDeps(versionObj) {
						depPid := dep[0]
						depVid := dep[1]
						if doneDeps[depPid] { continue }
						doneDeps[depPid] = true

						s.logMsg(fmt.Sprintf("  🔗 依存Mod検出 ID: %s", depPid), key)
						var du, df string
						if s.Config.StrictDeps && depVid != "" {
							if vData, err := httpGet(ModrinthAPI+"/version/"+depVid, nil); err == nil {
								if vm, ok := vData.(map[string]interface{}); ok {
									du, df = mrBestFile(vm)
								}
							}
						} else {
							vs := mrGetVersions(depPid, s.Config.TargetVersion, s.Config.TargetLoader, MrMod)
							if len(vs) > 0 {
								if vm, ok := vs[0].(map[string]interface{}); ok {
									du, df = mrBestFile(vm)
								}
							}
						}

						if du != "" && df != "" {
							ddest := filepath.Join(t.OutDir, df)
							if _, err := os.Stat(ddest); err == nil {
								s.logMsg(fmt.Sprintf("  🔗 依存ファイル既存: %s", df), key)
							} else {
								s.doDownload(du, ddest, df, "Modrinth", "", false, doDelFail, key)
								s.ModPanel.addItem(ItemInfo{Filename: df, Path: ddest, Name: df, Selected: true})
								results[key]["ok"] = append(results[key]["ok"], "[依存] "+df)
							}
						}
					}
				}
			} else {
				results[key]["fail"] = append(results[key]["fail"], name)
			}
		} else {
			results[key]["fail"] = append(results[key]["fail"], name)
			s.logMsg("  ❌ スキップ（対応バージョンなし）", key)
			if s.Config.DeleteFailed && t.MrType == MrMod && t.Item.Path != "" {
				os.Remove(t.Item.Path)
				s.logMsg(fmt.Sprintf("  🗑 失敗ファイルを削除しました: %s", t.Item.Filename), key)
			}
		}
		s.Progress.SetValue(float64(i + 1))
	}

	// 処理完了サマリーログ
	totalOk := 0
	totalFail := 0
	for _, k := range []string{"mod", "rp", "shader"} {
		totalOk += len(results[k]["ok"])
		totalFail += len(results[k]["fail"])
	}

	s.ProgLabel.SetText("完了")
	s.Mu.Lock()
	s.Running = false
	s.Mu.Unlock()
	s.CancelBtn.Disable()

	msg := fmt.Sprintf("✅ 成功: %d 件\n❌ 失敗: %d 件", totalOk, totalFail)
	dialog.ShowInformation("完了", msg, s.MainWindow)
}

func (s *AppState) doDownload(urlStr, dest, name, source, oldPath string, delOld, delFail bool, logKey string) bool {
	s.logMsg(fmt.Sprintf("  ⬇ DL開始 [%s]: %s", source, filepath.Base(dest)), logKey)
	err := downloadFile(urlStr, dest, func(p float64) {
		s.ProgLabel.SetText(fmt.Sprintf("DL: %s (%.0f%%)", name, p*100))
	})
	if err == nil {
		if delOld && oldPath != "" && dest != oldPath {
			os.Remove(oldPath)
			s.logMsg(fmt.Sprintf("  🗑 旧ファイルを削除: %s", filepath.Base(oldPath)), logKey)
		}
		s.logMsg("  ✅ 完了", logKey)
		return true
	}

	s.logMsg(fmt.Sprintf("  ❌ DL失敗: %v", err), logKey)
	os.Remove(dest)
	if delFail && oldPath != "" {
		os.Remove(oldPath)
		s.logMsg(fmt.Sprintf("  🗑 不完全なファイルをクリーンアップ: %s", filepath.Base(oldPath)), logKey)
	}
	return false
}
