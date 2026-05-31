from src.llm_helper import extract_property_coordinates


def test_extract_property_coordinates_from_center_array():
    html = """
    <script>
      var center = [121.50123, 31.24567];
    </script>
    """

    result = extract_property_coordinates(html)

    assert result is not None
    assert result["longitude"] == 121.50123
    assert result["latitude"] == 31.24567


def test_extract_property_coordinates_from_named_fields():
    html = """
    <script>
      window.__MAP__ = {
        "longitude": 121.61234,
        "latitude": 31.19876
      };
    </script>
    """

    result = extract_property_coordinates(html)

    assert result is not None
    assert result["longitude"] == 121.61234
    assert result["latitude"] == 31.19876


def test_extract_property_coordinates_from_center_string():
    html = """
    <script>
      var pageData = { center: "121.50088,31.24066" };
    </script>
    """

    result = extract_property_coordinates(html)

    assert result is not None
    assert result["longitude"] == 121.50088
    assert result["latitude"] == 31.24066


def test_extract_property_coordinates_from_amap_lnglat_constructor():
    html = """
    <script>
      var marker = new AMap.LngLat(121.70012, 31.11034);
    </script>
    """

    result = extract_property_coordinates(html)

    assert result is not None
    assert result["longitude"] == 121.70012
    assert result["latitude"] == 31.11034
