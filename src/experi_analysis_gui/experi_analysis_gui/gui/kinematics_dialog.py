import numpy as np
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider
)
from PyQt5.QtCore import Qt, QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


JOINT_TOPIC_MAP = {
    '/excavator/sensors/joint_boom': {'name': 'boom', 'type': 'array', 'index': 0, 'unit': 'deg'},
    '/excavator/sensors/joint_arm': {'name': 'arm', 'type': 'array', 'index': 0, 'unit': 'deg'},
    '/excavator/sensors/joint_bucket': {'name': 'bucket', 'type': 'array', 'index': 0, 'unit': 'deg'},
    '/excavator/sensors/swing_angle': {'name': 'swing', 'type': 'scalar', 'unit': 'deg'},
}


class KinematicsDialog(QDialog):
    def __init__(self, bag_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Excavator Kinematics Viewer")
        self.setMinimumSize(1050, 650)
        self._bag_path = bag_path
        self._joint_data = {}
        self._t_range = (0, 1)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._init_ui()
        self._load_joint_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self.status = QLabel("Loading joint data...")
        self.status.setStyleSheet("color: #FFD700;")
        layout.addWidget(self.status)

        ctrl = QHBoxLayout()
        self.btn_play = QPushButton("▶ Play")
        self.btn_play.setCheckable(True)
        self.btn_play.clicked.connect(self._toggle_play)
        ctrl.addWidget(self.btn_play)
        ctrl.addWidget(QLabel("Time:"))
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(0, 1000)
        self.time_slider.valueChanged.connect(self._on_time)
        ctrl.addWidget(self.time_slider, stretch=1)
        self.time_label = QLabel("0.0s")
        self.time_label.setMinimumWidth(80)
        ctrl.addWidget(self.time_label)
        layout.addLayout(ctrl)

        self.figure = Figure(figsize=(11, 5.5))
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas, stretch=1)
        layout.addWidget(QPushButton("Close", clicked=self.close))

    def _toggle_play(self, checked):
        if checked:
            self.btn_play.setText("⏸ Pause")
            self._timer.start(50)
        else:
            self.btn_play.setText("▶ Play")
            self._timer.stop()

    def _advance(self):
        v = self.time_slider.value() + 5
        self.time_slider.setValue(v if v <= 1000 else 0)

    def _on_time(self, value):
        t = self._t_range[0] + (self._t_range[1] - self._t_range[0]) * value / 1000.0
        self.time_label.setText(f"{t - self._t_range[0]:.1f}s")
        self._draw(t)

    def _load_joint_data(self):
        try:
            from core.rosbag_loader import _open_reader
            from rclpy.serialization import deserialize_message
            from std_msgs.msg import Float32, Float32MultiArray

            reader = _open_reader(self._bag_path, topic_filter=list(JOINT_TOPIC_MAP.keys()))
            data = {}
            count = 0
            while reader.has_next() and count < 100000:
                topic, raw, t = reader.read_next()
                if topic not in JOINT_TOPIC_MAP:
                    count += 1; continue
                info = JOINT_TOPIC_MAP[topic]
                name = info['name']
                time_sec = t / 1e9
                try:
                    if info['type'] == 'array':
                        msg = deserialize_message(raw, Float32MultiArray)
                        idx = info.get('index', 0)
                        if len(msg.data) <= idx:
                            count += 1; continue
                        val = float(msg.data[idx])
                    else:
                        msg = deserialize_message(raw, Float32)
                        val = float(msg.data)
                    if name not in data:
                        data[name] = {'times': [], 'values': []}
                    data[name]['times'].append(time_sec)
                    data[name]['values'].append(val)
                except Exception:
                    pass
                count += 1

            for name in data:
                data[name]['times'] = np.array(data[name]['times'])
                data[name]['values'] = np.array(data[name]['values'])

            self._joint_data = data
            all_times = np.concatenate([d['times'] for d in data.values() if len(d['times']) > 0])
            if len(all_times) > 0:
                self._t_range = (float(all_times.min()), float(all_times.max()))
                parts = []
                for name, d in sorted(data.items()):
                    if len(d['values']) > 0:
                        parts.append(f"{name}: [{d['values'].min():.1f}°~{d['values'].max():.1f}°]")
                self.status.setText(f"Duration: {self._t_range[1]-self._t_range[0]:.1f}s | {' | '.join(parts)}")
                self._draw(self._t_range[0])
            else:
                self.status.setText("No joint data found")
        except Exception as e:
            self.status.setText(f"Error: {e}")

    def _val(self, name, t):
        d = self._joint_data.get(name)
        if d is None or len(d['times']) == 0:
            return None
        return float(d['values'][np.argmin(np.abs(d['times'] - t))])

    def _draw(self, t=None):
        fig = self.figure
        fig.clear()
        if not self._joint_data:
            return

        colors = {
            'boom': '#F44336', 'arm': '#4CAF50', 'bucket': '#2196F3', 'swing': '#FF9800',
        }
        t0 = self._t_range[0]

        ax1 = fig.add_subplot(131)
        for name, d in sorted(self._joint_data.items()):
            if len(d['times']) == 0: continue
            ax1.plot(d['times'] - t0, d['values'], color=colors.get(name, 'white'),
                     label=name, linewidth=1, alpha=0.8)
        if t is not None:
            ax1.axvline(t - t0, color='yellow', linewidth=2, linestyle='--', alpha=0.7)
        ax1.set_xlabel('Time (s)'); ax1.set_ylabel('Angle (deg)')
        ax1.set_title('Joint Angles'); ax1.legend(fontsize=6, loc='upper right'); ax1.grid(True, alpha=0.3)

        boom = self._val('boom', t) or 30
        arm = self._val('arm', t) or 90
        bucket = self._val('bucket', t) or 90
        swing = self._val('swing', t) or 0

        ax2 = fig.add_subplot(132)
        self._draw_side(ax2, boom, arm, bucket)

        ax3 = fig.add_subplot(133)
        self._draw_top(ax3, swing)

        fig.tight_layout()
        self.canvas.draw()

    def _draw_side(self, ax, boom_deg, arm_deg, bucket_deg):
        ax.fill([-2, 2, 2, -2, -2], [0, 0, 1.5, 1.5, 0], color='#555', alpha=0.8)
        pivot = np.array([1.5, 1.5])

        boom_rad = np.radians(-boom_deg)
        boom_end = pivot + 5.5 * np.array([np.cos(boom_rad), np.sin(boom_rad)])
        ax.plot([pivot[0], boom_end[0]], [pivot[1], boom_end[1]], 'o-', color='#F44336', lw=5, ms=7)

        arm_abs = boom_rad - np.radians(180 - arm_deg)
        arm_end = boom_end + 3.5 * np.array([np.cos(arm_abs), np.sin(arm_abs)])
        ax.plot([boom_end[0], arm_end[0]], [boom_end[1], arm_end[1]], 'o-', color='#4CAF50', lw=4, ms=6)

        bkt_abs = arm_abs - np.radians(180 - bucket_deg)
        bkt_end = arm_end + 1.5 * np.array([np.cos(bkt_abs), np.sin(bkt_abs)])
        ax.plot([arm_end[0], bkt_end[0]], [arm_end[1], bkt_end[1]], 'o-', color='#2196F3', lw=4, ms=6)

        perp = 0.3 * np.array([-np.sin(bkt_abs), np.cos(bkt_abs)])
        ax.plot([bkt_end[0]+perp[0], bkt_end[0]-perp[0]],
                [bkt_end[1]+perp[1], bkt_end[1]-perp[1]], '-', color='#2196F3', lw=3)

        ax.axhline(0, color='#8B4513', lw=2)
        ax.set_xlim(-5, 12); ax.set_ylim(-6, 10); ax.set_aspect('equal')
        ax.set_title(f'Side View\nBoom={boom_deg:.0f}° Arm={arm_deg:.0f}° Bucket={bucket_deg:.0f}°', fontsize=9)
        ax.grid(True, alpha=0.2)

    def _draw_top(self, ax, swing_deg):
        body = np.array([[-2,-1.25],[2,-1.25],[2,1.25],[-2,1.25],[-2,-1.25]])
        ax.fill(body[:,0], body[:,1], color='#555', alpha=0.5, label='Track')

        sr = np.radians(swing_deg)
        R = np.array([[np.cos(sr), -np.sin(sr)], [np.sin(sr), np.cos(sr)]])
        upper = np.array([[0,-1],[3,-1],[3,1],[0,1],[0,-1]])
        ur = (R @ upper.T).T
        ax.fill(ur[:,0], ur[:,1], color='#777', alpha=0.7, label='Upper')

        bd = R @ np.array([6, 0])
        ax.annotate('', xy=bd, xytext=[0,0], arrowprops=dict(arrowstyle='->', color='#F44336', lw=2))
        ax.text(bd[0]*1.1, bd[1]*1.1, 'Boom', fontsize=8, color='#F44336', ha='center')

        c = np.linspace(0, 2*np.pi, 60)
        ax.plot(8*np.cos(c), 8*np.sin(c), '--', color='#444', lw=0.5)
        ax.set_xlim(-10, 10); ax.set_ylim(-10, 10); ax.set_aspect('equal')
        ax.set_title(f'Top View (Swing={swing_deg:.1f}°)', fontsize=9)
        ax.legend(fontsize=7, loc='upper left'); ax.grid(True, alpha=0.2)
