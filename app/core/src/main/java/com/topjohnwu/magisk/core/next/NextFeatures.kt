package com.topjohnwu.magisk.core.next

import android.os.Build
import com.topjohnwu.magisk.core.BuildConfig
import com.topjohnwu.magisk.core.Config
import com.topjohnwu.magisk.core.Info
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * magisk-Next 分支标识与设备体检数据。
 *
 * 刻意只依赖 Kotlin 标准库 + Android/Java 基础类 + 项目内已有的 Config/Info/BuildConfig，
 * 不引入新的三方依赖，方便在上游合版时整体保留或整体移除。
 *
 * BRAND / CHANNEL 与两个开关的默认值来自构建期 config.prop（经 flags.prop 与
 * Gradle BuildConfig 传递），因此分发方无需改 Kotlin 即可定制分支标识。
 */
object NextFeatures {

    val BRAND: String = BuildConfig.NEXT_BRAND
    const val VERSION = "31.1-next.1"
    const val UPSTREAM_BASELINE = "33bfff7ce7"
    val CHANNEL: String = BuildConfig.NEXT_CHANNEL

    const val STATUS_OK = "ok"
    const val STATUS_WARN = "warn"
    const val STATUS_FAIL = "fail"
    const val STATUS_NA = "na"

    data class Check(
        val id: String,
        val status: String,
        val detail: String,
        val hint: String = "",
    )

    data class Health(
        val brand: String = BRAND,
        val version: String = VERSION,
        val channel: String = CHANNEL,
        val healthEnabled: Boolean = Config.nextHealthCheck,
        val device: String,
        val android: String,
        val generatedAt: String,
        val checks: List<Check>,
    )

    /** 汇总可在不执行 root 命令的前提下获得的状态。 */
    fun collectChecks(): List<Check> {
        val active = Info.env.isActive
        return listOf(
            Check(
                "magisk.active",
                if (active) STATUS_OK else STATUS_FAIL,
                if (active) "Magisk 已激活，核心版本 ${Info.env.versionString}"
                else "未检测到已激活的 Magisk",
                if (active) "" else "请确认已正确刷入 boot 镜像",
            ),
            Check(
                "app.version", STATUS_OK,
                "${BuildConfig.APP_VERSION_NAME} (${BuildConfig.APP_VERSION_CODE})",
            ),
            Check(
                "zygisk.enabled",
                if (Config.zygisk) STATUS_OK else STATUS_WARN,
                if (Config.zygisk) "Zygisk 已启用" else "Zygisk 未启用",
                if (Config.zygisk) "" else "在 Magisk 设置中开启 Zygisk 后重启",
            ),
            Check(
                "zygisk.loaded",
                if (!Config.zygisk) STATUS_NA
                else if (Info.isZygiskEnabled) STATUS_OK else STATUS_WARN,
                if (!Config.zygisk) "Zygisk 关闭，跳过"
                else if (Info.isZygiskEnabled) "Zygisk 已加载" else "配置与运行状态不一致，需重启",
            ),
            Check(
                "denylist.configured",
                if (Config.denyList) STATUS_OK else STATUS_WARN,
                if (Config.denyList) "DenyList 已强制启用" else "DenyList 未强制启用",
                if (Config.denyList) "" else "在设置中开启 Enforce DenyList",
            ),
            Check(
                "next.module.snapshot",
                if (Config.nextModuleSnapshot) STATUS_OK else STATUS_WARN,
                if (Config.nextModuleSnapshot) "模块变更前自动快照已开启" else "模块快照未开启",
                if (Config.nextModuleSnapshot) "" else "建议开启，便于模块变更失败后回滚",
            ),
            Check(
                "next.channel.verify",
                if (Config.nextChannelVerify) STATUS_OK else STATUS_WARN,
                if (Config.nextChannelVerify) "更新通道清单校验已开启" else "更新通道清单校验已关闭",
                if (Config.nextChannelVerify) "" else "关闭后不会校验通道清单签名",
            ),
            Check(
                "app.cloak", STATUS_NA,
                "可选 App Cloak 插件未安装",
                "按需安装，详见 docs/DESIGN.md",
            ),
        )
    }

    fun snapshot(): Health = Health(
        device = "${Build.MANUFACTURER} ${Build.MODEL}".trim(),
        android = "API ${Build.VERSION.SDK_INT} (${Build.VERSION.RELEASE})",
        generatedAt = utcNow(),
        checks = collectChecks(),
    )

    /** 导出为 next/health_report.py 可直接消费的 JSON。 */
    fun exportHealthJson(): String {
        val h = snapshot()
        val sb = StringBuilder(1024)
        sb.append('{')
        sb.append("\"brand\":").append(q(h.brand)).append(',')
        sb.append("\"version\":").append(q(h.version)).append(',')
        sb.append("\"channel\":").append(q(h.channel)).append(',')
        sb.append("\"health_enabled\":").append(h.healthEnabled).append(',')
        sb.append("\"device\":").append(q(h.device)).append(',')
        sb.append("\"android\":").append(q(h.android)).append(',')
        sb.append("\"generated_at\":").append(q(h.generatedAt)).append(',')
        sb.append("\"checks\":[")
        h.checks.forEachIndexed { i, c ->
            if (i > 0) sb.append(',')
            sb.append('{')
            sb.append("\"id\":").append(q(c.id)).append(',')
            sb.append("\"status\":").append(q(c.status)).append(',')
            sb.append("\"detail\":").append(q(c.detail)).append(',')
            sb.append("\"hint\":").append(q(c.hint))
            sb.append('}')
        }
        sb.append("]}")
        return sb.toString()
    }

    private fun utcNow(): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.ROOT)
        fmt.timeZone = TimeZone.getTimeZone("UTC")
        return fmt.format(Date())
    }

    private fun q(s: String): String {
        val sb = StringBuilder(s.length + 2)
        sb.append('"')
        for (ch in s) {
            when (ch) {
                '"' -> sb.append("\\\"")
                '\\' -> sb.append("\\\\")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                else -> if (ch < ' ') sb.append("\\u%04x".format(ch.code)) else sb.append(ch)
            }
        }
        sb.append('"')
        return sb.toString()
    }
}
