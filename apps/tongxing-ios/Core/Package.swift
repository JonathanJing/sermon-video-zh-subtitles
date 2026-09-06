// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TongxingCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "TongxingCore", targets: ["TongxingCore"])],
    targets: [
        .target(name: "TongxingCore"),
        .testTarget(name: "TongxingCoreTests", dependencies: ["TongxingCore"], resources: [.copy("Fixtures")])
    ],
    swiftLanguageVersions: [.v5]
)
