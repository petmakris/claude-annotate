package com.petros.ireview

import com.intellij.ide.impl.OpenProjectTask
import com.intellij.ide.impl.ProjectUtil
import com.intellij.notification.Notification
import com.intellij.notification.NotificationType
import com.intellij.notification.Notifications
import com.intellij.openapi.application.EDT
import com.intellij.openapi.application.JBProtocolCommand
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.ProjectManager
import com.intellij.openapi.wm.IdeFocusManager
import git4idea.repo.GitRepositoryManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.nio.file.Files
import java.nio.file.Path

/**
 * `jetbrains://idea/ireview/pr-diff?number=6433&repo=acme/shop&branch=TICKET-291-x&path=/abs/checkout&id=PR_kw…`
 *
 * Opens PR `number`'s GitHub diff in the window [PrDiffWindowPicker] picks, opening `path`
 * in a new window when no window holds it. `id` is the PR's GraphQL node id, which saves
 * the IDE its own `gh pr view`.
 */
internal class PrDiffProtocolCommand : JBProtocolCommand("ireview") {

    override suspend fun execute(target: String?, parameters: Map<String, String>, fragment: String?): String? {
        val parsed = PrDiffRequest.parse(target, parameters)
        val request = parsed.request() ?: return parsed.error()
        val number = request.number()
        val path = request.path()
        val branch = request.branch()
        val repo = request.repo()

        val project = withContext(Dispatchers.EDT) { pickOpenWindow(path, branch, repo) }
            ?: path?.let { openInNewWindow(it) }
            ?: return notifyMissing(number, repo)

        withContext(Dispatchers.EDT) { ProjectUtil.focusProjectWindow(project, true) }
        GhPrDiffOpener.openPr(project, number, request.id())
        return null
    }

    private fun pickOpenWindow(path: String?, branch: String?, repo: String?): Project? {
        val focused = IdeFocusManager.getGlobalInstance().lastFocusedFrame?.project
        val byPath = ProjectManager.getInstance().openProjects
            .filter { !it.isDisposed && it.basePath != null }
            .associateBy { it.basePath!! }
        val windows = byPath.values.map { p ->
            val repos = GitRepositoryManager.getInstance(p).repositories
            val root = repos.firstOrNull { it.root.path == p.basePath } ?: repos.firstOrNull()
            PrDiffWindowPicker.Window(
                p.basePath!!,
                root?.currentBranchName,
                repos.flatMap { r -> r.remotes.flatMap { it.urls } },
                p == focused)
        }
        return PrDiffWindowPicker.pick(windows, path, branch, repo).orElse(null)?.let { byPath[it.basePath()] }
    }

    private suspend fun openInNewWindow(path: String): Project? {
        val dir = Path.of(path)
        if (!Files.isDirectory(dir)) return null
        return ProjectUtil.openOrImportAsync(dir, OpenProjectTask { forceOpenInNewFrame = true })
    }

    private fun notifyMissing(number: Long, repo: String?): String {
        val body = "No open window holds ${repo ?: "the PR's repository"}, and no checkout path was given."
        Notifications.Bus.notify(
            Notification("Claude IDE Review", "Couldn't open PR #$number", body, NotificationType.WARNING))
        return body
    }
}
