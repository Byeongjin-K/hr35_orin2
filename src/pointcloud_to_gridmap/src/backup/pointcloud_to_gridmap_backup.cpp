#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <grid_map_ros/grid_map_ros.hpp>
#include <grid_map_msgs/msg/grid_map.hpp>
#include <pcl_conversions/pcl_conversions.h>
#include <pcl/point_types.h>
#include <pcl/point_cloud.h>
#include <pcl/filters/passthrough.h>
#include <message_filters/subscriber.h>
#include <message_filters/time_synchronizer.h>

class PointCloud2Subscriber : public rclcpp::Node
{
public:
  PointCloud2Subscriber()
    : Node("pointcloud_to_gridmap_node")
  {
    pointcloud_sub_ = this->create_subscription<sensor_msgs::msg::PointCloud2>(
      "/robot1/PointCloud2", 10,
      std::bind(&PointCloud2Subscriber::pointCloudCallback, this, std::placeholders::_1)
    );
    
    grid_map_pub_ = this->create_publisher<grid_map_msgs::msg::GridMap>("/grid_map", 10);
  }

private:
  void pointCloudCallback(const sensor_msgs::msg::PointCloud2::SharedPtr msg)
  {
    pcl::PointCloud<pcl::PointXYZ> cloud;
    pcl::fromROSMsg(*msg, cloud);

    // GridMap 생성
    grid_map::GridMap map({"elevation"});
    map.setFrameId(msg->header.frame_id);

    // 포인트 클라우드의 범위에 따라 그리드 맵의 크기 설정
    double resolution = 0.1;
    double x_min = cloud.points[0].x, x_max = cloud.points[0].x;
    double y_min = cloud.points[0].y, y_max = cloud.points[0].y;
    for (const auto& point : cloud.points) {
      if (point.x < x_min) x_min = point.x;
      if (point.x > x_max) x_max = point.x;
      if (point.y < y_min) y_min = point.y;
      if (point.y > y_max) y_max = point.y;
    }

    map.setGeometry(grid_map::Length(x_max - x_min, y_max - y_min), resolution, grid_map::Position((x_max + x_min) / 2.0, (y_max + y_min) / 2.0));

    // 포인트 클라우드 데이터를 GridMap에 추가
    for (const auto& point : cloud.points) {
      grid_map::Position position(point.x, point.y);
      if (map.isInside(position)) {
        map.atPosition("elevation", position) = point.z;
      }
    }

    // 메시지로 변환하여 퍼블리시
    auto grid_map_msg = grid_map::GridMapRosConverter::toMessage(map);
    grid_map_pub_->publish(*grid_map_msg);
  }

  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr pointcloud_sub_;
  rclcpp::Publisher<grid_map_msgs::msg::GridMap>::SharedPtr grid_map_pub_;
};

int main(int argc, char **argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<PointCloud2Subscriber>());
  rclcpp::shutdown();
  return 0;
}

