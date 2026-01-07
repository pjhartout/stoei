# Stoei Architecture

## Overview

Stoei is a Terminal User Interface (TUI) application for monitoring SLURM jobs. It is built using the [Textual](https://textual.textualize.io/) framework and provides real-time monitoring of jobs, nodes, and users on a SLURM cluster.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface                            │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    SlurmMonitor (App)                       ││
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐           ││
│  │  │ Jobs    │ │ Nodes   │ │ Users   │ │ Logs    │  Tabs     ││
│  │  │ Tab     │ │ Tab     │ │ Tab     │ │ Tab     │           ││
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘           ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │                 Cluster Sidebar                          │││
│  │  │  - Node stats  - CPU usage  - GPU usage  - Memory       │││
│  │  └─────────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         SLURM Layer                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  Commands   │  │   Parser    │  │  Formatters │             │
│  │  (commands) │  │   (parser)  │  │ (formatters)│             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │    Cache    │  │ Validation  │  │ GPU Parser  │             │
│  │   (cache)   │  │(validation) │  │(gpu_parser) │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SLURM Commands (External)                     │
│        squeue    scontrol    sacct    scancel                   │
└─────────────────────────────────────────────────────────────────┘
```

## Component Details

### User Interface Layer

#### SlurmMonitor (`app.py`)
The main Textual application class. Responsibilities:
- Compose the UI layout with tabs and sidebar
- Handle keybindings and user input
- Coordinate data refresh via background workers
- Manage tab switching and content updates

#### Widgets (`widgets/`)
Reusable UI components:

| Widget | File | Description |
|--------|------|-------------|
| TabContainer | `tabs.py` | Tab navigation component |
| ClusterSidebar | `cluster_sidebar.py` | Cluster statistics display |
| NodeOverviewTab | `node_overview.py` | Node-level resource overview |
| UserOverviewTab | `user_overview.py` | User-level resource aggregation |
| LogPane | `log_pane.py` | Application log display |
| HelpScreen | `help_screen.py` | Keybinding reference modal |

#### Modal Screens (`screens.py`)
Full-screen dialogs:
- `JobInputScreen` - Job ID input dialog
- `JobInfoScreen` - Job details display
- `LogViewerScreen` - Log file viewer with search
- `CancelConfirmScreen` - Job cancellation confirmation
- `NodeInfoScreen` - Node details display

### SLURM Layer

#### Commands (`slurm/commands.py`)
Executes SLURM CLI commands with error handling and retry logic:
- `get_running_jobs()` - Current user's jobs from `squeue`
- `get_job_history()` - Historical jobs from `sacct`
- `get_job_info()` - Detailed job info from `scontrol`/`sacct`
- `get_cluster_nodes()` - Node info from `scontrol`
- `cancel_job()` - Job cancellation via `scancel`

#### Parser (`slurm/parser.py`)
Parses raw SLURM command output:
- `parse_squeue_output()` - Parse squeue tabular output
- `parse_sacct_output()` - Parse sacct accounting data
- `parse_scontrol_output()` - Parse scontrol key=value format

#### Formatters (`slurm/formatters.py`)
Format parsed data for display:
- `format_job_info()` - Format job details for display
- `format_node_info()` - Format node details for display

#### GPU Parser (`slurm/gpu_parser.py`)
Specialized GPU information parsing (shared module):
- `parse_gpu_entries()` - Parse GPU from TRES strings
- `parse_gpu_from_gres()` - Parse GPU from Gres strings
- `aggregate_gpu_counts()` - Aggregate GPU counts by type

#### Cache (`slurm/cache.py`)
Job data caching and state management:
- Caches job data to reduce SLURM calls
- Tracks job state changes
- Categorizes job states (running, pending, completed, etc.)

#### Validation (`slurm/validation.py`)
Input validation utilities:
- `validate_job_id()` - Validate job ID format
- `resolve_executable()` - Find SLURM executables in PATH
- `check_slurm_available()` - Verify SLURM is accessible

## Data Flow

### Refresh Cycle

```
1. Timer triggers refresh (every 5 seconds)
         │
         ▼
2. Background worker starts (_refresh_data_async)
         │
         ├── JobCache.refresh() ──► squeue
         ├── get_cluster_nodes() ──► scontrol show nodes
         └── get_all_users_jobs() ──► squeue -a
         │
         ▼
3. Worker calls UI update on main thread
         │
         ├── Update jobs table
         ├── Update cluster sidebar stats
         └── Update active tab content
```

### Job Info Lookup

```
User presses Enter or 'i'
         │
         ▼
JobInputScreen (if 'i')
         │
         ▼
get_job_info(job_id)
         │
         ├── Try scontrol (for active jobs)
         │   └── Parse and format output
         │
         └── Fallback to sacct (for completed jobs)
             └── Parse accounting data
         │
         ▼
JobInfoScreen displays formatted info
```

## Styling

### CSS Files (`styles/`)

| File | Purpose |
|------|---------|
| `app.tcss` | Main application styles |
| `modals.tcss` | Modal/screen-specific styles |
| `theme.py` | Color theme definitions |

## Extension Points

### Adding a New Tab

1. Create widget in `widgets/`
2. Add CSS in `styles/`
3. Register in `app.py` compose method
4. Add keybinding for switching

### Adding SLURM Data Source

1. Add command function in `slurm/commands.py`
2. Add parser in `slurm/parser.py`
3. Add formatter in `slurm/formatters.py`
4. Update cache if needed

### Adding a Modal Screen

1. Create screen class in `widgets/screens.py`
2. Add CSS in `styles/modals.tcss`
3. Add action method in `app.py` to push screen

## Performance Considerations

- **Background Workers**: SLURM commands run in background threads to avoid blocking UI
- **Job Caching**: Reduces redundant SLURM queries
- **Retry Logic**: Handles transient failures with exponential backoff
- **File Truncation**: Large log files are truncated to 512KB for performance
- **Responsive Layout**: UI adapts to terminal size
