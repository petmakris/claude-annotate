// promo-ide-driver: a test-only IntelliJ plugin for the ca-18 clip. Built against the
// local IDE given by -PlocalIdePath (default ~/Applications/IntelliJ IDEA.app).
plugins {
    id("java")
    id("org.jetbrains.intellij.platform") version "2.16.0"
}
group = "promo"
version = "0.1"
repositories {
    mavenCentral()
    intellijPlatform { defaultRepositories() }
}
java { toolchain { languageVersion = JavaLanguageVersion.of(25) } }
dependencies {
    intellijPlatform {
        local(providers.gradleProperty("localIdePath")
            .orElse(System.getProperty("user.home") + "/Applications/IntelliJ IDEA.app").get())
    }
}
intellijPlatform {
    buildSearchableOptions = false
    pluginConfiguration { ideaVersion { sinceBuild = "261"; untilBuild = "299.*" } }
}
