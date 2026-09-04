from __future__ import annotations

import json

from src.collection.adapters.generic_product import GenericProductAdapter
from src.collection.adapters.taobao_judicial import TaobaoJudicialAuctionAdapter
from src.collection.seed_list_parser import (
    GenericJsonSeedListParser,
    TaobaoSeedListParser,
)
from tools import seed_collector


def test_generic_parser_extracts_nested_json_and_preserves_source_fields() -> None:
    payload = {
        "data": {
            "items": [
                {
                    "sku": "sku-7",
                    "name": "Reusable product",
                    "detail_url": "/products/sku-7",
                    "inventory": 12,
                }
            ]
        }
    }

    result = GenericJsonSeedListParser().parse(
        json.dumps(payload),
        final_url="https://catalog.example/list?page=1",
    )

    assert result.has_challenge is False
    assert result.summary["parsed_item_count"] == 1
    assert result.items == (
        {
            "sku": "sku-7",
            "name": "Reusable product",
            "detail_url": "/products/sku-7",
            "inventory": 12,
            "id": "sku-7",
            "source_item_id": "sku-7",
            "url": "https://catalog.example/products/sku-7",
            "source_url": "https://catalog.example/products/sku-7",
            "title": "Reusable product",
            "source_title": "Reusable product",
        },
    )


def test_generic_parser_handles_json_ld_rejections_and_long_ids() -> None:
    long_id = "external-" + ("x" * 80)
    html = """
    <script type="application/ld+json">
      {"@graph": [
        {"@type": "Organization", "name": "Catalog"},
        {"@type": "Product", "@id": "%s", "url": "//catalog.example/p/1", "name": "One"},
        {"id": "unsafe", "url": "javascript:alert(1)"}
      ]}
    </script>
    """ % long_id

    result = GenericJsonSeedListParser().parse(html, final_url="https://catalog.example/list")

    assert len(result.items) == 1
    item = result.items[0]
    assert item["source_item_id"].startswith("sha256:")
    assert len(item["source_item_id"]) == 63
    assert item["raw_source_item_id"] == long_id
    assert item["source_url"] == "https://catalog.example/p/1"
    assert result.summary["rejected_item_count"] == 0


def test_generic_parser_skips_empty_containers_and_hashes_url_only_product() -> None:
    html = """
    <script id="__NeXt_DaTa__">
      {"items": [{"not_a_product": true}], "products": [{"url": "/products/no-id"}]}
    </script>
    """

    result = GenericJsonSeedListParser().parse(html, final_url="https://catalog.example/list")

    assert len(result.items) == 1
    assert result.items[0]["source_item_id"].startswith("url:")
    assert result.items[0]["source_url"] == "https://catalog.example/products/no-id"


def test_generic_parser_skips_an_empty_json_script_before_product_data() -> None:
    html = """
    <script type="application/json">[]</script>
    <script type="application/json">[{"id": "sku-9", "url": "/products/sku-9"}]</script>
    """

    result = GenericJsonSeedListParser().parse(html, final_url="https://catalog.example/list")

    assert [item["source_item_id"] for item in result.items] == ["sku-9"]


def test_generic_parser_reports_login_or_captcha_challenges() -> None:
    result = GenericJsonSeedListParser().parse(
        "<html><body>Sign in to continue. CAPTCHA required.</body></html>",
        final_url="https://catalog.example/login",
    )

    assert result.items == ()
    assert result.has_challenge is True
    assert result.summary["body_has_login"] is True
    assert result.summary["body_has_captcha"] is True


def test_taobao_parser_retains_legacy_probe_contract() -> None:
    class Probe:
        def summarize_list_page(self, html: str, *, final_url: str):
            assert html == "legacy-html"
            assert final_url == "https://sf.taobao.com/list"
            return {"item_count": 1}

        def extract_list_payload(self, html: str):
            assert html == "legacy-html"
            return {"legacy": True}

        def build_userscript_like_batch_payload(self, payload, *, source_page_url: str):
            assert payload == {"legacy": True}
            return {"items": [{"id": "1001", "url": source_page_url + "/1001"}]}

    parser = TaobaoSeedListParser(Probe())
    items, summary, challenged = seed_collector._extract_seed_items(
        parser,
        "legacy-html",
        final_url="https://sf.taobao.com/list",
    )

    assert items == [{"id": "1001", "url": "https://sf.taobao.com/list/1001"}]
    assert summary == {"item_count": 1}
    assert challenged is False


def test_collection_adapters_select_source_specific_list_parsers() -> None:
    probe = object()

    generic = GenericProductAdapter(source_platform="catalog_x").create_seed_list_parser(probe)
    taobao = TaobaoJudicialAuctionAdapter().create_seed_list_parser(probe)

    assert type(generic) is GenericJsonSeedListParser
    assert isinstance(taobao, TaobaoSeedListParser)
    assert taobao.probe is probe
