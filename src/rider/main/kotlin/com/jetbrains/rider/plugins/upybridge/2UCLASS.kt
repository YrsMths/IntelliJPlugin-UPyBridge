package com.jetbrains.rider.plugins.upybridge

import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.project.DumbAwareAction
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.vfs.VirtualFile

internal class `2UCLASS` : DumbAwareAction() {
    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT

    override fun update(e: AnActionEvent) {
        val file: VirtualFile? = e.getData(CommonDataKeys.VIRTUAL_FILE)
        // 选中 .py
        e.presentation.isVisible = file?.extension == "py"
    }

    override fun actionPerformed(e: AnActionEvent) {
        val file = e.getData(CommonDataKeys.VIRTUAL_FILE) ?: return
        try {
            // 临时文件路径
            val tempScript = java.io.File(System.getProperty("java.io.tmpdir"), "upy_bridge.py")

            // 仅在文件不存在时提取资源
            if (!tempScript.exists()) {
                val resource = javaClass.classLoader.getResourceAsStream("scripts/upy_bridge.py")
                    ?: throw IllegalStateException("找不到资源")
                resource.use { input ->
                    tempScript.outputStream().use { output ->
                        input.copyTo(output)
                    }
                }
            }

            // 构建命令
            val pythonExe = "python"
            val target = file.path
            val processBuilder = ProcessBuilder(pythonExe, tempScript.absolutePath, target)
            processBuilder.redirectErrorStream(true)

            val process = processBuilder.start()
            val output = process.inputStream.bufferedReader().readText()
            val exitCode = process.waitFor()
        } catch (ex: Exception) {
            Messages.showErrorDialog("失败: ${ex.message}", "2UCLASSAction")
        }
    }
}