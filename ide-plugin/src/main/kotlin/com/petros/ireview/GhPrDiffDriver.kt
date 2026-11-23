package com.petros.ireview

import com.intellij.collaboration.util.ChangesSelection
import com.intellij.diff.util.Side
import com.intellij.openapi.application.EDT
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.service
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.project.Project
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.jetbrains.plugins.github.pullrequest.data.GHPRIdentifier
import org.jetbrains.plugins.github.pullrequest.ui.GHPRConnectedProjectViewModel
import org.jetbrains.plugins.github.pullrequest.ui.GHPRProjectViewModel

/** Project-scoped CoroutineScope holder — the platform injects a scope tied to
 *  the project lifetime, which we use to drive the GitHub diff view model. */
@Service(Service.Level.PROJECT)
internal class IReviewCoroutineScope(val cs: CoroutineScope)

/**
 * Drives the REAL GitHub PR combined-diff editor to a specific file + line,
 * using the bundled GitHub plugin's view models.
 *
 * Flow: activate the connection → open the PR diff tab → acquire the per-PR
 * diff view model (the same instance the open editor renders) → wait for its
 * changes to load → pick the change for [filePath] → [GHPRDiffViewModel.showChange]
 * with a scroll-to-line request. Opening the diff alone leaves it blank because
 * nothing tells it which change to render; showChange is that missing call.
 */
internal object GhPrDiffDriver {

    private val LOG = logger<GhPrDiffDriver>()

    /**
     * Connect the GitHub tool window to its project, then [show] the diff.
     * Called here in Kotlin, not from Java: 2026.3 (build 263) gave
     * activateAndAwaitProject an optional first parameter (the repository and
     * account to connect), which Java cannot leave out. This one call
     * compiles against both 262 and 263.
     */
    @JvmStatic
    fun open(project: Project, vm: GHPRProjectViewModel, prId: GHPRIdentifier,
             filePath: String?, side: String, line: Int) {
        // A function value, not a lambda: Kotlin accepts it whether the
        // parameter is typed (GHPRConnectedProjectViewModel) -> Unit or, as in
        // 263, GHPRConnectedProjectViewModel.() -> Unit.
        val onConnected: (GHPRConnectedProjectViewModel) -> Unit =
            { connected -> show(project, connected, prId, filePath, side, line) }
        vm.activateAndAwaitProject(action = onConnected)
    }

    /**
     * Drive the [connected] PR's diff editor to [filePath] at [line]. Called by
     * [open] once the project is connected.
     *
     * @param prId     the PR identifier.
     * @param filePath project-relative path to show, or null to show the first change.
     * @param side     "L" or "R" — which side [line] refers to.
     * @param line     0-based line to scroll to.
     */
    // The diff VM is passive — it renders whatever showDiffFor() hands it. The
    // changes list itself comes from the PR's data provider, which is Kotlin
    // `internal`; @Suppress is the standard escape hatch for reaching IntelliJ
    // internals from a plugin.
    @JvmStatic
    @Suppress("INVISIBLE_REFERENCE", "INVISIBLE_MEMBER")
    fun show(project: Project, connected: GHPRConnectedProjectViewModel, prId: GHPRIdentifier,
             filePath: String?, side: String, line: Int) {
        val scope = project.service<IReviewCoroutineScope>().cs
        val diffVm = connected.acquireDiffViewModel(prId, scope)
        scope.launch {
            try {
                val dataProvider = connected.dataContext.dataProviderRepository
                    .getDataProvider(prId, scope)
                val changes = dataProvider.changesData.loadChanges().changes
                if (changes.isEmpty()) {
                    LOG.warn("GhPrDiffDriver: PR ${prId.number} loaded 0 changes")
                    notifyWarn(project, "PR diff has no changes",
                        "PR #${prId.number} loaded 0 changes — nothing to show.")
                    return@launch
                }
                val idx = if (filePath != null) {
                    val i = changes.indexOfFirst { c ->
                        val p = c.filePathAfter?.path ?: c.filePathBefore?.path
                        p != null && p.endsWith(filePath)
                    }
                    if (i < 0) {
                        // Silently showing the first change instead would look
                        // like the wrong file "for no reason" — say why and stop.
                        LOG.warn("GhPrDiffDriver: $filePath not among PR ${prId.number}'s changes")
                        notifyWarn(project, "File not in PR diff",
                            "$filePath is not among PR #${prId.number}'s changed files.")
                        return@launch
                    }
                    i
                } else 0
                val location: Pair<Side, Int> = diffSide(side) to maxOf(0, line)
                val selection = ChangesSelection.Precise(changes, idx, location)
                withContext(Dispatchers.EDT) {
                    connected.openPullRequestDiff(prId, true)
                    diffVm.showDiffFor(selection)
                }
            } catch (t: Throwable) {
                LOG.warn("GhPrDiffDriver.show failed for PR ${prId.number}", t)
                notifyWarn(project, "Couldn't open the PR diff",
                    "PR #${prId.number}: ${t.message ?: t.javaClass.simpleName}")
            }
        }
    }

    private fun notifyWarn(project: Project, title: String, body: String) {
        com.intellij.notification.Notifications.Bus.notify(
            com.intellij.notification.Notification(
                "Interactive Review", title, body,
                com.intellij.notification.NotificationType.WARNING),
            project)
    }

    private fun diffSide(side: String): Side =
        if (side.equals("L", ignoreCase = true)) Side.LEFT else Side.RIGHT
}
