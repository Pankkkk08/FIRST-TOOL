from shared.format import human_size


def test_human_size_formatting():
    assert human_size(0) == "0 B"
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(1024 * 1024 * 3) == "3.0 MB"


def test_human_size_negative():
    assert human_size(-1536) == "-1.5 KB"
