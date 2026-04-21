import AppKit
import Foundation

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let label = "com.voicedictate.daemon"
    let logPath = ("~/Library/Logs/voice_dictate.log" as NSString).expandingTildeInPath
    let plistPath = ("~/Library/LaunchAgents/com.voicedictate.daemon.plist" as NSString).expandingTildeInPath
    let configDir = ("~/Library/Application Support/voice-dictate" as NSString).expandingTildeInPath
    var configPath: String { configDir + "/config.json" }
    var presetsPath: String { configDir + "/presets.json" }

    var statusItem: NSStatusItem!
    var tailTask: Process?
    var modelSubmenuDelegate: ModelSubmenuDelegate?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        setIdleIcon()

        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu

        startLogTail()
    }

    // MARK: - Icon

    func setIdleIcon() {
        let img = NSImage(systemSymbolName: "mic", accessibilityDescription: "VoiceDictate")
        img?.isTemplate = true
        statusItem.button?.image = img
    }

    func setRecordingIcon() {
        let img = NSImage(systemSymbolName: "mic.fill", accessibilityDescription: "VoiceDictate recording")
        img?.isTemplate = false
        let tinted = img?.tinted(with: .systemRed)
        statusItem.button?.image = tinted ?? img
    }

    // MARK: - Menu

    func menuNeedsUpdate(_ menu: NSMenu) {
        if menu == statusItem.menu {
            rebuildMainMenu(menu)
        }
    }

    func rebuildMainMenu(_ menu: NSMenu) {
        menu.removeAllItems()

        let statusLabel = NSMenuItem(title: daemonStatus(), action: nil, keyEquivalent: "")
        statusLabel.isEnabled = false
        menu.addItem(statusLabel)
        menu.addItem(.separator())

        let cfg = loadConfig()
        let presets = loadPresets()
        let activeId = cfg["active_preset"] as? String ?? ""
        let activePreset = presets.first { ($0["id"] as? String) == activeId }
        let currentModel = cfg["current_model"] as? String

        let ppOn = (cfg["postprocess"] as? Bool) == true
        let toggle = NSMenuItem(title: "Post-processing", action: #selector(togglePostprocess), keyEquivalent: "")
        toggle.target = self
        toggle.state = ppOn ? .on : .off
        menu.addItem(toggle)

        let presetTitle: String
        if let name = activePreset?["name"] as? String {
            presetTitle = "Preset: \(name)"
        } else {
            presetTitle = "Preset: (none)"
        }
        let presetItem = NSMenuItem(title: presetTitle, action: nil, keyEquivalent: "")
        presetItem.submenu = buildPresetSubmenu(presets: presets, activeId: activeId)
        menu.addItem(presetItem)

        let modelTitle: String
        if let m = currentModel, !m.isEmpty {
            modelTitle = "Model: \(m)"
        } else {
            modelTitle = "Model: (none)"
        }
        let modelItem = NSMenuItem(title: modelTitle, action: nil, keyEquivalent: "")
        let modelSubmenu = NSMenu()
        modelSubmenuDelegate = ModelSubmenuDelegate(
            activePreset: activePreset,
            currentModel: currentModel,
            selectionTarget: self,
            selectionAction: #selector(selectModel(_:))
        )
        modelSubmenu.delegate = modelSubmenuDelegate
        modelItem.submenu = modelSubmenu
        menu.addItem(modelItem)

        menu.addItem(item(title: "Edit Presets…", sel: #selector(editPresets), key: ""))

        menu.addItem(.separator())
        menu.addItem(item(title: "Pause",   sel: #selector(pause),   key: "p"))
        menu.addItem(item(title: "Resume",  sel: #selector(resume),  key: "r"))
        menu.addItem(item(title: "Restart", sel: #selector(restart), key: "k"))
        menu.addItem(.separator())
        menu.addItem(item(title: "Show Log", sel: #selector(showLog), key: "l"))
        menu.addItem(.separator())
        menu.addItem(item(title: "Quit",    sel: #selector(quit),    key: "q"))
    }

    func buildPresetSubmenu(presets: [[String: Any]], activeId: String) -> NSMenu {
        let sub = NSMenu()
        if presets.isEmpty {
            sub.addItem(disabledItem("(no presets — run install.sh or Edit Presets…)"))
            return sub
        }
        for preset in presets {
            guard let id = preset["id"] as? String,
                  let name = preset["name"] as? String else { continue }
            let it = NSMenuItem(title: name, action: #selector(selectPreset(_:)), keyEquivalent: "")
            it.target = self
            it.representedObject = id
            it.state = (id == activeId) ? .on : .off
            sub.addItem(it)
        }
        return sub
    }

    func item(title: String, sel: Selector, key: String) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        i.target = self
        return i
    }

    func disabledItem(_ title: String) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        it.isEnabled = false
        return it
    }

    // MARK: - Config & presets I/O

    func ensureConfigDir() {
        try? FileManager.default.createDirectory(
            atPath: configDir, withIntermediateDirectories: true, attributes: nil)
    }

    func loadConfig() -> [String: Any] {
        if let data = try? Data(contentsOf: URL(fileURLWithPath: configPath)),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            return obj
        }
        let presets = loadPresets()
        let firstId = presets.first?["id"] as? String ?? ""
        let firstModel = presets.first?["default_model"] as? String ?? ""
        return [
            "postprocess": false,
            "active_preset": firstId,
            "current_model": firstModel,
        ]
    }

    func saveConfig(_ cfg: [String: Any]) {
        ensureConfigDir()
        guard let data = try? JSONSerialization.data(
            withJSONObject: cfg,
            options: [.prettyPrinted, .sortedKeys]) else { return }
        try? data.write(to: URL(fileURLWithPath: configPath), options: .atomic)
    }

    func loadPresets() -> [[String: Any]] {
        if let data = try? Data(contentsOf: URL(fileURLWithPath: presetsPath)),
           let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
            return arr
        }
        return []
    }

    // MARK: - Actions: config

    @objc func togglePostprocess() {
        var cfg = loadConfig()
        let current = (cfg["postprocess"] as? Bool) ?? false
        cfg["postprocess"] = !current
        if cfg["active_preset"] == nil || (cfg["active_preset"] as? String)?.isEmpty == true {
            if let first = loadPresets().first?["id"] as? String {
                cfg["active_preset"] = first
            }
        }
        saveConfig(cfg)
    }

    @objc func selectPreset(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        var cfg = loadConfig()
        cfg["active_preset"] = id
        if let preset = loadPresets().first(where: { ($0["id"] as? String) == id }),
           let def = preset["default_model"] as? String {
            cfg["current_model"] = def
        } else {
            cfg["current_model"] = ""
        }
        saveConfig(cfg)
    }

    @objc func selectModel(_ sender: NSMenuItem) {
        guard let model = sender.representedObject as? String else { return }
        var cfg = loadConfig()
        cfg["current_model"] = model
        saveConfig(cfg)
    }

    @objc func editPresets() {
        ensureConfigDir()
        if !FileManager.default.fileExists(atPath: presetsPath) {
            let seed = "[]\n"
            try? seed.write(toFile: presetsPath, atomically: true, encoding: .utf8)
        }
        NSWorkspace.shared.open(URL(fileURLWithPath: presetsPath))
    }

    // MARK: - Actions: daemon control

    @objc func pause()   { _ = run("/bin/launchctl", ["bootout", "gui/\(getuid())/\(label)"]) }
    @objc func resume()  { _ = run("/bin/launchctl", ["bootstrap", "gui/\(getuid())", plistPath]) }
    @objc func restart() { _ = run("/bin/launchctl", ["kickstart", "-k", "gui/\(getuid())/\(label)"]) }
    @objc func showLog() { NSWorkspace.shared.open(URL(fileURLWithPath: logPath)) }
    @objc func quit()    { NSApp.terminate(nil) }

    // MARK: - Status

    func daemonStatus() -> String {
        let out = run("/bin/launchctl", ["list"])
        let line = out.split(separator: "\n").first { $0.hasSuffix(label) }
        let pid = line?.split(separator: "\t").first.map(String.init) ?? "-"
        return pid == "-" ? "Status: Stopped" : "Status: Running · PID \(pid)"
    }

    // MARK: - Log tail for recording indicator

    func startLogTail() {
        let task = Process()
        task.launchPath = "/usr/bin/tail"
        task.arguments = ["-n", "0", "-F", logPath]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = Pipe()

        pipe.fileHandleForReading.readabilityHandler = { [weak self] fh in
            let data = fh.availableData
            guard !data.isEmpty, let s = String(data: data, encoding: .utf8) else { return }
            for line in s.split(separator: "\n") {
                if line.contains("● rec…") {
                    DispatchQueue.main.async { self?.setRecordingIcon() }
                } else if line.contains("✓") || line.contains("too short") || line.contains("[error]") {
                    DispatchQueue.main.async { self?.setIdleIcon() }
                }
            }
        }

        do { try task.run() } catch { NSLog("tail failed: \(error)") }
        tailTask = task
    }

    func applicationWillTerminate(_ notification: Notification) {
        tailTask?.terminate()
    }

    // MARK: - Shell helper

    @discardableResult
    func run(_ path: String, _ args: [String]) -> String {
        let t = Process()
        t.launchPath = path
        t.arguments = args
        let out = Pipe()
        t.standardOutput = out
        t.standardError = out
        do { try t.run(); t.waitUntilExit() } catch { return "" }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8) ?? ""
    }
}

/// Populates the Model submenu on open by hitting /v1/models on the active
/// preset's base_url. Synchronous with a short timeout — if the endpoint is
/// offline the menu briefly hangs then shows "(offline)".
final class ModelSubmenuDelegate: NSObject, NSMenuDelegate {
    let activePreset: [String: Any]?
    let currentModel: String?
    weak var selectionTarget: AnyObject?
    let selectionAction: Selector

    init(activePreset: [String: Any]?,
         currentModel: String?,
         selectionTarget: AnyObject,
         selectionAction: Selector) {
        self.activePreset = activePreset
        self.currentModel = currentModel
        self.selectionTarget = selectionTarget
        self.selectionAction = selectionAction
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        guard let preset = activePreset,
              let baseRaw = preset["base_url"] as? String else {
            menu.addItem(disabledItem("(no active preset)"))
            return
        }
        let base = baseRaw.hasSuffix("/") ? String(baseRaw.dropLast()) : baseRaw
        guard let url = URL(string: base + "/models") else {
            menu.addItem(disabledItem("(bad base_url)"))
            return
        }

        let models = fetchModels(url: url)
        if models.isEmpty {
            menu.addItem(disabledItem("(endpoint offline or empty)"))
            return
        }
        for m in models {
            let it = NSMenuItem(title: m, action: selectionAction, keyEquivalent: "")
            it.target = selectionTarget
            it.representedObject = m
            it.state = (m == currentModel) ? .on : .off
            menu.addItem(it)
        }
    }

    func fetchModels(url: URL) -> [String] {
        let sem = DispatchSemaphore(value: 0)
        var models: [String] = []
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 1.0
        cfg.timeoutIntervalForResource = 1.5
        let session = URLSession(configuration: cfg)
        let task = session.dataTask(with: url) { data, _, _ in
            defer { sem.signal() }
            guard let data = data,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let arr = obj["data"] as? [[String: Any]] else { return }
            models = arr.compactMap { $0["id"] as? String }.sorted()
        }
        task.resume()
        _ = sem.wait(timeout: .now() + 1.5)
        return models
    }

    func disabledItem(_ title: String) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        it.isEnabled = false
        return it
    }
}

extension NSImage {
    func tinted(with color: NSColor) -> NSImage {
        let tinted = self.copy() as! NSImage
        tinted.lockFocus()
        color.set()
        let rect = NSRect(origin: .zero, size: tinted.size)
        rect.fill(using: .sourceAtop)
        tinted.unlockFocus()
        tinted.isTemplate = false
        return tinted
    }
}

let delegate = AppDelegate()
let app = NSApplication.shared
app.delegate = delegate
app.run()
