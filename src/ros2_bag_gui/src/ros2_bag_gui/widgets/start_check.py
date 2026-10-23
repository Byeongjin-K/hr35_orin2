"""The question asked at Start when a recording is big or holds the same data twice."""
from PySide6.QtWidgets import QMessageBox, QWidget

from ros2_bag_gui.ros2.topic_notes import HEAVY_GB_PER_HOUR, StartReport


def confirm_start(parent: QWidget, report: StartReport) -> bool:
    """Show what the recording costs and what it holds twice; True to record anyway."""
    lines = []
    if report.heavy:
        lines.append("bag에 들어갈 큰 토픽 (Start 전 측정, 시간당):")
        lines += [f"  {topic}   {size:.1f} GB/h{'  ⚠' if size >= HEAVY_GB_PER_HOUR else ''}"
                  for topic, size in report.heavy]
        lines.append("")
    total = report.bag_gb_per_hour + report.side_gb_per_hour
    lines.append(f"예상: bag {report.bag_gb_per_hour:.0f} GB/h + LAZ·SVO2 약 "
                 f"{report.side_gb_per_hour:.0f} GB/h = 약 {total:.0f} GB/h")
    if report.hours_left is not None:
        lines.append(f"남은 디스크로 약 {report.hours_left:.1f}시간 녹화할 수 있습니다.")
    if report.duplicates or report.laz_and_bag:
        lines.append("")
        lines.append("같은 데이터를 다른 형태로 두 번 저장합니다:")
        lines += [f"  {topic}  =  {original}" for topic, original in report.duplicates]
        lines += [f"  {topic}  (LAZ와 bag 둘 다)" for topic in report.laz_and_bag]
    lines.append("")
    lines.append("이대로 녹화할까요?")
    reply = QMessageBox.question(
        parent, "용량·중복 확인", "\n".join(lines),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    return reply == QMessageBox.StandardButton.Yes
