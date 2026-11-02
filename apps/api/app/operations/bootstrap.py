"""Initialize the durable stores required by a managed worker invocation."""

from apps.api.app.core.dependencies import (
    get_automation_repository,
    get_default_analysis_repository,
    get_default_monitor_repository,
    get_workspace_repository,
)


def initialize_stores() -> None:
    get_default_analysis_repository().initialize()
    get_default_monitor_repository().initialize()
    get_workspace_repository().initialize()
    get_automation_repository().initialize()
