from app.main import create_app
from app.version import __version__


def test_openapi_exposes_semantic_service_version() -> None:
    openapi = create_app().openapi()

    assert openapi["info"]["version"] == __version__
