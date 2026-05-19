from app.services.crawl_request_service import should_run_crawl


def test_should_run_crawl_requires_payload_and_request_id():
    assert should_run_crawl(None, None) is False
    assert should_run_crawl({}, None) is False
    assert should_run_crawl({"website": "https://example.com"}, None) is False


def test_should_run_crawl_true_for_new_request_id():
    assert should_run_crawl({"request_id": "abc"}, None) is True
    assert should_run_crawl({"request_id": "abc"}, "xyz") is True


def test_should_run_crawl_false_for_already_processed_request_id():
    assert should_run_crawl({"request_id": "abc"}, "abc") is False
