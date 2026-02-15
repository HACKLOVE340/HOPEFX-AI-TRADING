"""
Utilities Module

This module provides shared utilities for the HOPEFX AI Trading framework.

Components:
- Component status checking and version reporting
- Common helper functions
- System health utilities
"""

from .component_status import (
    ComponentStatus,
    get_component_status,
    get_all_component_statuses,
    get_framework_version,
)

__all__ = [
    'ComponentStatus',
    'get_component_status',
    'get_all_component_statuses',
    'get_framework_version',
]

__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
