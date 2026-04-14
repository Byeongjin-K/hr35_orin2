/*

#include <rclcpp/rclcpp.hpp>
#include <grid_map_ros/grid_map_ros.hpp>
#include <grid_map_msgs/msg/grid_map.hpp>
#include <cmath>
#include <memory>
#include <utility>
#include <sensor_msgs/msg/point_cloud2.hpp> // PointCloud2 메시지 타입
#include <sensor_msgs/point_cloud2_iterator.hpp>
#include <tf2_ros/transform_listener.h>
#include <tf2_ros/buffer.h>
#include <tf2_sensor_msgs/tf2_sensor_msgs.hpp>

class GridMapNode : public rclcpp::Node
{
public:
  GridMapNode()
  : Node("pointcloud_to_gridmap"), map_({"elevation"}), tf_buffer_(this->get_clock()), tf_listener_(tf_buffer_)
  {
    // Publisher 초기화
    publisher_ = this->create_publisher<grid_map_msgs::msg::GridMap>("grid_map", rclcpp::QoS(1).transient_local());


    // Subscriber 초기화
    subscription_ = this->create_subscription<sensor_msgs::msg::PointCloud2>("/PointCloud2", 10, std::bind(&GridMapNode::pointCloudCallback, this, std::placeholders::_1));

    // 그리드 맵 초기화
    map_.setFrameId("map");
 //   map_.setGeometry(grid_map::Length(60, 30), 0.3);
    map_.setGeometry(grid_map::Length(50, 50), 0.5);

private:
  void pointCloudCallback(const sensor_msgs::msg::PointCloud2::SharedPtr msg)
  {
    rclcpp::Time time = this->now();  
    // 점군 변환
    sensor_msgs::msg::PointCloud2 transformed_msg;
    try {
      tf_buffer_.transform(*msg, transformed_msg, "map", tf2::durationFromSec(1.0));
    } catch (tf2::TransformException &ex) {
      RCLCPP_WARN(this->get_logger(), "Could not transform point cloud: %s", ex.what());
      return;
    }   
    // 변환 점군으로 그리드 맵 작성
    for (sensor_msgs::PointCloud2ConstIterator<float> iter_x(transformed_msg, "x"), iter_y(transformed_msg, "y"), iter_z(transformed_msg, "z");
         iter_x != iter_x.end();
         ++iter_x, ++iter_y, ++iter_z)
    {    
      grid_map::Position position(*iter_x, *iter_y); // 점의 위치 가져오기

      if (map_.isInside(position)) // 그리드 맵 범위 내에 있는지 확인
      {
        //if (*iter_z < -10.2)
        {
        map_.atPosition("elevation", position) = *iter_z; // 그리드 맵의 해당 위치에 고도 값 업데이트
        }  
      }
    }      


    // 그리드 맵 발행
    map_.setTimestamp(time.nanoseconds());
    std::unique_ptr<grid_map_msgs::msg::GridMap> message;
    message = grid_map::GridMapRosConverter::toMessage(map_);
    //message->header.frame_id = "robot1/Boom_frame";
    publisher_->publish(std::move(message));
    RCLCPP_INFO(this->get_logger(), "Grid map published.");

  grid_map::GridMap map_;
  rclcpp::Publisher<grid_map_msgs::msg::GridMap>::SharedPtr publisher_;
  rclcpp::Publisher<grid_map_msgs::msg::GridMap>::SharedPtr interpolated_publisher_; // 추가된 퍼블리셔
  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr subscription_;
  tf2_ros::Buffer tf_buffer_;
  tf2_ros::TransformListener tf_listener_;

};

int main(int argc, char ** argv)
{
  // ROS 2 초기화 및 노드 실행
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<GridMapNode>());
  rclcpp::shutdown();
  return 0;
}


*/

#include <rclcpp/rclcpp.hpp>
#include <grid_map_ros/grid_map_ros.hpp>
#include <grid_map_msgs/msg/grid_map.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <sensor_msgs/point_cloud2_iterator.hpp>
#include <tf2_ros/transform_listener.h>
#include <tf2_ros/buffer.h>
#include <tf2_sensor_msgs/tf2_sensor_msgs.hpp>
#include <grid_map_cv/grid_map_cv.hpp>
#include <vector>
#include <cmath>
#include <limits>

class GridMapNode : public rclcpp::Node
{
public:
  GridMapNode()
      : Node("pointcloud_to_gridmap"), map_({"elevation"}), interpolated_map_({"elevation"}), tf_buffer_(this->get_clock()), tf_listener_(tf_buffer_)
  {
    // 파라미터 선언 및 초기화
    this->declare_parameter<std::string>("pointcloud_topic", "/ouster/points");
    this->declare_parameter<double>("resolution", 0.5);
    this->declare_parameter<double>("length_x", 100.0);
    this->declare_parameter<double>("length_y", 100.0);
    this->declare_parameter<std::string>("frame_id", "map");

    // 파라미터 가져오기
    this->get_parameter("pointcloud_topic", pointcloud_topic_);
    this->get_parameter("resolution", resolution_);
    this->get_parameter("length_x", length_x_);
    this->get_parameter("length_y", length_y_);
    this->get_parameter("frame_id", frame_id_);

    // 퍼블리셔 설정
    publisher_ = this->create_publisher<grid_map_msgs::msg::GridMap>("grid_map", rclcpp::QoS(1).transient_local());
    interpolated_publisher_ = this->create_publisher<grid_map_msgs::msg::GridMap>("interpolated_grid_map", rclcpp::QoS(1).transient_local());

    // 구독자 설정
    subscription_ = this->create_subscription<sensor_msgs::msg::PointCloud2>(
        pointcloud_topic_, 10, std::bind(&GridMapNode::pointCloudCallback, this, std::placeholders::_1));

    // 그리드 맵 초기화
    grid_map::Length length(length_x_, length_y_);
    map_.setFrameId(frame_id_);
    map_.setGeometry(length, resolution_);

    interpolated_map_.setFrameId(frame_id_);
    interpolated_map_.setGeometry(length, resolution_);

    // 로그 메시지 추가
    RCLCPP_INFO(this->get_logger(), "GridMap node has been started with resolution: %.2f m and size: %.2f x %.2f m.", resolution_, length_x_, length_y_);
  }

private:
  void pointCloudCallback(const sensor_msgs::msg::PointCloud2::SharedPtr msg)
  {
    rclcpp::Time time = this->now();
    sensor_msgs::msg::PointCloud2 transformed_msg;
    try
    {
      tf_buffer_.transform(*msg, transformed_msg, frame_id_, tf2::durationFromSec(1.0));
    }
    catch (tf2::TransformException &ex)
    {
      RCLCPP_WARN(this->get_logger(), "Could not transform point cloud: %s", ex.what());
      return;
    }

    // 포인트 클라우드를 그리드 맵에 추가
    for (sensor_msgs::PointCloud2ConstIterator<float> iter_x(transformed_msg, "x"), iter_y(transformed_msg, "y"), iter_z(transformed_msg, "z");
         iter_x != iter_x.end();
         ++iter_x, ++iter_y, ++iter_z)
    {
      grid_map::Position position(*iter_x, *iter_y);
      if (map_.isInside(position))
      {
        // 특정 조건에 따라 elevation 업데이트 (필요 시 주석 해제)
        // if (*iter_z < -10.2)
        {
          map_.atPosition("elevation", position) = *iter_z;
        }
      }
    }

    // 타임스탬프 설정 및 퍼블리시
    map_.setTimestamp(time.nanoseconds());
    auto message = grid_map::GridMapRosConverter::toMessage(map_);
    publisher_->publish(std::move(message));

    // 인터폴레이션 수행 및 퍼블리시
    interpolateGridMap();
    auto interpolated_message = grid_map::GridMapRosConverter::toMessage(interpolated_map_);
    interpolated_publisher_->publish(std::move(interpolated_message));
  }

  void interpolateGridMap()
  {
    const std::string layer = "elevation";
    interpolated_map_.clearAll();
    interpolated_map_.setGeometry(map_.getLength(), resolution_, map_.getPosition());

    for (grid_map::GridMapIterator iterator(interpolated_map_); !iterator.isPastEnd(); ++iterator)
    {
      const grid_map::Index index(*iterator);
      grid_map::Position pos;
      interpolated_map_.getPosition(index, pos);

      if (map_.isInside(pos) && !std::isnan(map_.atPosition(layer, pos)))
      {
        interpolated_map_.at(layer, index) = map_.atPosition(layer, pos);
      }
      else
      {
        interpolated_map_.at(layer, index) = interpolateIDW(pos);
      }
    }
  }

  double interpolateIDW(const grid_map::Position &position)
  {
    const std::string layer = "elevation";
    double sum_weights = 0.0;
    double sum_values = 0.0;
    const double power = 2.0;         // IDW 파라미터
    const double search_radius = 3.0; // 이웃 검색 반경

    for (grid_map::CircleIterator iterator(map_, position, search_radius); !iterator.isPastEnd(); ++iterator)
    {
      const grid_map::Index index(*iterator);
      grid_map::Position neighbor_pos;
      map_.getPosition(index, neighbor_pos);
      if (!std::isnan(map_.at(layer, index)))
      {
        double distance = (neighbor_pos - position).norm();
        if (distance > 0.0)
        {
          double weight = 1.0 / std::pow(distance, power);
          sum_weights += weight;
          sum_values += weight * map_.at(layer, index);
        }
      }
    }

    if (sum_weights > 0.0)
    {
      return sum_values / sum_weights;
    }
    else
    {
      return std::numeric_limits<double>::quiet_NaN(); // 유효한 이웃 없음
    }
  }

  // 파라미터 변수
  std::string pointcloud_topic_;
  double resolution_;
  double length_x_;
  double length_y_;
  std::string frame_id_;

  // 그리드 맵 변수
  grid_map::GridMap map_;
  grid_map::GridMap interpolated_map_;

  // 퍼블리셔 및 구독자
  rclcpp::Publisher<grid_map_msgs::msg::GridMap>::SharedPtr publisher_;
  rclcpp::Publisher<grid_map_msgs::msg::GridMap>::SharedPtr interpolated_publisher_;
  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr subscription_;

  // TF 변환 관련
  tf2_ros::Buffer tf_buffer_;
  tf2_ros::TransformListener tf_listener_;
};

int main(int argc, char **argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<GridMapNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
