import pytest
import tempfile
import os
import csv
from pathlib import Path

from ros2_bag_gui.export.sync_generator import (
    SyncGenerator,
    SyncGeneratorConfig,
    SyncGeneratorResult
)


class TestSyncGenerator:
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    @pytest.fixture
    def generator(self):
        return SyncGenerator()
    
    def test_generate_with_only_pointcloud_files(self, generator, temp_dir):
        pc_dir = os.path.join(temp_dir, 'pointclouds')
        os.makedirs(pc_dir)
        
        timestamps = [1733824508854518630, 1733824508954518630, 1733824509054518630]
        for ts in timestamps:
            Path(os.path.join(pc_dir, f'{ts}.laz')).touch()
        
        output_path = os.path.join(temp_dir, 'timestamps.csv')
        config = SyncGeneratorConfig(
            output_path=output_path,
            pointcloud_dir=pc_dir
        )
        
        result = generator.generate(config)
        
        assert result.success
        assert result.row_count == 3
        assert os.path.exists(output_path)
        
        with open(output_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            assert len(rows) == 3
            assert rows[0]['timestamp_ns'] == str(timestamps[0])
            assert rows[0]['pointcloud_file'] == f'{timestamps[0]}.laz'
            assert rows[0]['image_left'] == ''
            assert rows[0]['image_right'] == ''
            assert rows[0]['image_depth'] == ''
    
    def test_generate_with_only_image_files(self, generator, temp_dir):
        left_dir = os.path.join(temp_dir, 'left')
        right_dir = os.path.join(temp_dir, 'right')
        os.makedirs(left_dir)
        os.makedirs(right_dir)
        
        timestamps = [1733824508854518630, 1733824508954518630]
        for ts in timestamps:
            Path(os.path.join(left_dir, f'{ts}.jpg')).touch()
            Path(os.path.join(right_dir, f'{ts}.jpg')).touch()
        
        output_path = os.path.join(temp_dir, 'timestamps.csv')
        config = SyncGeneratorConfig(
            output_path=output_path,
            image_dirs={
                'camera_left': left_dir,
                'camera_right': right_dir
            }
        )
        
        result = generator.generate(config)
        
        assert result.success
        assert result.row_count == 2
        
        with open(output_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            assert len(rows) == 2
            assert rows[0]['pointcloud_file'] == ''
            assert rows[0]['image_left'] == f'{timestamps[0]}.jpg'
            assert rows[0]['image_right'] == f'{timestamps[0]}.jpg'
    
    def test_generate_with_both_sources(self, generator, temp_dir):
        pc_dir = os.path.join(temp_dir, 'pointclouds')
        left_dir = os.path.join(temp_dir, 'left')
        depth_dir = os.path.join(temp_dir, 'depth')
        os.makedirs(pc_dir)
        os.makedirs(left_dir)
        os.makedirs(depth_dir)
        
        pc_timestamps = [1733824508854518630, 1733824509254518630]
        img_timestamps = [1733824508854518630, 1733824509004518630]
        
        for ts in pc_timestamps:
            Path(os.path.join(pc_dir, f'{ts}.laz')).touch()
        
        for ts in img_timestamps:
            Path(os.path.join(left_dir, f'{ts}.jpg')).touch()
            Path(os.path.join(depth_dir, f'{ts}_depth.png')).touch()
        
        output_path = os.path.join(temp_dir, 'timestamps.csv')
        config = SyncGeneratorConfig(
            output_path=output_path,
            pointcloud_dir=pc_dir,
            image_dirs={
                'camera_left': left_dir,
                'camera_depth': depth_dir
            }
        )
        
        result = generator.generate(config)
        
        assert result.success
        assert result.row_count == 3
        
        with open(output_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            assert len(rows) == 3
            assert rows[0]['pointcloud_file'] == f'{pc_timestamps[0]}.laz'
            assert rows[0]['image_left'] == f'{img_timestamps[0]}.jpg'
            assert rows[0]['image_depth'] == f'{img_timestamps[0]}_depth.png'
            
            assert rows[1]['pointcloud_file'] == ''
            assert rows[1]['image_left'] == f'{img_timestamps[1]}.jpg'
            
            assert rows[2]['pointcloud_file'] == f'{pc_timestamps[1]}.laz'
    
    def test_collect_timestamps_from_laz_filenames(self, generator, temp_dir):
        pc_dir = os.path.join(temp_dir, 'pointclouds')
        os.makedirs(pc_dir)
        
        timestamps = [1733824508854518630, 1733824508954518630, 1733824509054518630]
        for ts in timestamps:
            Path(os.path.join(pc_dir, f'{ts}.laz')).touch()
        
        Path(os.path.join(pc_dir, 'invalid.laz')).touch()
        
        result = generator.collect_timestamps(pointcloud_dir=pc_dir)
        
        assert result == sorted(timestamps)
    
    def test_collect_timestamps_from_image_filenames(self, generator, temp_dir):
        img_dir = os.path.join(temp_dir, 'images')
        os.makedirs(img_dir)
        
        timestamps = [1733824508854518630, 1733824508954518630]
        for ts in timestamps:
            Path(os.path.join(img_dir, f'{ts}.jpg')).touch()
        
        Path(os.path.join(img_dir, 'invalid.jpg')).touch()
        
        result = generator.collect_timestamps(image_dirs={'camera': img_dir})
        
        assert result == sorted(timestamps)
    
    def test_collect_timestamps_with_depth_suffix(self, generator, temp_dir):
        depth_dir = os.path.join(temp_dir, 'depth')
        os.makedirs(depth_dir)
        
        timestamps = [1733824508854518630, 1733824508954518630]
        for ts in timestamps:
            Path(os.path.join(depth_dir, f'{ts}_depth.png')).touch()
        
        result = generator.collect_timestamps(image_dirs={'depth': depth_dir})
        
        assert result == sorted(timestamps)
    
    def test_find_closest_file_within_tolerance(self, generator):
        file_timestamps = [
            ('1733824508854518630.laz', 1733824508854518630),
            ('1733824508954518630.laz', 1733824508954518630),
        ]
        
        target_ts = 1733824508854518630
        result = generator.find_closest_file(target_ts, file_timestamps)
        
        assert result == '1733824508854518630.laz'
    
    def test_find_closest_file_outside_tolerance(self, generator):
        file_timestamps = [
            ('1733824508854518630.laz', 1733824508854518630),
        ]
        
        target_ts = 1733824509854518630
        result = generator.find_closest_file(target_ts, file_timestamps, max_delta_ns=100_000_000)
        
        assert result == ''
    
    def test_find_closest_file_empty_list(self, generator):
        result = generator.find_closest_file(1733824508854518630, [])
        
        assert result == ''
    
    def test_ns_to_datetime_local_formatting(self, generator):
        timestamp_ns = 1733824508854518630
        result = generator.ns_to_datetime_local(timestamp_ns)
        
        assert len(result) == 23
        assert result[4] == '-'
        assert result[7] == '-'
        assert result[10] == ' '
        assert result[13] == ':'
        assert result[16] == ':'
        assert result[19] == '.'
    
    def test_time_range_filtering(self, generator, temp_dir):
        pc_dir = os.path.join(temp_dir, 'pointclouds')
        os.makedirs(pc_dir)
        
        timestamps = [1733824508854518630, 1733824508954518630, 1733824509054518630]
        for ts in timestamps:
            Path(os.path.join(pc_dir, f'{ts}.laz')).touch()
        
        output_path = os.path.join(temp_dir, 'timestamps.csv')
        config = SyncGeneratorConfig(
            output_path=output_path,
            pointcloud_dir=pc_dir,
            start_time_ns=1733824508900000000,
            end_time_ns=1733824509000000000
        )
        
        result = generator.generate(config)
        
        assert result.success
        assert result.row_count == 1
        
        with open(output_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            assert len(rows) == 1
            assert rows[0]['timestamp_ns'] == str(timestamps[1])
    
    def test_empty_sources(self, generator, temp_dir):
        output_path = os.path.join(temp_dir, 'timestamps.csv')
        config = SyncGeneratorConfig(output_path=output_path)
        
        result = generator.generate(config)
        
        assert result.success
        assert result.row_count == 0
        
        with open(output_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            assert len(rows) == 0
    
    def test_csv_loadable_with_pandas(self, generator, temp_dir):
        pytest.importorskip('pandas')
        import pandas as pd
        
        pc_dir = os.path.join(temp_dir, 'pointclouds')
        os.makedirs(pc_dir)
        
        timestamps = [1733824508854518630, 1733824508954518630]
        for ts in timestamps:
            Path(os.path.join(pc_dir, f'{ts}.laz')).touch()
        
        output_path = os.path.join(temp_dir, 'timestamps.csv')
        config = SyncGeneratorConfig(
            output_path=output_path,
            pointcloud_dir=pc_dir
        )
        
        result = generator.generate(config)
        assert result.success
        
        df = pd.read_csv(output_path)
        
        assert len(df) == 2
        assert 'timestamp_ns' in df.columns
        assert 'datetime_local' in df.columns
        assert 'pointcloud_file' in df.columns
        assert 'image_left' in df.columns
        assert 'image_right' in df.columns
        assert 'image_depth' in df.columns
    
    def test_column_order_matches_schema(self, generator, temp_dir):
        output_path = os.path.join(temp_dir, 'timestamps.csv')
        config = SyncGeneratorConfig(output_path=output_path)
        
        result = generator.generate(config)
        assert result.success
        
        with open(output_path, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            
            expected_columns = [
                'timestamp_ns',
                'datetime_local',
                'pointcloud_file',
                'image_left',
                'image_right',
                'image_depth'
            ]
            
            assert header == expected_columns
    
    def test_nonexistent_directories_handled(self, generator, temp_dir):
        output_path = os.path.join(temp_dir, 'timestamps.csv')
        config = SyncGeneratorConfig(
            output_path=output_path,
            pointcloud_dir='/nonexistent/path',
            image_dirs={'camera': '/another/nonexistent/path'}
        )
        
        result = generator.generate(config)
        
        assert result.success
        assert result.row_count == 0
    
    def test_mixed_file_extensions(self, generator, temp_dir):
        img_dir = os.path.join(temp_dir, 'images')
        os.makedirs(img_dir)
        
        Path(os.path.join(img_dir, '1733824508854518630.jpg')).touch()
        Path(os.path.join(img_dir, '1733824508954518630.png')).touch()
        Path(os.path.join(img_dir, '1733824509054518630.jpeg')).touch()
        
        result = generator.collect_timestamps(image_dirs={'camera': img_dir})
        
        assert len(result) == 3
    
    def test_image_topic_name_mapping(self, generator, temp_dir):
        left_dir = os.path.join(temp_dir, 'left')
        right_dir = os.path.join(temp_dir, 'right')
        depth_dir = os.path.join(temp_dir, 'depth')
        os.makedirs(left_dir)
        os.makedirs(right_dir)
        os.makedirs(depth_dir)
        
        ts = 1733824508854518630
        Path(os.path.join(left_dir, f'{ts}.jpg')).touch()
        Path(os.path.join(right_dir, f'{ts}.jpg')).touch()
        Path(os.path.join(depth_dir, f'{ts}_depth.png')).touch()
        
        output_path = os.path.join(temp_dir, 'timestamps.csv')
        config = SyncGeneratorConfig(
            output_path=output_path,
            image_dirs={
                '/zed/zed_node/left/image_rect_color': left_dir,
                '/zed/zed_node/right/image_rect_color': right_dir,
                '/zed/zed_node/depth/depth_registered': depth_dir
            }
        )
        
        result = generator.generate(config)
        assert result.success
        
        with open(output_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            assert rows[0]['image_left'] == f'{ts}.jpg'
            assert rows[0]['image_right'] == f'{ts}.jpg'
            assert rows[0]['image_depth'] == f'{ts}_depth.png'
    
    def test_output_directory_created(self, generator, temp_dir):
        output_path = os.path.join(temp_dir, 'subdir', 'nested', 'timestamps.csv')
        config = SyncGeneratorConfig(output_path=output_path)
        
        result = generator.generate(config)
        
        assert result.success
        assert os.path.exists(output_path)
    
    def test_error_handling(self, generator):
        config = SyncGeneratorConfig(output_path='/invalid/path/timestamps.csv')
        
        result = generator.generate(config)
        
        assert not result.success
        assert result.error is not None
        assert result.row_count == 0
    
    def test_closest_file_matching_exact(self, generator):
        file_timestamps = [
            ('1733824508854518630.laz', 1733824508854518630),
            ('1733824508954518630.laz', 1733824508954518630),
        ]
        
        target_ts = 1733824508854518630
        result = generator.find_closest_file(target_ts, file_timestamps)
        
        assert result == '1733824508854518630.laz'
    
    def test_closest_file_matching_near(self, generator):
        file_timestamps = [
            ('1733824508854518630.laz', 1733824508854518630),
            ('1733824508954518630.laz', 1733824508954518630),
        ]
        
        target_ts = 1733824508854518640
        result = generator.find_closest_file(target_ts, file_timestamps, max_delta_ns=100)
        
        assert result == '1733824508854518630.laz'
    
    def test_timestamps_sorted(self, generator, temp_dir):
        pc_dir = os.path.join(temp_dir, 'pointclouds')
        os.makedirs(pc_dir)
        
        timestamps = [1733824509054518630, 1733824508854518630, 1733824508954518630]
        for ts in timestamps:
            Path(os.path.join(pc_dir, f'{ts}.laz')).touch()
        
        result = generator.collect_timestamps(pointcloud_dir=pc_dir)
        
        assert result == sorted(timestamps)
    
    def test_duplicate_timestamps_deduplicated(self, generator, temp_dir):
        pc_dir = os.path.join(temp_dir, 'pointclouds')
        img_dir = os.path.join(temp_dir, 'images')
        os.makedirs(pc_dir)
        os.makedirs(img_dir)
        
        ts = 1733824508854518630
        Path(os.path.join(pc_dir, f'{ts}.laz')).touch()
        Path(os.path.join(img_dir, f'{ts}.jpg')).touch()
        
        result = generator.collect_timestamps(
            pointcloud_dir=pc_dir,
            image_dirs={'camera': img_dir}
        )
        
        assert result == [ts]
