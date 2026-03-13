"""AVM 估值置信度规则配置。"""

CONFIDENCE_RULES = {
    "weights": {
        # 可比样本数量
        "sample_count": 0.30,
        # 距离分布（近邻质量）
        "distance_distribution": 0.30,
        # 时间跨度（时序信息充分度）
        "time_span": 0.20,
        # 关键字段完整率
        "field_completeness": 0.20,
    },
    "sample_count": {
        # 达到该样本量后记满分
        "target": 20,
        # 低于该样本量会在解释中标记为偏弱
        "weak_threshold": 6,
    },
    "distance_distribution": {
        # 用于归一化的理想均值距离（米）
        "ideal_mean_m": 600,
        # 距离惩罚的上限（米）；高于该值会显著降分
        "max_mean_m": 3000,
        # P90 距离（米）的容忍上限
        "max_p90_m": 5000,
    },
    "time_span": {
        # 数据覆盖达到该跨度（天）视为充分
        "target_days": 365,
        # 低于该跨度（天）视为不足
        "weak_days": 90,
        # 高于该跨度可能混入过旧样本，开始轻微折损
        "stale_days": 730,
    },
    "field_completeness": {
        # 低于该完整率说明关键字段质量较差
        "weak_threshold": 0.75,
    },
    # 结果文字分档
    "banding": {
        "high": 0.80,
        "medium": 0.60,
        "low": 0.40,
    },
}
