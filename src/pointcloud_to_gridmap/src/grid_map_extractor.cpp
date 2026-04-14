#include <rclcpp/rclcpp.hpp>
#include <grid_map_ros/grid_map_ros.hpp>
#include <grid_map_msgs/msg/grid_map.hpp>
#include <tf2_ros/transform_listener.h>
#include <tf2_ros/buffer.h>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <visualization_msgs/msg/marker.hpp>
#include <Eigen/Dense>
#include <mutex>
#include <std_msgs/msg/color_rgba.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>
#include <cmath>
#include <thread>
#include <chrono>
#include <vector>

using namespace std::chrono_literals;

class GridMapExtractor : public rclcpp::Node
{
public:
    GridMapExtractor()
        : Node("grid_map_extractor"),
          tf_buffer_(this->get_clock()),
          tf_listener_(tf_buffer_)
    {
        // Parameter declaration and initialization
        this->declare_parameter<int>("front_cells", 20);
        this->declare_parameter<int>("side_cells", 40);
        this->declare_parameter<std::string>("layer", "elevation");
        this->declare_parameter<std::string>("robot_frame", "lower_frame");
        this->declare_parameter<int>("grid_map_x_offset", 0);
        this->declare_parameter<std::string>("map_frame", "map"); //  

        // Get parameters
        this->get_parameter("front_cells", front_cells_);
        this->get_parameter("side_cells", side_cells_);
        this->get_parameter("layer", layer_);
        this->get_parameter("robot_frame", robot_frame_);
        this->get_parameter("grid_map_x_offset", grid_map_x_offset);
        this->get_parameter("map_frame", map_frame_); //  

        // Subscribe to /interpolated_grid_map topic
        grid_map_sub_ = this->create_subscription<grid_map_msgs::msg::GridMap>(
            "/interpolated_grid_map",
            10,
            std::bind(&GridMapExtractor::gridMapCallback, this, std::placeholders::_1));

        // Publisher for visualization markers
        marker_pub_ = this->create_publisher<visualization_msgs::msg::MarkerArray>("extracted_grid_map", 10);

        // Publisher for extracted grid map data
        array_pub_ = this->create_publisher<std_msgs::msg::Float64MultiArray>("gridmap_state", 10);

        RCLCPP_INFO(this->get_logger(), "GridMapExtractor node has started with front_cells: %d, side_cells: %d, robot_frame: %s.",
                    front_cells_, side_cells_, robot_frame_.c_str());
    }

private:
    void gridMapCallback(const grid_map_msgs::msg::GridMap::SharedPtr msg)
    {
        std::lock_guard<std::mutex> lock(mutex_);

        // Convert to GridMap object
        grid_map::GridMap gridMap;
        grid_map::GridMapRosConverter::fromMessage(*msg, gridMap);

        // Get the robot's current position in grid_map frame
        geometry_msgs::msg::TransformStamped transformStamped;
        try
        {
            transformStamped = tf_buffer_.lookupTransform(
                msg->header.frame_id, // grid_map frame
                robot_frame_,         // Robot frame (parameterized)
                tf2::TimePointZero,
                tf2::durationFromSec(1.0)); // 1 second timeout
        }
        catch (tf2::TransformException &ex)
        {
            RCLCPP_WARN(this->get_logger(), "Could not get robot transform: %s", ex.what());
            return;
        }

        double robot_x = transformStamped.transform.translation.x;
        double robot_y = transformStamped.transform.translation.y;
        double robot_z = transformStamped.transform.translation.z; //  

        // Get the map frame position
        geometry_msgs::msg::TransformStamped mapTransformStamped; //  
        try
        {
            mapTransformStamped = tf_buffer_.lookupTransform(
                msg->header.frame_id, // grid_map frame
                map_frame_,           // Map frame (parameterized)
                tf2::TimePointZero,
                tf2::durationFromSec(1.0)); // 1 second timeout
        }
        catch (tf2::TransformException &ex)
        {
            RCLCPP_WARN(this->get_logger(), "Could not get map frame transform: %s", ex.what());
            return;
        }

        double map_z = mapTransformStamped.transform.translation.z; //  
        double z_offset = robot_z - map_z;                          //  

        // Convert robot position to grid_map index
        grid_map::Position robot_position(robot_x, robot_y);
        grid_map::Index index;
        if (!gridMap.getIndex(robot_position, index))
        {
            RCLCPP_WARN(this->get_logger(), "Robot position is out of grid map bounds.");
            return;
        }

        // Define extraction area
        int start_x = index.x() + grid_map_x_offset;
        int start_y = index.y() - (side_cells_ / 2);
        int extract_size_x = front_cells_ * 2;
        int extract_size_y = side_cells_;

        // Clamp extraction area within map bounds
        int map_width = static_cast<int>(gridMap.getSize()(0));
        int map_height = static_cast<int>(gridMap.getSize()(1));

        int end_x = std::min(start_x + extract_size_x, map_width - 1);
        int end_y = std::min(start_y + extract_size_y, map_height - 1);
        start_x = std::max(start_x, 0);
        start_y = std::max(start_y, 0);

        // Initialize extracted grid map
        grid_map::GridMap extractedMap;
        extractedMap.setFrameId(gridMap.getFrameId());
        grid_map::Length extract_length((end_x - start_x - 1) * gridMap.getResolution(),
                                        (end_y - start_y) * gridMap.getResolution());
        grid_map::Position extract_center(
            robot_position.x() - grid_map_x_offset * gridMap.getResolution(),
            robot_position.y());
        extractedMap.setGeometry(extract_length, gridMap.getResolution(), extract_center);
        extractedMap.add(layer_);

        // Copy values from the original map to the extracted map
        std::vector<double> array_data; // For storing extracted values
        for (int x = start_x; x <= end_x; ++x)
        {
            for (int y = start_y; y <= end_y; ++y)
            {
                grid_map::Index current_index(x, y);
                grid_map::Position pos;
                gridMap.getPosition(current_index, pos);

                if (gridMap.isInside(pos))
                {
                    grid_map::Index extracted_index;
                    if (extractedMap.getIndex(pos, extracted_index))
                    {
                        float value = gridMap.at(layer_, current_index); 
                        extractedMap.at(layer_, extracted_index) = std::isfinite(value) ? value : 0.0;
                        array_data.push_back(extractedMap.at(layer_, extracted_index) - z_offset);
                    }
                }
            }
        }

        // Publish extracted grid map data as Float64MultiArray
        std_msgs::msg::Float64MultiArray array_msg;
        array_msg.data = array_data;
        array_pub_->publish(array_msg);
        // RCLCPP_INFO(this->get_logger(), "Publishing extracted grid map data: [size=%zu]", array_msg.data.size());

        // Create MarkerArray for visualization
        visualization_msgs::msg::MarkerArray marker_array;
        visualization_msgs::msg::Marker marker;
        marker.header.frame_id = extractedMap.getFrameId();
        marker.header.stamp = this->get_clock()->now();
        marker.ns = "extracted_grid_map";
        marker.id = 0;
        marker.type = visualization_msgs::msg::Marker::CUBE_LIST;
        marker.action = visualization_msgs::msg::Marker::ADD;
        marker.scale.x = gridMap.getResolution();
        marker.scale.y = gridMap.getResolution();
        marker.scale.z = 0.1;
        marker.color.a = 0.8;

        // Populate marker points and colors based on extracted grid map values
        for (grid_map::GridMapIterator it(extractedMap); !it.isPastEnd(); ++it)
        {
            grid_map::Position pos;
            extractedMap.getPosition(*it, pos);
            float value = extractedMap.at(layer_, *it);

            if (!std::isfinite(value) || value == 0.0)
            {
                continue;
            }

            geometry_msgs::msg::Point p;
            p.x = pos.x();
            p.y = pos.y();
            p.z = value;

            marker.points.push_back(p);

            std_msgs::msg::ColorRGBA color;
            color.a = 0.8;
            color.r = value > 0.5 ? 1.0 : 0.0;
            color.g = value <= 0.5 ? 1.0 : 0.0;
            color.b = 0.0;
            marker.colors.push_back(color);
        }

        // If no valid points were found, add a log message
        if (marker.points.empty())
        {
            RCLCPP_WARN(this->get_logger(), "No valid points found in the extracted grid map for visualization.");
        }
        else
        {
            marker_array.markers.push_back(marker);
            marker_pub_->publish(marker_array);
        }
    }

    // ROS2 Subscriber and Publisher
    rclcpp::Subscription<grid_map_msgs::msg::GridMap>::SharedPtr grid_map_sub_;
    rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr marker_pub_;
    rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr array_pub_;

    // TF2 listener
    tf2_ros::Buffer tf_buffer_;
    tf2_ros::TransformListener tf_listener_;

    // Extraction parameters
    int front_cells_;
    int side_cells_;
    std::string layer_;
    std::string robot_frame_;
    std::string map_frame_; //  
    int grid_map_x_offset;

    // Mutex for thread safety
    std::mutex mutex_;
};

int main(int argc, char **argv)
{
    rclcpp::init(argc, argv);
    auto node = std::make_shared<GridMapExtractor>();
    rclcpp::spin(node);
    rclcpp::shutdown();
    return 0;
}