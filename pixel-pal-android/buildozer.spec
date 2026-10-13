[app]
title = 像素小猫
package.name = pixelpal
package.domain = com.workbuddy
source.dir = .
source.include_exts = py,png,jpg,kv,txt
version = 1.0.0
requirements = python3,kivy==2.3.0,android
orientation = portrait
fullscreen = 0
android.api = 34
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a
android.allow_backup = True
# 联网：与桌面版共用中转服务（好友/串门/消息）
android.permissions = INTERNET
# 中文显示
p4a.extra_build_args = --copy-libs

[buildozer]
log_level = 2
warn_on_root = 1
p4a.branch = 2024.1.1
