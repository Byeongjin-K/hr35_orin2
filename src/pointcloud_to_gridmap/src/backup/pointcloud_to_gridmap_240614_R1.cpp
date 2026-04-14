#include <rclcpp/rclcpp.hpp>
#include <grid_map_ros/grid_map_ros.hpp>
#include <grid_map_msgs/msg/grid_map.hpp>
#include <cmath>
#include <memory>
#include <utility>

class GridMapNode : public rclcpp::Node
{
public:
  GridMapNode()
  : Node("pointcloud_to_gridmap"), map_({"elevation"})
  {
    // Publisher 초기화
    publisher_ = this->create_publisher<grid_map_msgs::msg::GridMap>("grid_map", rclcpp::QoS(1).transient_local());

    // Subscriber 초기화
    subscription_ = this->create_subscription<sensor_msgs::msg::PointCloud2>("/robot1/PointCloud2", 10, std::bind(&GridMapNode::pointCloudCallback, this, std::placeholders::_1));

    // 그리드 맵 초기화

    map_.setFrameId("map");
    map_.setGeometry(grid_map::Length(10, 10), 0.05);
  }

private:
  void pointCloudCallback(const sensor_msgs::msg::PointCloud2::SharedPtr msg)
  {
    // 현재 시간 가져오기
    rclcpp::Time time = this->now();

    // 그리드 맵에 데이터 추가
    for (grid_map::GridMapIterator it(map_); !it.isPastEnd(); ++it) {
      grid_map::Position position;
      map_.getPosition(*it, position);
      map_.at("elevation", *it) = -0.04 + 0.2 * std::sin(3.0 * time.seconds() + 5.0 * position.y()) * position.x();
    }

    // 그리드 맵 발행
    map_.setTimestamp(time.nanoseconds());
    std::unique_ptr<grid_map_msgs::msg::GridMap> message;
    message = grid_map::GridMapRosConverter::toMessage(map_);
    publisher_->publish(std::move(message));
    RCLCPP_INFO(this->get_logger(), "Grid map published.");
  }
  
  grid_map::GridMap map_;
  rclcpp::Publisher<grid_map_msgs::msg::GridMap>::SharedPtr publisher_;
  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr subscription_;

};

int main(int argc, char ** argv)
{
  // ROS 2 초기화 및 노드 실행
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<GridMapNode>());
  rclcpp::shutdown();
  return 0;
}
