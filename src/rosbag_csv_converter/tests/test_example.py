def test_pytest_works():
    assert True


def test_addition():
    assert 1 + 1 == 2


def test_string_operations():
    result = "rosbag_csv_converter"
    assert "csv" in result
    assert result.startswith("rosbag")
