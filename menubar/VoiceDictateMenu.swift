import AppKit
import Foundation

final class AppDelegate: NSObject, NSApplicationDelegate {
    let label = "com.voicedictate.daemon"
    let logPath = ("~/Library/Logs/voice_dictate.log" as NSString).expandingTildeInPath
    let plistPath = ("~/Library/LaunchAgents/com.voicedictate.daemon.plist" as NSString).expandingTildeInPath

    var statusItem: NSStatusItem!
    var statusLine: NSMenuItem!
    var tailTask: Process?
    var statusTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        setIdleIcon()
        statusItem.menu = buildMenu()

        startLogTail()
        refreshStatus()
        statusTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { _ in
            self.refreshStatus()
        }
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

    func buildMenu() -> NSMenu {
        let m = NSMenu()

        statusLine = NSMenuItem(title: "Status: …", action: nil, keyEquivalent: "")
        statusLine.isEnabled = false
        m.addItem(statusLine)

        m.addItem(.separator())
        m.addItem(item(title: "Pause",   sel: #selector(pause),   key: "p"))
        m.addItem(item(title: "Resume",  sel: #selector(resume),  key: "r"))
        m.addItem(item(title: "Restart", sel: #selector(restart), key: "k"))
        m.addItem(.separator())
        m.addItem(item(title: "Show Log", sel: #selector(showLog), key: "l"))
        m.addItem(.separator())
        m.addItem(item(title: "Quit",    sel: #selector(quit),    key: "q"))

        return m
    }

    func item(title: String, sel: Selector, key: String) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        i.target = self
        return i
    }

    // MARK: - Actions

    @objc func pause()   { _ = run("/bin/launchctl", ["bootout", "gui/\(getuid())/\(label)"]); refreshStatus() }
    @objc func resume()  { _ = run("/bin/launchctl", ["bootstrap", "gui/\(getuid())", plistPath]); refreshStatus() }
    @objc func restart() { _ = run("/bin/launchctl", ["kickstart", "-k", "gui/\(getuid())/\(label)"]); refreshStatus() }
    @objc func showLog() { NSWorkspace.shared.open(URL(fileURLWithPath: logPath)) }
    @objc func quit()    { NSApp.terminate(nil) }

    // MARK: - Status

    func refreshStatus() {
        let out = run("/bin/launchctl", ["list"])
        let line = out.split(separator: "\n").first { $0.hasSuffix(label) }
        let pid = line?.split(separator: "\t").first.map(String.init) ?? "-"
        DispatchQueue.main.async {
            self.statusLine.title = pid == "-" ? "Stopped" : "Running · PID \(pid)"
        }
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

    // MARK: - Helpers

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
