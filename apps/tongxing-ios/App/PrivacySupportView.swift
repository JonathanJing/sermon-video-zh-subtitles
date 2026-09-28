import SwiftUI

/// Available offline. Opening this page does not request microphone access or send feedback.
struct PrivacySupportView: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var playback: PlaybackController

    var body: some View {
        List {
            Section(localization.text("反馈与支持")) {
                Text(localization.text("私密反馈、资料访问或删除请求，请通过邮件联系。下方说明可离线阅读。"))
                    .font(.footnote)
                Link(destination: URL(string: "mailto:achillesjing@gmail.com")!) {
                    Text(verbatim: "achillesjing@gmail.com")
                }
                .accessibilityIdentifier("privacy-contact-email")
            }
            Section(localization.text("匿名使用统计")) {
                Toggle(localization.text("分享匿名使用统计"), isOn: Binding(
                    get: { playback.statisticsEnabled }, set: { playback.setStatisticsEnabled($0) }))
                    .accessibilityIdentifier("anonymous-statistics-toggle")
                Text(localization.text("默认关闭。开启后上传界面语言访问、内容与音频语言、收听时长和播放覆盖范围；只使用每日更新的随机标识，不含姓名、邮箱或广告标识，不跨日追踪。设备数不等于人数。"))
                    .font(.footnote)
                Text(localization.text("关闭后立即停止，并尝试撤回本次 App 运行中已上传的统计；断网时无法保证撤回。没有离线上传队列，未联网期间的使用可能不计入。"))
                    .font(.footnote)
            }
            section("关于本说明", "本说明适用于同行原生 App。同行是独立个人项目，不设登录或广告。匿名统计由你自愿开启。")
            section("麦克风", "只有你点击听音对齐时，App 才会请求麦克风权限。根据所选内容，App 会聆听约 8 秒或 10 秒。声音仅在设备内存中匹配，不保存为录音、不上传。取消或进入后台会停止采音。拒绝权限仍可手动收听和定位。")
            section("内容请求", "App 通过 HTTPS 从 Google Firebase Hosting 下载证道目录、音频和参考指纹。Google 为检测滥用和分析服务使用情况处理请求 IP，其公开说明将 IP 数据保留期描述为数月。打开原视频或网页版后，适用对应网站的隐私规则。")
            section("本机资料", "音频、目录、参考指纹、语言偏好和收听位置保存在本机。收听位置最多保留 12 条，读取或更新时清理超过 30 天的记录。下载音频不进入系统备份；其他本机资料可能随你的系统备份设置保存。删除 App 可移除本机 App 资料；系统备份需在系统设置中管理。")
            section("系统播放展示", "锁屏媒体控件和实时活动会显示当前证道、讲员、播放状态和时间。实时活动不使用推送服务；这些状态不会另行上传到业务服务器。")
        }
        .navigationTitle(localization.text("隐私与支持"))
        .environment(\.locale, localization.locale)
        .accessibilityIdentifier("privacy-support-page")
    }

    private func section(_ title: String, _ text: String) -> some View {
        Section(localization.text(title)) { Text(localization.text(text)) }
    }
}
