"""Versioned, exact-answer collection extraction qualification (not a judge LLM)."""

VERSION = "collection-exact-v1"
INSTRUCTION = (
    "Extract only facts stated in the source. Return compact JSON, with exactly "
    "these keys in this order: price_yuan,area_sqm,sold. Use numbers (no trailing "
    "decimal zeros), true/false for an explicit sale result, and null for missing "
    "facts. Convert 万元 to yuan. A starting price is not a sale price. "
    "No markdown, explanation, or additional keys. Source:\n"
)
CASES = (
    ("成交价：125万元；建筑面积：89.5平方米；已成交。",
     '{"price_yuan":1250000,"area_sqm":89.5,"sold":true}'),
    ("起拍价：80万元；建筑面积：60平方米；流拍，未成交。",
     '{"price_yuan":null,"area_sqm":60,"sold":false}'),
    ("成交价：986000元；已成交。页面没有提供建筑面积。",
     '{"price_yuan":986000,"area_sqm":null,"sold":true}'),
    ("建筑面积：102平方米；即将开始拍卖。起拍价：100万元。",
     '{"price_yuan":null,"area_sqm":102,"sold":null}'),
    ("市场评估价：300万元；成交价：218.6万元；建筑面积：120.25平方米；已成交。",
     '{"price_yuan":2186000,"area_sqm":120.25,"sold":true}'),
)


def exact_match(answer, expected):
    # Only transport-level outer whitespace is ignored; no fuzzy/LLM grading.
    return isinstance(answer, str) and answer.strip() == expected
