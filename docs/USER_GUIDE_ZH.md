# EncodeForge 简体中文使用指南

## 启动

安装依赖后运行：

```bash
python main.py
```

首次启动需要配置 FFmpeg，可自动检测、自动下载或手动选择 `ffmpeg` 可执行文件。也可以使用 `python cli.py gui` 启动。

## 三个主要功能

1. **编码器**：添加文件或文件夹，选择容器、编码器、质量、预设和硬件加速，然后开始批量转码。
2. **字幕**：选择下载或 Whisper 本地生成，指定语言、字幕来源和输出格式。
3. **元数据**：扫描媒体后从在线来源匹配电影/剧集/动漫信息，先预览再批量改名。

左侧的“日志”和“进程”用于排错与观察后台任务；“设置”用于保存默认编码、字幕、命名和 API 参数。

## 中文/英文切换

程序默认显示简体中文。启动前设置环境变量即可切换英文：

```bash
ENCODEFORGE_LANG=en python main.py
```

汉化只影响界面文案，不会翻译 FFmpeg 编码器名称、字幕语言码（如 `eng`）或媒体文件名。

## 命令行改名

```bash
python cli.py rename ./媒体目录 --dry-run  # 仅预览
python cli.py rename ./媒体目录 -y         # 确认后执行
python cli.py rename ./媒体目录 -d ./整理后 --action move
```

建议先使用 `--dry-run` 检查匹配结果；程序会为实际改名生成备份记录，并可携带同名 `.srt`、`.ass`、`.nfo` 文件。
