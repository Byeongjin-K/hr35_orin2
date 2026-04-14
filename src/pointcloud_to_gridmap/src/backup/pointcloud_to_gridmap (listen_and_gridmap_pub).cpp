#include <rclcpp/rclcpp.hpp>
#include <grid_map_ros/grid_map_ros.hpp>
#include <grid_map_msgs/msg/grid_map.hpp>
#include <cmath>
#include <memory>
#include <utility>
#include <sensor_msgs/msg/point_cloud2.hpp> // PointCloud2 메시지 타입
#include <sensor_msgs/point_cloud2_iterator.hpp>

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
    map_.setGeometry(grid_map::Length(100, 100), 0.1);
  }

private:
  void pointCloudCallback(const sensor_msgs::msg::PointCloud2::SharedPtr msg)
  {
    rclcpp::Time time = this->now();
/*    
    // 그리드 맵에 데이터 추가
    rclcpp::Time time = this->now();
    for (grid_map::GridMapIterator it(map_); !it.isPastEnd(); ++it) {
      grid_map::Position position;
      map_.getPosition(*it, position);
      map_.at("elevation", *it) = -0.04 + 0.2 * std::sin(3.0 * time.seconds() + 5.0 * position.y()) * position.x();
    }
*/

    for (sensor_msgs::PointCloud2ConstIterator<float> iter_x(*msg, "x"), iter_y(*msg, "y"), iter_z(*msg, "z");
         iter_x != iter_x.end();
         ++iter_x, ++iter_y, ++iter_z)
    {    
      grid_map::Position position(*iter_x, *iter_y); // 점의 위치 가져오기

      if (map_.isInside(position)) // 그리드 맵 범위 내에 있는지 확인
      {
        map_.atPosition("elevation", position) = *iter_z;  // 그리드 맵의 해당 위치에 고도 값 업데이트
      }
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
