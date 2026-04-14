#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <grid_map_ros/grid_map_ros.hpp>
#include <grid_map_msgs/msg/grid_map.hpp>
#include <sensor_msgs/point_cloud2_iterator.hpp>
#include <Eigen/Dense>

using namespace std::chrono_literals;

class PointCloudToGridMap : public rclcpp::Node
{
public:
    PointCloudToGridMap()
    : Node("pointcloud_to_gridmap")
    {
        subscription_ = this->create_subscription<sensor_msgs::msg::PointCloud2>(
            "/robot1/PointCloud2", 10,
            std::bind(&PointCloudToGridMap::pointcloud_callback, this, std::placeholders::_1));
        publisher_ = this->create_publisher<grid_map_msgs::msg::GridMap>("/grid_map", 10);
    }

private:
    void pointcloud_callback(const sensor_msgs::msg::PointCloud2::SharedPtr msg)
    {
        grid_map::GridMap map({"elevation"});
        map.setFrameId("map");
        map.setGeometry(grid_map::Length(10.0, 10.0), 0.1);

        // Ensure the data type of the grid map is double
        map.add("elevation", 0.0);

        sensor_msgs::PointCloud2ConstIterator<float> iter_x(*msg, "x");
        sensor_msgs::PointCloud2ConstIterator<float> iter_y(*msg, "y");
        sensor_msgs::PointCloud2ConstIterator<float> iter_z(*msg, "z");

        for (; iter_x != iter_x.end(); ++iter_x, ++iter_y, ++iter_z)
        {
            grid_map::Position position(*iter_x, *iter_y);
            if (map.isInside(position))
            {
                map.at("elevation", position) = static_cast<double>(*iter_z);
            }
        }

        std::vector<std::string> layers = {"elevation"};
        auto grid_map_msg = grid_map::GridMapRosConverter::toMessage(map, layers);
        publisher_->publish(*grid_map_msg);
    }

    rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr subscription_;
    rclcpp::Publisher<grid_map_msgs::msg::GridMap>::SharedPtr publisher_;
};

int main(int argc, char **argv)
{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<PointCloudToGridMap>());
    rclcpp::shutdown();
    return 0;
}

