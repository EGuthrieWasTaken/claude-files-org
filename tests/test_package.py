import claude_files_org


def test_package_metadata():
    assert claude_files_org.__version__ == "0.1.1"
    assert claude_files_org.REQUIRES_API == 1
    assert callable(claude_files_org.register)
