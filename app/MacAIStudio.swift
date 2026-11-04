// A small native Mac window around the local studio tools. It runs each tool through
// lib/services.sh, shows it in a tab, and stops everything it started on quit.
// Built by lib/build_app.sh with the Swift compiler from Apple's Command Line Tools.
import Cocoa
import UniformTypeIdentifiers
import WebKit

struct Service: Decodable {
  let id: String
  let title: String
  /// One sentence on what the tool does while it starts; shown on the loading screen.
  let hint: String?
  /// Seconds services.sh waits for the tool before it gives up.
  let timeout: Int?
}

final class Backend {
  let script: String

  init(script: String) { self.script = script }

  /// Runs a services.sh command without blocking the window and returns its output line and,
  /// when it fails, its last error line.
  func run(_ arguments: [String], completion: @escaping (Int32, String, String) -> Void) {
    DispatchQueue.global(qos: .userInitiated).async {
      let (status, output, error) = self.runSync(arguments)
      DispatchQueue.main.async { completion(status, output, error) }
    }
  }

  @discardableResult
  func runSync(_ arguments: [String]) -> (Int32, String, String) {
    let process = Process()
    let output = Pipe()
    let errors = Pipe()
    process.executableURL = URL(fileURLWithPath: "/bin/bash")
    process.arguments = [script] + arguments
    process.standardOutput = output
    process.standardError = errors
    do {
      try process.run()
    } catch {
      return (127, "", "")
    }
    // Read before waiting: a full pipe would otherwise block the script forever. The script
    // prints a line or two on each pipe; its tools write to the log files instead.
    let outputText = Backend.text(output.fileHandleForReading.readDataToEndOfFile())
    let errorText = Backend.text(errors.fileHandleForReading.readDataToEndOfFile())
    process.waitUntilExit()
    let lastError = errorText.split(separator: "\n").last.map(String.init) ?? ""
    return (process.terminationStatus, outputText, lastError)
  }

  private static func text(_ data: Data) -> String {
    return (String(data: data, encoding: .utf8) ?? "")
      .trimmingCharacters(in: .whitespacesAndNewlines)
  }
}

/// What a tab shows while its tool starts: two turning rings, a clock and a changing hint, so a
/// model load of several minutes does not look like a frozen app. When the start fails it shows
/// the reason, with Try again and Show logs buttons.
final class LoadingView: NSView {
  var retry: (() -> Void)?
  var showLogs: (() -> Void)?

  private static let ringSize: CGFloat = 76
  private let serviceTitle: String
  private let hints: [String]
  private let ringHost = NSView()
  private let outerRing = CAShapeLayer()
  private let innerRing = CAShapeLayer()
  private let symbol = NSImageView()
  private let heading = NSTextField(labelWithString: "")
  private let hint = NSTextField(wrappingLabelWithString: "")
  private let elapsed = NSTextField(labelWithString: "")
  private let buttons = NSStackView()
  private let started = Date()
  private var timer: Timer?
  private var ticks = 0
  private var hintIndex = 0

  init(service: Service) {
    serviceTitle = service.title
    let minutes = max(1, (service.timeout ?? 180) / 60)
    hints = [
      service.hint ?? "\(service.title) is starting.",
      "Nothing is frozen: the tool loads in the background, and its page opens here by itself.",
      "The first start after a restart is the slowest, because the models are read from disk into memory.",
      "The studio waits up to \(minutes) minutes before it reports a problem.",
    ]
    super.init(frame: .zero)
    build()
    heading.stringValue = "Starting \(service.title)"
    hint.stringValue = hints[0]
    elapsed.stringValue = "Starting for 0:00"
    let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.tick() }
    // The common mode keeps the clock running while a menu is open or the window is resized.
    RunLoop.main.add(timer, forMode: .common)
    self.timer = timer
  }

  required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

  deinit { timer?.invalidate() }

  private func build() {
    ringHost.wantsLayer = true
    ringHost.translatesAutoresizingMaskIntoConstraints = false
    let frame = CGRect(x: 0, y: 0, width: LoadingView.ringSize, height: LoadingView.ringSize)
    for (ring, inset, arc) in [(outerRing, 4.0, 0.72), (innerRing, 19.0, 0.45)]
      as [(CAShapeLayer, CGFloat, CGFloat)]
    {
      ring.frame = frame
      ring.path = CGPath(ellipseIn: frame.insetBy(dx: inset, dy: inset), transform: nil)
      ring.fillColor = nil
      ring.lineWidth = 5
      ring.lineCap = .round
      ring.strokeEnd = arc
      ringHost.layer?.addSublayer(ring)
    }

    symbol.image = NSImage(
      systemSymbolName: "exclamationmark.triangle", accessibilityDescription: "Problem")
    symbol.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 44, weight: .regular)
    symbol.contentTintColor = .systemOrange
    symbol.isHidden = true

    heading.font = NSFont.systemFont(ofSize: 20, weight: .semibold)
    heading.alignment = .center
    hint.font = NSFont.systemFont(ofSize: 14)
    hint.textColor = .secondaryLabelColor
    hint.alignment = .center
    hint.preferredMaxLayoutWidth = 440
    hint.wantsLayer = true
    elapsed.font = NSFont.monospacedDigitSystemFont(ofSize: 13, weight: .regular)
    elapsed.textColor = .tertiaryLabelColor
    elapsed.alignment = .center

    let logs = NSButton(title: "Show logs", target: self, action: #selector(openLogs))
    let again = NSButton(title: "Try again", target: self, action: #selector(tryAgain))
    again.keyEquivalent = "\r"
    buttons.orientation = .horizontal
    buttons.spacing = 12
    buttons.addArrangedSubview(logs)
    buttons.addArrangedSubview(again)
    buttons.isHidden = true

    let stack = NSStackView(views: [ringHost, symbol, heading, hint, elapsed, buttons])
    stack.orientation = .vertical
    stack.alignment = .centerX
    stack.spacing = 14
    stack.setCustomSpacing(24, after: ringHost)
    stack.setCustomSpacing(24, after: symbol)
    stack.translatesAutoresizingMaskIntoConstraints = false
    addSubview(stack)
    NSLayoutConstraint.activate([
      ringHost.widthAnchor.constraint(equalToConstant: LoadingView.ringSize),
      ringHost.heightAnchor.constraint(equalToConstant: LoadingView.ringSize),
      hint.widthAnchor.constraint(lessThanOrEqualToConstant: 440),
      stack.centerXAnchor.constraint(equalTo: centerXAnchor),
      stack.centerYAnchor.constraint(equalTo: centerYAnchor, constant: -24),
      stack.leadingAnchor.constraint(greaterThanOrEqualTo: leadingAnchor, constant: 40),
      stack.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -40),
    ])
    applyColors()
  }

  /// Layer colours do not follow light and dark mode by themselves.
  private func applyColors() {
    effectiveAppearance.performAsCurrentDrawingAppearance {
      outerRing.strokeColor = NSColor.controlAccentColor.cgColor
      innerRing.strokeColor = NSColor.controlAccentColor.withAlphaComponent(0.45).cgColor
    }
  }

  override func viewDidChangeEffectiveAppearance() {
    super.viewDidChangeEffectiveAppearance()
    applyColors()
  }

  /// Animations are re-added each time the view returns to the window (after a tab switch).
  override func viewDidMoveToWindow() {
    super.viewDidMoveToWindow()
    if window != nil, timer != nil { spin() }
  }

  private func spin() {
    if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
      // Reduce Motion is on: still rings, and the clock shows that the app is alive.
      outerRing.strokeEnd = 1
      innerRing.strokeEnd = 1
      return
    }
    for (ring, seconds, direction) in [(outerRing, 1.4, -1.0), (innerRing, 2.3, 1.0)]
      as [(CAShapeLayer, Double, Double)]
    {
      let turn = CABasicAnimation(keyPath: "transform.rotation.z")
      turn.fromValue = 0
      turn.toValue = direction * 2 * Double.pi
      turn.duration = seconds
      turn.repeatCount = .infinity
      turn.timingFunction = CAMediaTimingFunction(name: .linear)
      ring.add(turn, forKey: "turn")
    }
  }

  private func tick() {
    ticks += 1
    let seconds = Int(Date().timeIntervalSince(started))
    elapsed.stringValue = String(format: "Starting for %d:%02d", seconds / 60, seconds % 60)
    if ticks % 7 == 0 { nextHint() }
  }

  private func nextHint() {
    hintIndex = (hintIndex + 1) % hints.count
    let text = hints[hintIndex]
    NSAnimationContext.runAnimationGroup({ context in
      context.duration = 0.35
      self.hint.animator().alphaValue = 0
    }, completionHandler: {
      self.hint.stringValue = text
      NSAnimationContext.runAnimationGroup { context in
        context.duration = 0.35
        self.hint.animator().alphaValue = 1
      }
    })
  }

  /// The tool is up: the clock and the rings stop, so a view kept around costs nothing.
  func stop() {
    timer?.invalidate()
    timer = nil
    outerRing.removeAllAnimations()
    innerRing.removeAllAnimations()
  }

  func fail(_ reason: String) {
    stop()
    ringHost.isHidden = true
    symbol.isHidden = false
    heading.stringValue = "\(serviceTitle) did not start"
    hint.alphaValue = 1
    hint.stringValue = reason
    elapsed.isHidden = true
    buttons.isHidden = false
  }

  @objc private func tryAgain() { retry?() }
  @objc private func openLogs() { showLogs?() }
}

final class StudioController: NSObject, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate,
  WKDownloadDelegate
{
  private let backend: Backend
  private let services: [Service]
  private let window: NSWindow
  private let tabs = NSSegmentedControl()
  private let container = NSView()
  private var views: [String: WKWebView] = [:]
  private var loading: [String: LoadingView] = [:]
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

    let toolbar = NSStackView(views: [tabs, NSView(), outputs, models])
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
    } else if let view = loading[service.id] {
      // Still starting, or showing why it did not start.
      show(view)
    } else {
      start(service)
    }
  }

  /// Starts the tool behind a tab and shows the loading screen until its page answers.
  private func start(_ service: Service) {
    let loader = LoadingView(service: service)
    loader.retry = { [weak self] in self?.start(service) }
    loader.showLogs = { [weak self] in self?.backend.run(["open-logs"]) { _, _, _ in } }
    loading[service.id] = loader
    if current?.id == service.id { show(loader) }
    backend.run(["start", service.id]) { [weak self] code, output, error in
      guard let self else { return }
      guard code == 0, let url = URL(string: output), url.scheme == "http" else {
        loader.fail(error.isEmpty ? "The logs folder says why." : error)
        return
      }
      loader.stop()
      self.loading[service.id] = nil
      let view = self.makeWebView()
      self.views[service.id] = view
      view.load(URLRequest(url: url))
      if self.current?.id == service.id { self.show(view) }
    }
  }

  private func makeWebView() -> WKWebView {
    let view = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
    view.uiDelegate = self
    view.navigationDelegate = self
    view.allowsBackForwardNavigationGestures = false
    return view
  }

  private func show(_ view: NSView) {
    container.subviews.forEach { $0.removeFromSuperview() }
    view.translatesAutoresizingMaskIntoConstraints = false
    container.addSubview(view)
    NSLayoutConstraint.activate([
      view.topAnchor.constraint(equalTo: container.topAnchor),
      view.bottomAnchor.constraint(equalTo: container.bottomAnchor),
      view.leadingAnchor.constraint(equalTo: container.leadingAnchor),
      view.trailingAnchor.constraint(equalTo: container.trailingAnchor),
    ])
  }

  @objc private func openModels() { backend.run(["open-models"]) { _, _, _ in } }
  @objc private func openOutputs() { backend.run(["open-outputs"]) { _, _, _ in } }

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

    let (code, output, _) = backend.runSync(["list"])
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
