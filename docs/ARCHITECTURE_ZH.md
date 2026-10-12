# EncodeForge 项目架构与能力说明

## 项目定位

EncodeForge 是跨平台 PySide6 桌面媒体工具，围绕 FFmpeg 提供视频批量编码、字幕处理和媒体文件智能改名。应用支持 Windows、macOS、Linux；AI 字幕使用本地 faster-whisper，不依赖云端服务。

## 分层架构

```text
入口层：main.py / cli.py
   ├─ GUI：app/main_window.py、app/widgets、app/dialogs
   └─ CLI：rename 命令（与 GUI 共用核心）
业务核心：core/
   ├─ handlers：文件扫描、编码、字幕、改名流程
   ├─ providers：元数据与字幕提供商适配器
   ├─ encodeforge_core.py：统一业务门面
   ├─ ffmpeg_manager.py / subtitle_manager.py：媒体能力
   └─ rename_pattern.py / rename_executor.py：命名解析与执行
基础设施：utils/
   ├─ settings_manager.py：持久化设置
   ├─ workers.py：后台线程任务
   ├─ theme_manager.py / app_stylesheet.py：主题
   ├─ update_checker.py / download_manager.py：更新与下载
   └─ i18n.py：界面简体中文本地化
资源与发布：resources/、packaging/、build_*.py
```

## 核心能力

| 模块 | 当前能力 |
|---|---|
| 视频编码 | MP4/MKV/WebM 等容器；H.264/H.265/AV1/VP9；批量队列；音频复制/转码/标准化；NVENC、AMF、Quick Sync、VideoToolbox |
| 字幕 | OpenSubtitles、Addic7ed、SubDL、Subf2m、YIFY、Podnapisi、SubDivX、Jimaku；SRT/ASS/SSA/VTT；本地 Whisper 生成 |
| 元数据改名 | TMDB、TVDB、OMDb、Trakt、AniDB、Kitsu、Jikan/MAL、TVmaze；电影/剧集/动漫识别；预览、批量改名、移动/复制及伴随文件处理 |
| GUI | 深色玻璃拟态界面、拖放/文件夹导入、实时进度、日志、进程监控、配置档案 |
| CLI | `python cli.py rename` 已可用，支持 dry-run、递归扫描、命名模板、目标目录、sidecar；`encode`/`subtitle` 仍是占位命令 |

## 运行与数据流

1. `main.py` 初始化日志、Qt 应用、主题和中文界面；检查 FFmpeg，缺失时进入配置对话框。
2. 主窗口创建各功能 Tab。耗时任务通过 `QThreadPool`/Worker 放到后台，避免阻塞界面。
3. Tab 将设置组装成 `ConversionSettings`，交给 `EncodeForgeCore` 和对应 handler。
4. handler 调用 FFmpeg、Whisper 或 provider，结果通过 Qt Signal 回传进度、成功或错误状态。
5. 设置写入平台用户目录；日志、缓存和 FFmpeg 路径由 `core.path_manager` 统一管理。

## 当前边界与风险

- FFmpeg 不是内置依赖，首次运行必须检测、下载或手动指定。
- 元数据和字幕 provider 受网络、API key、限流影响；无 key 时仍可使用部分免费来源。
- CLI 编码/字幕子命令尚未实现；并发任务能力仍以单个 GUI 队列为主。
- 主题设置中的浅色/自动模式及插件体系属于路线图能力。

## 开发与验证

```bash
pip install -r requirements-dev.txt
pytest
python main.py
python cli.py rename ./media --dry-run
```

## 汉化说明

当前版本内置简体中文界面层，默认启用；设置环境变量 `ENCODEFORGE_LANG=en` 可恢复英文。该层只替换 Qt 可见文案，不改变媒体处理中的英文 codec、语言码、文件格式和 API 字段。
