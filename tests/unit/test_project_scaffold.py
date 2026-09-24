"""Minimal infrastructure test — verifies the installable package structure."""


def test_genesis_cognitive_package_is_importable() -> None:
    import genesis_cognitive

    assert genesis_cognitive.__name__ == "genesis_cognitive"
