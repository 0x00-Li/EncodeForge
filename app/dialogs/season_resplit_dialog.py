"""Configuration dialog for rebuilding a complete season."""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.widgets.custom_widgets import StyledLineEdit
from core.season_resplit import SeasonResplitOptions, find_season_videos


class SeasonResplitDialog(QDialog):
    def __init__(self, parent=None, initial_directory: Optional[Path] = None):
        super().__init__(parent)
        self.setWindowTitle("整季重新切分")
        self.setMinimumWidth(620)

        root = QVBoxLayout(self)
        intro = QLabel(
            "按文件名顺序合并选定目录中的视频，再按指定时长重新切分。"
            "源文件不会被修改。"
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        path_row = QHBoxLayout()
        self.directory_edit = StyledLineEdit()
        if initial_directory:
            self.directory_edit.setText(str(initial_directory))
        self.directory_edit.textChanged.connect(self._update_summary)
        browse = QPushButton("选择目录…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.directory_edit, 1)
        path_row.addWidget(browse)
        form.addRow("整季目录：", path_row)

        self.title_edit = StyledLineEdit()
        self.title_edit.setPlaceholderText("例如：我的剧集")
        form.addRow("剧集名称：", self.title_edit)

        self.season_spin = QSpinBox()
        self.season_spin.setRange(0, 999)
        self.season_spin.setValue(1)
        form.addRow("季号：", self.season_spin)

        duration_row = QHBoxLayout()
        self.min_spin = QSpinBox()
        self.min_spin.setRange(1, 86400)
        self.min_spin.setValue(30)
        self.min_spin.setSuffix(" 秒")
        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 86400)
        self.max_spin.setValue(50)
        self.max_spin.setSuffix(" 秒")
        duration_row.addWidget(QLabel("最短"))
        duration_row.addWidget(self.min_spin)
        duration_row.addWidget(QLabel("最长"))
        duration_row.addWidget(self.max_spin)
        duration_row.addStretch()
        form.addRow("每集时长：", duration_row)
        root.addLayout(form)

        hint = QLabel("将最短和最长设置为相同数值，可使用固定时长。默认在 30–50 秒间逐集随机。")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.summary = QLabel("")
        root.addWidget(self.summary)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("开始重新切分")
        self.buttons.accepted.connect(self._accept_if_valid)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self._update_summary()

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "选择整季所在目录", self.directory_edit.text().strip()
        )
        if selected:
            self.directory_edit.setText(selected)
            if not self.title_edit.text().strip():
                self.title_edit.setText(Path(selected).name)

    def _update_summary(self) -> None:
        directory = Path(self.directory_edit.text().strip()).expanduser()
        count = len(find_season_videos(directory)) if directory.is_dir() else 0
        self.summary.setText(f"已发现 {count} 个可处理的视频文件。")

    def _accept_if_valid(self) -> None:
        try:
            self.options().validate()
        except ValueError as exc:
            self.summary.setText(f"⚠ {exc}")
            return
        if not find_season_videos(self.options().source_dir):
            self.summary.setText("⚠ 目录中没有可处理的视频文件。")
            return
        self.accept()

    def options(self) -> SeasonResplitOptions:
        return SeasonResplitOptions(
            source_dir=Path(self.directory_edit.text().strip()).expanduser(),
            show_title=self.title_edit.text().strip(),
            season=self.season_spin.value(),
            min_episode_seconds=self.min_spin.value(),
            max_episode_seconds=self.max_spin.value(),
        )
