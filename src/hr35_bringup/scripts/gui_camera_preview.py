#!/usr/bin/env python3
"""ORIN1 GUI 카메라 패널 전용 저빈도·저해상도 미리보기.

원본 캐빈 영상(1280x800 JPEG, 10 Hz, 약 3.9 MB/s)을 GUI 가 그대로 받으면 ORIN1 의
GUI Python 이 매 프레임을 역직렬화한다. GUI 는 패널을 작게만 보이므로 rate_hz 로
솎은 프레임만 절반 크기로 디코드해 다시 압축한다. 원본 토픽·카메라 노드·녹화는 그대로다.
"""
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage


class GuiCameraPreview(Node):
    def __init__(self) -> None:
        super().__init__("zedx_cabin_gui_preview")
        self.declare_parameter(
            "input_topic", "/zedx_cabin/zedx_cabin_node/left/image_rect_color/compressed"
        )
        self.declare_parameter("output_topic", "/zedx_cabin/gui_preview/compressed")
        self.declare_parameter("rate_hz", 3.0)
        self.declare_parameter("jpeg_quality", 70)
        rate_hz = self.get_parameter("rate_hz").get_parameter_value().double_value
        jpeg_quality = self.get_parameter("jpeg_quality").get_parameter_value().integer_value
        self._min_interval_ns = int(1e9 / rate_hz)
        self._encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
        self._next_due_ns = 0

        # 원본은 best-effort 로 받아 카메라 쪽에 재전송 부담을 주지 않는다. GUI 는 RELIABLE depth 1 로 구독한다.
        source_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        preview_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self._pub = self.create_publisher(
            CompressedImage,
            self.get_parameter("output_topic").get_parameter_value().string_value,
            preview_qos,
        )
        self.create_subscription(
            CompressedImage,
            self.get_parameter("input_topic").get_parameter_value().string_value,
            self._on_image,
            source_qos,
        )

    def _on_image(self, msg: CompressedImage) -> None:
        now_ns = self.get_clock().now().nanoseconds
        if now_ns < self._next_due_ns:
            return
        # 마감 시각을 누적해야 10 Hz 원본에서 평균 rate_hz 가 나온다(직전 발행 기준이면 0.4 s 간격 2.5 Hz).
        self._next_due_ns = max(self._next_due_ns + self._min_interval_ns, now_ns - self._min_interval_ns)
        image = cv2.imdecode(np.frombuffer(msg.data, dtype=np.uint8), cv2.IMREAD_REDUCED_COLOR_2)
        if image is None:
            self.get_logger().warn("원본 프레임 디코드 실패", throttle_duration_sec=5.0)
            return
        ok, encoded = cv2.imencode(".jpg", image, self._encode_params)
        if not ok:
            self.get_logger().warn("미리보기 JPEG 인코드 실패", throttle_duration_sec=5.0)
            return
        out = CompressedImage()
        out.header = msg.header
        out.format = "jpeg"
        out.data = encoded.tobytes()
        self._pub.publish(out)


def main() -> None:
    rclpy.init()
    node = GuiCameraPreview()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
