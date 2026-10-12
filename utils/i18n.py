"""轻量级界面本地化支持。

项目原有界面没有统一调用 ``tr()``，因此这里提供一个不侵入业务层的
Qt 事件过滤器：窗口/对话框显示时，将常用控件文案替换为简体中文。
通过 ``ENCODEFORGE_LANG=en`` 可恢复英文界面。
"""

from __future__ import annotations

import os
from typing import Dict

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QAbstractButton, QLabel, QWidget


ZH_CN: Dict[str, str] = {
    "Encoder": "编码器", "Subtitles": "字幕", "Metadata": "元数据",
    "Logs": "日志", "Settings": "设置", "Processes": "进程",
    "MODES": "功能", "FILES": "文件", "SYSTEM": "系统",
    "Add Files": "添加文件", "Add Folder": "添加文件夹",
    "Active Encoding Processes": "正在编码的进程", "No active processes": "没有活动进程",
    "Check for Updates…": "检查更新…", "Documentation": "文档",
    "Report an Issue…": "报告问题…", "Open Logs Folder": "打开日志目录",
    "Open Settings Folder": "打开设置目录", "About EncodeForge": "关于 EncodeForge",
    "Format:": "格式：", "Codec:": "编码器：", "Quality:": "质量：",
    "Preset:": "预设：", "Profile:": "配置：", "Load": "加载",
    "Save as…": "另存为…", "HW Accel": "硬件加速", "Normalize": "音频标准化",
    "Delete Source": "删除源文件", "Mode:": "模式：", "Search": "搜索",
    "Languages:": "语言：", "Providers:": "字幕来源：", "Set Up Whisper": "配置 Whisper",
    "FFmpeg Setup": "FFmpeg 设置", "Setup Method": "设置方式",
    "Auto-detect system FFmpeg": "自动检测系统 FFmpeg",
    "Download FFmpeg automatically": "自动下载 FFmpeg",
    "Select FFmpeg executable manually": "手动选择 FFmpeg 可执行文件",
    "Browse…": "浏览…", "Cancel": "取消", "OK": "确定", "Close": "关闭",
    "Start": "开始", "Stop": "停止", "Clear": "清空", "Remove": "移除",
    "Queued": "排队中", "Processing": "处理中", "Completed": "已完成",
    "About EncodeForge": "关于 EncodeForge", "FFmpeg Required": "需要 FFmpeg",
    "Startup Error": "启动错误", "Add Files": "添加文件", "Add Folder": "添加文件夹",
}


def _translate_text(text: str) -> str:
    """Translate only exact labels, preserving dynamic paths and values."""
    return ZH_CN.get(text, text)


class ChineseTranslator(QObject):
    """Translate visible Qt widgets without changing core processing code."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget):
            self._translate_tree(watched)
        return False

    def _translate_tree(self, root: QWidget) -> None:
        for widget in [root, *root.findChildren(QWidget)]:
            if isinstance(widget, (QAbstractButton, QLabel)):
                text = widget.text()
                translated = _translate_text(text.strip())
                if translated != text.strip():
                    prefix = text[: len(text) - len(text.lstrip())]
                    widget.setText(prefix + translated)
            if widget.toolTip():
                widget.setToolTip(_translate_text(widget.toolTip()))
            if widget.windowTitle():
                widget.setWindowTitle(_translate_text(widget.windowTitle()))


_translator: ChineseTranslator | None = None


def install_translator(app: QApplication) -> bool:
    """Install Chinese UI translation unless explicitly overridden.

    Returns ``True`` when Chinese translation is enabled. Set
    ``ENCODEFORGE_LANG=en`` to keep the original English UI.
    """
    global _translator
    language = os.environ.get("ENCODEFORGE_LANG", "zh_CN").lower().replace("-", "_")
    if language not in {"zh", "zh_cn", "zh_hans"}:
        return False
    _translator = ChineseTranslator(app)
    app.installEventFilter(_translator)
    return True
