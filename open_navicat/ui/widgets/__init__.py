"""UI widgets package."""

from __future__ import annotations

from open_navicat.ui.widgets.ai_copilot import AICopilotSidebar, ChatBubble
from open_navicat.ui.widgets.backup_panel import BackupPanel
from open_navicat.ui.widgets.bi_dashboard import BIDashboardWidget
from open_navicat.ui.widgets.command_line import CommandLineWidget
from open_navicat.ui.widgets.command_panel import CommandPanel
from open_navicat.ui.widgets.data_dictionary import DataDictionaryWidget
from open_navicat.ui.widgets.data_sync_panel import DataSyncPanel
from open_navicat.ui.widgets.data_transfer import DataTransferWidget
from open_navicat.ui.widgets.history_log import HistoryLogWidget
from open_navicat.ui.widgets.model_designer import ModelDesignerWidget
from open_navicat.ui.widgets.object_browser import ObjectBrowser
from open_navicat.ui.widgets.object_designer import ObjectDesignerWidget
from open_navicat.ui.widgets.query_builder import QueryBuilderWidget
from open_navicat.ui.widgets.query_manager import QueryManagerWidget
from open_navicat.ui.widgets.scheduler_panel import SchedulerPanel
from open_navicat.ui.widgets.schema_sync_panel import SchemaSyncPanel
from open_navicat.ui.widgets.server_monitor import ServerMonitorWidget
from open_navicat.ui.widgets.sql_editor import ResultTable, SQLEditorWidget
from open_navicat.ui.widgets.table_designer import TableDesignerWidget
from open_navicat.ui.widgets.table_viewer import TableViewerWidget
from open_navicat.ui.widgets.user_manager import UserManagerWidget

__all__ = [
    "ObjectBrowser",
    "SQLEditorWidget",
    "ResultTable",
    "TableViewerWidget",
    "AICopilotSidebar",
    "ChatBubble",
    "TableDesignerWidget",
    "SchemaSyncPanel",
    "BackupPanel",
    "QueryManagerWidget",
    "BIDashboardWidget",
    "ModelDesignerWidget",
    "ObjectDesignerWidget",
    "QueryBuilderWidget",
    "DataSyncPanel",
    "SchedulerPanel",
    "DataDictionaryWidget",
    "CommandPanel",
    "CommandLineWidget",
    "ServerMonitorWidget",
    "HistoryLogWidget",
    "DataTransferWidget",
]
