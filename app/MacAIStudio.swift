// A small native Mac window around the local studio tools. It runs each tool through
// lib/services.sh, shows it in a tab, and stops everything it started on quit.
// Built by lib/build_app.sh with the Swift compiler from Apple's Command Line Tools.
import Cocoa
import UniformTypeIdentifiers
import WebKit

struct Service: Decodable {
  let id: String
  let title: String
}

final class Backend {
  let script: String

  init(script: String) { self.script = script }

  /// Runs a services.sh command without blocking the window and returns its output line.
  func run(_ arguments: [String], completion: @escaping (Int32, String) -> Void) {
    DispatchQueue.global(qos: .userInitiated).async {
      let (status, output) = self.runSync(arguments)
      DispatchQueue.main.async { completion(status, output) }
    }
  }

  @discardableResult
  func runSync(_ arguments: [String]) -> (Int32, String) {
    let process = Process()
    let pipe = Pipe()
    process.executableURL = URL(fileURLWithPath: "/bin/bash")
    process.arguments = [script] + arguments
    process.standardOutput = pipe
    process.standardError = FileHandle.nullDevice
    do {
      try process.run()
    } catch {
      return (127, "")
    }
    // Read before waiting: a full pipe would otherwise block the script forever.
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    let output = String(data: data, encoding: .utf8) ?? ""
    return (process.terminationStatus, output.trimmingCharacters(in: .whitespacesAndNewlines))
  }
}

final class StudioController: NSObject, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate,
  WKDownloadDelegate
{
  private let backend: Backend
  private let services: [Service]
  private let window: NSWindow
  private let tabs = NSSegmentedControl()
  private let container = NSView()
  private let status = NSTextField(labelWithString: "")
  private var views: [String: WKWebView] = [:]
  private var current: Service?
  private var downloadTargets: [ObjectIdentifier: URL] = [:]

  init(backend: Backend, services: [Service]) {
    self.backend = backend
    self.services = services
    window = NSWindow(
      contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900),
      styleMask: [.titled, .closable, .miniaturizable, .resizable],
      backing: .buffered, defer: false)
    super.init()
    window.title = "Mac AI Studio"
    window.delegate = self
    window.minSize = NSSize(width: 900, height: 600)
    window.setFrameAutosaveName("MacAIStudioMain")
    buildInterface()
    window.center()
    window.makeKeyAndOrderFront(nil)
    if !services.isEmpty { select(index: 0) }
  }

  private func buildInterface() {
    let content = NSView()
    window.contentView = content

    tabs.segmentCount = services.count
    tabs.trackingMode = .selectOne
    tabs.target = self
    tabs.action = #selector(tabChanged)
    for (index, service) in services.enumerated() {
      tabs.setLabel(service.title, forSegment: index)
    }

    let models = NSButton(title: "Models", target: self, action: #selector(openModels))
    let outputs = NSButton(title: "My Files", target: self, action: #selector(openOutputs))
    status.textColor = .secondaryLabelColor

    let toolbar = NSStackView(views: [tabs, status, NSView(), outputs, models])
    toolbar.orientation = .horizontal
    toolbar.spacing = 10
    toolbar.edgeInsets = NSEdgeInsets(top: 8, left: 12, bottom: 8, right: 12)

    for view in [toolbar, container] as [NSView] {
      view.translatesAutoresizingMaskIntoConstraints = false
      content.addSubview(view)
    }
    NSLayoutConstraint.activate([
      toolbar.topAnchor.constraint(equalTo: content.topAnchor),
      toolbar.leadingAnchor.constraint(equalTo: content.leadingAnchor),
      toolbar.trailingAnchor.constraint(equalTo: content.trailingAnchor),
      container.topAnchor.constraint(equalTo: toolbar.bottomAnchor),
      container.leadingAnchor.constraint(equalTo: content.leadingAnchor),
      container.trailingAnchor.constraint(equalTo: content.trailingAnchor),
      container.bottomAnchor.constraint(equalTo: content.bottomAnchor),
    ])
  }

  @objc private func tabChanged() { select(index: tabs.selectedSegment) }

  private func select(index: Int) {
    guard services.indices.contains(index) else { return }
    tabs.selectedSegment = index
    let service = services[index]
    current = service
    if let view = views[service.id] {
      show(view)
      return
    }
    status.stringValue = "Starting \(service.title)…"
    backend.run(["start", service.id]) { [weak self] code, output in
      guard let self else { return }
      guard code == 0, let url = URL(string: output), url.scheme == "http" else {
        if self.current?.id == service.id {
          self.status.stringValue = "\(service.title) did not start. See the logs folder."
        }
        return
      }
      let view = self.makeWebView()
      self.views[service.id] = view
      view.load(URLRequest(url: url))
      if self.current?.id == service.id {
        self.status.stringValue = ""
        self.show(view)
      }
    }
  }

  private func makeWebView() -> WKWebView {
    let view = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
    view.uiDelegate = self
    view.navigationDelegate = self
    view.allowsBackForwardNavigationGestures = false
    return view
  }

  private func show(_ view: WKWebView) {
    container.subviews.forEach { $0.removeFromSuperview() }
    view.translatesAutoresizingMaskIntoConstraints = false
    container.addSubview(view)
    NSLayoutConstraint.activate([
      view.topAnchor.constraint(equalTo: container.topAnchor),
      view.bottomAnchor.constraint(equalTo: container.bottomAnchor),
      view.leadingAnchor.constraint(equalTo: container.leadingAnchor),
      view.trailingAnchor.constraint(equalTo: container.trailingAnchor),
    ])
    status.stringValue = ""
  }

  @objc private func openModels() { backend.run(["open-models"]) { _, _ in } }
  @objc private func openOutputs() { backend.run(["open-outputs"]) { _, _ in } }

  func windowShouldClose(_ sender: NSWindow) -> Bool {
    NSApp.terminate(nil)
    return false
  }

  // MARK: Dialogs the tools' pages ask for. A web view shows none of these by itself.

  func webView(
    _ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
    initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void
  ) {
    let panel = NSOpenPanel()
    panel.allowsMultipleSelection = parameters.allowsMultipleSelection
    panel.canChooseDirectories = parameters.allowsDirectories
    panel.beginSheetModal(for: window) { response in
      completionHandler(response == .OK ? panel.urls : nil)
    }
  }

  func webView(
    _ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
    initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void
  ) {
    let alert = NSAlert()
    alert.messageText = message
    alert.beginSheetModal(for: window) { _ in completionHandler() }
  }

  func webView(
    _ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
    initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void
  ) {
    let alert = NSAlert()
    alert.messageText = message
    alert.addButton(withTitle: "OK")
    alert.addButton(withTitle: "Cancel")
    alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
  }

  func webView(
    _ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
    defaultText: String?, initiatedByFrame frame: WKFrameInfo,
    completionHandler: @escaping (String?) -> Void
  ) {
    let alert = NSAlert()
    let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
    field.stringValue = defaultText ?? ""
    alert.messageText = prompt
    alert.accessoryView = field
    alert.addButton(withTitle: "OK")
    alert.addButton(withTitle: "Cancel")
    alert.beginSheetModal(for: window) {
      completionHandler($0 == .alertFirstButtonReturn ? field.stringValue : nil)
    }
  }

  /// Pages opening a new window stay inside the app when local; anything else goes to the browser.
  func webView(
    _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
    for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
  ) -> WKWebView? {
    if let url = navigationAction.request.url {
      if StudioController.isLocal(url) { webView.load(URLRequest(url: url)) }
      else { NSWorkspace.shared.open(url) }
    }
    return nil
  }

  static func isLocal(_ url: URL) -> Bool {
    return url.host == "127.0.0.1" || url.scheme == "blob" || url.scheme == "data"
      || url.scheme == "about"
  }

  // MARK: Downloads, and keeping outside links out of the app

  func webView(
    _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
    preferences: WKWebpagePreferences,
    decisionHandler: @escaping (WKNavigationActionPolicy, WKWebpagePreferences) -> Void
  ) {
    if navigationAction.shouldPerformDownload {
      decisionHandler(.download, preferences)
    } else if let url = navigationAction.request.url, !StudioController.isLocal(url),
      navigationAction.targetFrame?.isMainFrame == true
    {
      NSWorkspace.shared.open(url)
      decisionHandler(.cancel, preferences)
    } else {
      decisionHandler(.allow, preferences)
    }
  }

  func webView(
    _ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
    decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
  ) {
    decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)
  }

  func webView(
    _ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload
  ) { download.delegate = self }

  func webView(
    _ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload
  ) { download.delegate = self }

  func download(
    _ download: WKDownload, decideDestinationUsing response: URLResponse,
    suggestedFilename: String, completionHandler: @escaping (URL?) -> Void
  ) {
    let panel = NSSavePanel()
    panel.nameFieldStringValue = suggestedFilename
    panel.beginSheetModal(for: window) { result in
      completionHandler(result == .OK ? panel.url : nil)
    }
  }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
  private var controller: StudioController?
  private var backend: Backend?

  func applicationDidFinishLaunching(_ notification: Notification) {
    buildMenu()
    let script = Bundle.main.url(forResource: "services-path", withExtension: "txt")
      .flatMap { try? String(contentsOf: $0, encoding: .utf8) }?
      .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    let backend = Backend(script: script)
    self.backend = backend

    let (code, output) = backend.runSync(["list"])
    let services =
      output.data(using: .utf8).flatMap { try? JSONDecoder().decode([Service].self, from: $0) }
      ?? []
    guard code == 0, !services.isEmpty else {
      let alert = NSAlert()
      alert.messageText = "Mac AI Studio is not installed correctly"
      alert.informativeText = "Run milestone1.sh again, then reopen the app."
      alert.runModal()
      NSApp.terminate(nil)
      return
    }
    controller = StudioController(backend: backend, services: services)
    NSApp.activate(ignoringOtherApps: true)
  }

  func applicationWillTerminate(_ notification: Notification) {
    backend?.runSync(["stop-all"])
  }

  func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

  /// Without an Edit menu, copy, paste and undo do not work inside a web view.
  private func buildMenu() {
    let main = NSMenu()
    let appItem = NSMenuItem()
    let appMenu = NSMenu()
    appMenu.addItem(withTitle: "Quit Mac AI Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
    appItem.submenu = appMenu
    main.addItem(appItem)

    let editItem = NSMenuItem()
    let editMenu = NSMenu(title: "Edit")
    editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
    let redo = editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
    redo.keyEquivalentModifierMask = [.command, .shift]
    editMenu.addItem(.separator())
    editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
    editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
    editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
    editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
    editItem.submenu = editMenu
    main.addItem(editItem)
    NSApp.mainMenu = main
  }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
