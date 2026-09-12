"""Stable A2UI protocol identifiers shared by resources and tools."""

A2UI_VERSION = "v0.9.1"
A2UI_SDK_VERSION = "0.9.1"
A2UI_MIME_TYPE = "application/a2ui+json"
A2UI_BASIC_CATALOG = "https://a2ui.org/specification/v0_9_1/catalogs/basic/catalog.json"

A2UI_URI_NAMESPACE = "a2ui://database"
DATABASE_OVERVIEW_SURFACE_ID = "database-overview"
DATABASE_OVERVIEW_RESOURCE_URI = f"{A2UI_URI_NAMESPACE}/overview"
DATABASE_OVERVIEW_DATA_URI = f"{DATABASE_OVERVIEW_RESOURCE_URI}/data"
REFRESH_DATABASE_OVERVIEW_ACTION = "refresh_database_overview"
REFRESH_DATABASE_OVERVIEW_COMPONENT_ID = "refresh_button"

DATABASE_OVERVIEW_DEFAULT_LIMIT = 50
