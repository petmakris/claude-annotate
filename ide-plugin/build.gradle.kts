import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("java")
    // Matches the IDE's bundled Kotlin (2.3.10) so the compiler can read the
    // platform's Kotlin metadata. A small Kotlin file (GhPrDiffDriver) drives the
    // GitHub diff view models — their coroutine/value-class APIs aren't callable
    // from Java.
    id("org.jetbrains.kotlin.jvm") version "2.3.10"
    id("org.jetbrains.intellij.platform") version "2.16.0"
}

// Target JVM 21 bytecode for Kotlin: the JBR is 25 (loads 21 fine) and Kotlin
// has no JVM 25 target. Java stays on its 25 toolchain; mixed class versions in
// one jar load fine.
kotlin {
    compilerOptions {
        jvmTarget = JvmTarget.JVM_21
    }
}

group = "com.petros"

// Plugin version is the running commit count on the branch (cheap auto-
// incrementing integer). Build N+1 is one commit ahead of build N — easy
// to reason about without parsing SHAs.
val buildNumber: String = try {
    providers.exec {
        commandLine("git", "rev-list", "--count", "HEAD")
    }.standardOutput.asText.get().trim()
} catch (e: Exception) {
    "0"
}
version = "0.1.$buildNumber"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(25)
    }
}

dependencies {
    intellijPlatform {
        // Prefer a locally installed IDE when there is one: JetBrains' Maven
        // repo lags point releases, and a local install always matches what
        // `runIde` will sandbox against.
        //
        // Resolution order: gradle property `localIdePath`, else env var
        // `IREVIEW_LOCAL_IDE_PATH`, else the usual user-installed location —
        // each used only if it actually exists on disk. When none does (CI, or
        // a contributor without IDEA installed) this downloads the pinned
        // `platformVersion` instead, so the build never depends on one
        // machine's filesystem layout.
        //
        // The download is Ultimate, not Community: Community stops at build
        // 253, and this plugin targets 261+.
        val candidate = providers.gradleProperty("localIdePath")
            .orElse(providers.environmentVariable("IREVIEW_LOCAL_IDE_PATH"))
            .orElse("${System.getProperty("user.home")}/Applications/IntelliJ IDEA.app/Contents")
            .get()
        if (File(candidate).isDirectory) {
            logger.lifecycle("intellijPlatform: using local IDE at $candidate")
            local(candidate)
        } else {
            val pinned = providers.gradleProperty("platformVersion").get()
            logger.lifecycle("intellijPlatform: no local IDE at $candidate — downloading IU $pinned")
            intellijIdeaUltimate(pinned)
        }
        bundledPlugin("com.intellij.java")
        // Bundled JetBrains GitHub plugin — gives us the real PR-diff seam
        // (GHPRProjectViewModel.openPullRequestDiff) so we can drive the
        // GitHub diff view (with inline PR comments) instead of an isolated one.
        bundledPlugin("org.jetbrains.plugins.github")
        // Java code instrumentation is enabled by default in plugin 2.2+.
    }
}

intellijPlatform {
    pluginConfiguration {
        ideaVersion {
            sinceBuild = providers.gradleProperty("pluginSinceBuild")
            untilBuild = providers.gradleProperty("pluginUntilBuild")
        }
    }
}

dependencies {
    implementation("org.commonmark:commonmark:0.24.0")
    implementation("org.commonmark:commonmark-ext-gfm-tables:0.24.0")
    implementation("com.google.code.gson:gson:2.11.0")

    // Provided by the running IDE at runtime; here only for compile + tests.
    compileOnly("org.yaml:snakeyaml:2.2")
    testImplementation("org.yaml:snakeyaml:2.2")

    testImplementation("org.junit.jupiter:junit-jupiter-api:5.10.0")
    testImplementation("org.junit.jupiter:junit-jupiter-engine:5.10.0")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher:1.10.0")
}

tasks.test {
    useJUnitPlatform()
}

tasks.withType<JavaCompile> {
    options.encoding = "UTF-8"
}

// Bake a per-build stamp into the jar so the running plugin can show exactly
// which build is loaded. Unlike the plugin version (git commit count, which
// only moves on a commit), this refreshes on EVERY build — the task is never
// up-to-date — so a plain rebuild + IDE restart is visibly distinguishable.
val generateBuildInfo = tasks.register("generateBuildInfo") {
    val outDir = layout.buildDirectory.dir("generated/buildinfo")
    val gitCount = buildNumber
    outputs.dir(outDir)
    outputs.upToDateWhen { false }
    doLast {
        val stamp = LocalDateTime.now()
            .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
        val f = outDir.get().file("com/petros/ireview/build-info.properties").asFile
        f.parentFile.mkdirs()
        f.writeText("buildTime=$stamp\ngitCount=$gitCount\n")
    }
}
sourceSets["main"].resources.srcDir(generateBuildInfo)
