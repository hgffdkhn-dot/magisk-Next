package com.topjohnwu.magisk.ui.settings

import android.content.Intent
import android.widget.Toast
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.topjohnwu.magisk.core.Config
import com.topjohnwu.magisk.core.next.NextFeatures
import com.topjohnwu.magisk.ui.component.SettingsSwitch
import com.topjohnwu.magisk.ui.component.SmallTitle
import com.topjohnwu.magisk.core.R as CoreR
import java.io.File

/**
 * magisk-Next 独立设置分区。
 *
 * 自包含：直接读写 Config，不改动 SettingsUiState / SettingsViewModel，
 * 因此上游合版时只需保留本文件与 SettingsContent 里的一行调用。
 *
 * 三个开关都有实际作用：
 *  - nextModuleSnapshot / nextChannelVerify：构建期默认值 + 体检报告状态项
 *  - nextHealthCheck：控制下方"导出体检报告"入口是否可用
 */
@Composable
fun NextSection(modifier: Modifier = Modifier) {
    var snapshotEnabled by remember { mutableStateOf(Config.nextModuleSnapshot) }
    var verifyEnabled by remember { mutableStateOf(Config.nextChannelVerify) }
    var healthEnabled by remember { mutableStateOf(Config.nextHealthCheck) }
    val context = LocalContext.current

    SmallTitle(text = stringResource(CoreR.string.next_section_title))
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerLow
        )
    ) {
        SettingsSwitch(
            title = stringResource(CoreR.string.next_snapshot_title),
            summary = stringResource(CoreR.string.next_snapshot_summary),
            checked = snapshotEnabled,
            onCheckedChange = {
                Config.nextModuleSnapshot = it
                snapshotEnabled = it
            }
        )

        HorizontalDivider(
            modifier = Modifier.padding(horizontal = 16.dp),
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)
        )

        SettingsSwitch(
            title = stringResource(CoreR.string.next_channel_verify_title),
            summary = stringResource(CoreR.string.next_channel_verify_summary),
            checked = verifyEnabled,
            onCheckedChange = {
                Config.nextChannelVerify = it
                verifyEnabled = it
            }
        )

        HorizontalDivider(
            modifier = Modifier.padding(horizontal = 16.dp),
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)
        )

        SettingsSwitch(
            title = stringResource(CoreR.string.next_health_check_title),
            summary = stringResource(CoreR.string.next_health_check_summary),
            checked = healthEnabled,
            onCheckedChange = {
                Config.nextHealthCheck = it
                healthEnabled = it
            }
        )

        if (healthEnabled) {
            TextButton(
                onClick = {
                    val json = NextFeatures.exportHealthJson()
                    runCatching {
                        File(context.cacheDir, "next-health.json").writeText(json)
                        val send = Intent(Intent.ACTION_SEND).apply {
                            type = "application/json"
                            putExtra(Intent.EXTRA_TEXT, json)
                            putExtra(Intent.EXTRA_SUBJECT, "${NextFeatures.BRAND} health report")
                        }
                        val chooser = Intent.createChooser(send, null)
                        chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        context.startActivity(chooser)
                    }.onFailure {
                        Toast.makeText(
                            context,
                            it.message ?: "Export failed",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                },
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
            ) {
                Text(stringResource(CoreR.string.next_export_button))
            }
        } else {
            Text(
                text = stringResource(CoreR.string.next_health_disabled),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)
            )
        }

        Text(
            text = "${NextFeatures.BRAND} ${NextFeatures.VERSION} · upstream ${NextFeatures.UPSTREAM_BASELINE}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)
        )
    }
}
