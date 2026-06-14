import AppKit
import ApplicationServices
import Foundation

struct ElementRecord: Codable {
    let role: String
    let title: String?
    let value: String?
    let description: String?
}

enum ExportError: LocalizedError {
    case accessibilityPermission
    case noWindow
    case itemsTabNotFound

    var errorDescription: String? {
        switch self {
        case .accessibilityPermission:
            return "Accessibility permission is required."
        case .noWindow:
            return "Find My has no accessible window."
        case .itemsTabNotFound:
            return "Could not find the Items tab."
        }
    }
}

guard AXIsProcessTrustedWithOptions(
    [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
) else {
    FileHandle.standardError.write(
        Data("Error: \(ExportError.accessibilityPermission.localizedDescription)\n".utf8)
    )
    exit(1)
}

do {
    let appURL = URL(fileURLWithPath: "/System/Applications/FindMy.app")
    let configuration = NSWorkspace.OpenConfiguration()
    configuration.activates = true
    let runningApplication = try waitForApplication {
        try await NSWorkspace.shared.openApplication(
            at: appURL,
            configuration: configuration
        )
    }
    let app = AXUIElementCreateApplication(runningApplication.processIdentifier)
    guard let window = elements(app, attribute: kAXWindowsAttribute as String).first else {
        throw ExportError.noWindow
    }
    guard let itemsTab = findElement(window, matching: { element in
        let text = textValues(element).joined(separator: ", ").lowercased()
        return text == "items" || text.hasPrefix("items,")
    }) else {
        throw ExportError.itemsTabNotFound
    }
    AXUIElementPerformAction(itemsTab, kAXPressAction as CFString)
    Thread.sleep(forTimeInterval: 1.5)

    let records = allElements(window).map { element in
        ElementRecord(
            role: stringAttribute(element, kAXRoleAttribute as String) ?? "",
            title: stringAttribute(element, kAXTitleAttribute as String),
            value: stringAttribute(element, kAXValueAttribute as String),
            description: stringAttribute(element, kAXDescriptionAttribute as String)
        )
    }
    let data = try JSONEncoder().encode(records)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    FileHandle.standardError.write(Data("Error: \(error.localizedDescription)\n".utf8))
    exit(1)
}

func waitForApplication(
    _ operation: @escaping () async throws -> NSRunningApplication
) throws -> NSRunningApplication {
    let semaphore = DispatchSemaphore(value: 0)
    var result: Result<NSRunningApplication, Error>?
    Task {
        do {
            result = .success(try await operation())
        } catch {
            result = .failure(error)
        }
        semaphore.signal()
    }
    semaphore.wait()
    return try result!.get()
}

func value(_ element: AXUIElement, attribute: String) -> AnyObject? {
    var result: CFTypeRef?
    guard AXUIElementCopyAttributeValue(
        element,
        attribute as CFString,
        &result
    ) == .success else {
        return nil
    }
    return result
}

func stringAttribute(_ element: AXUIElement, _ attribute: String) -> String? {
    value(element, attribute: attribute) as? String
}

func elements(_ element: AXUIElement, attribute: String) -> [AXUIElement] {
    value(element, attribute: attribute) as? [AXUIElement] ?? []
}

func children(_ element: AXUIElement) -> [AXUIElement] {
    elements(element, attribute: kAXChildrenAttribute as String)
}

func allElements(_ root: AXUIElement) -> [AXUIElement] {
    [root] + children(root).flatMap(allElements)
}

func findElement(
    _ root: AXUIElement,
    matching predicate: (AXUIElement) -> Bool
) -> AXUIElement? {
    if predicate(root) {
        return root
    }
    return children(root).compactMap {
        findElement($0, matching: predicate)
    }.first
}

func textValues(_ element: AXUIElement) -> [String] {
    [
        kAXTitleAttribute,
        kAXValueAttribute,
        kAXDescriptionAttribute
    ].compactMap {
        stringAttribute(element, $0 as String)
    }
}
