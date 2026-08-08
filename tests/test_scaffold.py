def test_tools_importable() -> None:
    """Scaffold guard: the tools package must import cleanly."""
    import tools  # noqa: F401
