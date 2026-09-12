"""Stable A2UI protocol identifiers shared by resources and tools."""

A2UI_VERSION = "v0.9.1"
A2UI_SDK_VERSION = "0.9.1"
A2UI_MIME_TYPE = "application/a2ui+json"
A2UI_BASIC_CATALOG = "https://a2ui.org/specification/v0_9_1/catalogs/basic/catalog.json"
A2UI_FINANCE_CATALOG = "https://fluidbank.app/a2ui/catalogs/finance/v1"

A2UI_URI_NAMESPACE = "a2ui://database"
DATABASE_OVERVIEW_SURFACE_ID = "database-overview"
DATABASE_OVERVIEW_RESOURCE_URI = f"{A2UI_URI_NAMESPACE}/overview"
DATABASE_OVERVIEW_DATA_URI = f"{DATABASE_OVERVIEW_RESOURCE_URI}/data"
REFRESH_DATABASE_OVERVIEW_ACTION = "refresh_database_overview"
REFRESH_DATABASE_OVERVIEW_COMPONENT_ID = "refresh_button"

DATABASE_OVERVIEW_DEFAULT_LIMIT = 50

DATA_CHART_SURFACE_ID = "data-chart"
DATA_CHART_RESOURCE_URI = "a2ui://finance/data-chart"
DATA_CHART_DATA_URI = f"{DATA_CHART_RESOURCE_URI}/data"
DATA_CHART_DEFAULT_LIMIT = 100
DATA_CHART_MAX_LIMIT = 500

CHAT_MESSAGE_SURFACE_ID = "chat-message"
CHAT_MESSAGE_RESOURCE_URI = "a2ui://chat/message"
CHAT_MESSAGE_DATA_URI = f"{CHAT_MESSAGE_RESOURCE_URI}/data"
CHAT_MESSAGE_MAX_LENGTH = 4_000
