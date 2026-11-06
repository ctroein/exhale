// Native EXHALE setup and launcher. The Python driver owns private runtime operations.
import AppKit
import Foundation

let resources = Bundle.main.resourceURL!
let support = ProcessInfo.processInfo.environment["EXHALE_SETUP_HOME"].map { URL(fileURLWithPath: $0) }
    ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("EXHALE")

func makeProcess(_ action: String, _ arguments: [String] = []) -> Process {
    let process = Process()
    process.executableURL = resources.appendingPathComponent("uv")
    process.arguments = ["run", "--no-project", "--no-config", "--managed-python", "--python", "3.12",
                         "python", resources.appendingPathComponent("runtime.py").path,
                         "--resources", resources.path, "--home", support.path, action] + arguments
    var env = ProcessInfo.processInfo.environment
    for key in Array(env.keys) where key.hasPrefix("UV_") || key.hasPrefix("PYTHON") || key == "VIRTUAL_ENV" {
        env.removeValue(forKey: key)
    }
    env["UV_PYTHON_INSTALL_DIR"] = support.appendingPathComponent("runtime/python").path
    env["UV_PYTHON_BIN_DIR"] = support.appendingPathComponent("runtime/bin").path
    env["UV_CACHE_DIR"] = support.appendingPathComponent("runtime/cache").path
    env["UV_NO_PROGRESS"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    process.environment = env
    process.standardInput = FileHandle.nullDevice
    return process
}

// Exercise precisely the same setup driver as the GUI, without requiring a desktop session.
if let index = CommandLine.arguments.firstIndex(of: "--setup-check") {
    guard CommandLine.arguments.count > index + 1 else { exit(2) }
    do {
        let process = makeProcess("install", [CommandLine.arguments[index + 1]])
        try process.run()
        process.waitUntilExit()
        exit(process.terminationStatus)
    } catch {
        fputs("\(error)\n", stderr)
        exit(1)
    }
}

class SetupDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    let starDist = NSButton(checkboxWithTitle: "StarDist — TensorFlow", target: nil, action: nil)
    let cellpose = NSButton(checkboxWithTitle: "Cellpose and MONAI U-Net — PyTorch and DINOv3", target: nil, action: nil)
    let install = NSButton(title: "Install and Open", target: nil, action: nil)
    let remove = NSButton(title: "Remove Runtime…", target: nil, action: nil)
    let open = NSButton(title: "Open EXHALE", target: nil, action: nil)
    let status = NSTextField(labelWithString: "Choose the segmentation backends to install.")
    let log = NSTextView()
    var running = false
    var installed: [String: String]? {
        guard let data = try? Data(contentsOf: support.appendingPathComponent("runtime/installed.json")) else { return nil }
        return try? JSONDecoder().decode([String: String].self, from: data)
    }
    var config: [String: String] {
        guard let data = try? Data(contentsOf: resources.appendingPathComponent("setup.json")),
              let config = try? JSONDecoder().decode([String: String].self, from: data) else { return [:] }
        return config
    }
    var currentWheel: String? { config["wheel"] }
    var supportsCellpose: Bool {
        config["architecture"] == "arm64" && ProcessInfo.processInfo.isOperatingSystemAtLeast(
            OperatingSystemVersion(majorVersion: 14, minorVersion: 0, patchVersion: 0))
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let appMenu = NSMenu()
        let item = NSMenuItem()
        item.submenu = appMenu
        menu.addItem(item)
        appMenu.addItem(withTitle: "Quit EXHALE", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 660, height: 480),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "EXHALE Setup"
        window.delegate = self
        window.center()
        let heading = NSTextField(wrappingLabelWithString:
            "EXHALE downloads a private Python environment and the selected packages. Internet access is required. Selecting neither backend installs viewing and composition only.")
        starDist.state = .on
        if let selection = installed?["backends"] {
            starDist.state = ["stardist", "both"].contains(selection) ? .on : .off
            cellpose.state = ["cellpose", "both"].contains(selection) ? .on : .off
        }
        if !supportsCellpose {
            cellpose.state = .off
            cellpose.title = "Cellpose and MONAI U-Net — requires Apple Silicon and macOS 14+"
        }
        install.target = self; install.action = #selector(installClicked)
        open.target = self; open.action = #selector(openClicked)
        remove.target = self; remove.action = #selector(removeClicked)
        let buttons = NSStackView(views: [install, open, remove])
        buttons.orientation = .horizontal
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        scroll.documentView = log
        log.isEditable = false
        log.isVerticallyResizable = true
        log.autoresizingMask = [.width]
        log.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        log.textContainer?.widthTracksTextView = true
        let stack = NSStackView(views: [heading, starDist, cellpose, status, buttons, scroll])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -20),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 20),
            stack.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor, constant: -20),
            scroll.widthAnchor.constraint(equalTo: stack.widthAnchor),
            heading.widthAnchor.constraint(equalTo: stack.widthAnchor),
            scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 180)
        ])
        refreshButtons()
        let setup = CommandLine.arguments.contains("--setup") || NSEvent.modifierFlags.contains(.option)
        if !setup, installed?["wheel"] == currentWheel, installed != nil {
            launch()
        } else {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    func refreshButtons() {
        install.isEnabled = !running
        starDist.isEnabled = !running
        cellpose.isEnabled = !running && supportsCellpose
        remove.isEnabled = !running && installed != nil
        open.isEnabled = !running && installed != nil && installed?["wheel"] == currentWheel
    }

    func append(_ text: String) {
        log.textStorage?.append(NSAttributedString(string: text))
        if log.string.utf16.count > 200_000 {
            log.textStorage?.deleteCharacters(in: NSRange(location: 0, length: 100_000))
        }
        log.scrollToEndOfDocument(nil)
    }

    func perform(_ action: String, _ arguments: [String] = [], completion: @escaping () -> Void) {
        running = true
        refreshButtons()
        status.stringValue = action == "launch" ? "EXHALE is running." : "Setting up EXHALE…"
        DispatchQueue.global(qos: .userInitiated).async {
            let process = makeProcess(action, arguments)
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe
            var failure: String?
            do {
                try process.run()
                while true {
                    let data = pipe.fileHandleForReading.availableData
                    if data.isEmpty { break }
                    let text = String(decoding: data, as: UTF8.self)
                    DispatchQueue.main.async { self.append(text) }
                }
                process.waitUntilExit()
                if process.terminationStatus != 0 {
                    failure = "Operation failed (exit \(process.terminationStatus)). See the log below; you can retry."
                }
            } catch { failure = error.localizedDescription }
            let message = failure
            DispatchQueue.main.async {
                self.running = false
                self.refreshButtons()
                if let message = message {
                    self.status.stringValue = message
                    self.window.makeKeyAndOrderFront(nil)
                    NSApp.activate(ignoringOtherApps: true)
                } else { completion() }
            }
        }
    }

    @objc func installClicked() {
        let selection = starDist.state == .on
            ? (cellpose.state == .on ? "both" : "stardist")
            : (cellpose.state == .on ? "cellpose" : "none")
        perform("install", [selection]) { self.launch() }
    }
    @objc func openClicked() { launch() }
    func launch() {
        window.orderOut(nil)
        perform("launch") { NSApp.terminate(nil) }
    }
    @objc func removeClicked() {
        let alert = NSAlert()
        alert.messageText = "Remove EXHALE's downloaded runtime?"
        alert.informativeText = "This removes its private Python and installed packages. Projects, downloaded models and application settings are retained. You can then move EXHALE.app to Trash."
        alert.addButton(withTitle: "Remove Runtime")
        alert.addButton(withTitle: "Cancel")
        if alert.runModal() == .alertFirstButtonReturn {
            perform("remove") { self.status.stringValue = "Runtime removed." }
        }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if running { return false }
        NSApp.terminate(nil)
        return true
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        return running ? .terminateCancel : .terminateNow
    }
}

let delegate = SetupDelegate()
NSApplication.shared.delegate = delegate
NSApplication.shared.run()
