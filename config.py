import os
from dotenv import load_dotenv, find_dotenv
import sys

load_dotenv(find_dotenv())

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

BASE_WORKFLOW_LOGS_DIR = os.path.join(PROJECT_ROOT, "workflow_logs")
BASE_PROJECT_WORKSPACE_DIR = os.path.join(PROJECT_ROOT, "project_workspace")

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
TEMP_ATTACHMENT_DIR = os.path.join(PROJECT_ROOT, "temp_discord_attachments")

LLM_MODEL = "gemini-1.5-flash"

MCP_CONNECTIONS = {
    "search": {
        "connection_type": "stdio",
        "command": "python",
        # args: [script_path, (appends) workflow_log_file_path]
        "args": [os.path.join(PROJECT_ROOT, "tools", "search_mcp.py")]
    },
    "filesystem": {
        "connection_type": "stdio",
        "command": "python",
        # args: [script_path, (appends) workspace_path, workflow_log_file_path]
        "args": [os.path.join(PROJECT_ROOT, "tools", "file_system_mcp.py")]
    },
    "logging": {
        "connection_type": "stdio",
        "command": "python",
        "args": [os.path.join(PROJECT_ROOT, "tools", "logging_mcp.py")]
    }
}

# Task queue priority settings (lower number = higher priority)
PRIORITY_NEW_TASK = 10
PRIORITY_CONTINUATION_TASK = 5

def ensure_directories():
    """Ensures essential directories exist."""
    dirs_to_create = [
        BASE_PROJECT_WORKSPACE_DIR,
        BASE_WORKFLOW_LOGS_DIR,
        TEMP_ATTACHMENT_DIR
    ]
    for dir_path in dirs_to_create:
        if not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
                print(f"Config: Created directory '{dir_path}'.")
            except OSError as e:
                print(f"Warning: Failed to create directory '{dir_path}': {e}", file=sys.stderr)

ensure_directories()

def check_tool_scripts():
    """Checks if MCP tool scripts exist."""
    all_scripts_found = True
    for server_name, conn_config in MCP_CONNECTIONS.items():
        if conn_config["connection_type"] == "stdio":
            script_path = conn_config["args"][0] if conn_config.get("args") else None
            if not script_path or not os.path.exists(script_path):
                print(f"Warning: MCP tool script '{script_path}' (Server: {server_name}) not found.", file=sys.stderr)
                all_scripts_found = False
    return all_scripts_found