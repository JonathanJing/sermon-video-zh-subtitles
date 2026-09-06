// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TongxingIOS",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "TongxingInfrastructure", targets: ["TongxingInfrastructure"]),
        .executable(name: "TongxingPreview", targets: ["TongxingPreview"]),
    ],
    dependencies: [.package(path: "Core")],
    targets: [
        .target(
            name: "TongxingInfrastructure",
            dependencies: [.product(name: "TongxingCore", package: "Core")],
            path: "Infrastructure"
        ),
        // The macOS host build checks shared SwiftUI/AVPlayer code with CLT.
        // It does not replace an iOS SDK build or a physical iPhone test.
        .executableTarget(
            name: "TongxingPreview",
            dependencies: ["TongxingInfrastructure", .product(name: "TongxingCore", package: "Core")],
            path: "App",
            exclude: ["Info.plist", "PrivacyInfo.xcprivacy", "Assets.xcassets"]
        ),
        .testTarget(
            name: "TongxingInfrastructureTests",
            dependencies: ["TongxingInfrastructure", .product(name: "TongxingCore", package: "Core")],
            path: "InfrastructureTests"
        ),
    ],
    swiftLanguageVersions: [.v5]
)
