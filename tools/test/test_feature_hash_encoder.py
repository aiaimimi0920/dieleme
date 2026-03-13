import pandas as pd

from tools.feature_hash_encoder import encode_categorical_features


def test_encode_categorical_features_with_unk_and_missing_markers():
    df = pd.DataFrame(
        {
            "community_name": ["汤臣一品", None],
            "city": ["上海市", ""],
            "district": ["浦东新区", "  "],
            "housing_type": [None, "住宅"],
            "floor_level": ["高区", None],
        }
    )

    encoded = encode_categorical_features(df)

    # UNK normalization
    assert encoded.loc[1, "community_name"] == "UNK"
    assert encoded.loc[1, "city"] == "UNK"
    assert encoded.loc[1, "district"] == "UNK"
    assert encoded.loc[0, "housing_type"] == "UNK"
    assert encoded.loc[1, "floor_level"] == "UNK"

    # explicit missing indicators
    assert encoded.loc[1, "community_name_is_missing"] == 1
    assert encoded.loc[1, "city_is_missing"] == 1
    assert encoded.loc[1, "district_is_missing"] == 1
    assert encoded.loc[0, "housing_type_is_missing"] == 1
    assert encoded.loc[1, "floor_level_is_missing"] == 1

    # stable same-value hashing
    unk_hashes = {
        encoded.loc[1, "community_name_hash"],
        encoded.loc[1, "city_hash"],
        encoded.loc[1, "district_hash"],
        encoded.loc[0, "housing_type_hash"],
        encoded.loc[1, "floor_level_hash"],
    }
    assert len(unk_hashes) == 1
