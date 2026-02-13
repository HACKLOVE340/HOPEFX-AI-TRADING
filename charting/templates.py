"""
Chart Template Management
"""

from typing import Dict, Any
from datetime import datetime


class ChartTemplate:
    """Chart template"""
    def __init__(self, name: str, description: str):
        self.template_id = f"TPL_{name}_{datetime.utcnow().timestamp()}"
        self.name = name
        self.description = description
        self.config = {}
        self.created_at = datetime.utcnow()


class TemplateManager:
    """Manages chart templates"""
    
    def __init__(self):
        self.templates: Dict[str, ChartTemplate] = {}
    
    def save_template(
        self,
        name: str,
        description: str,
        config: Dict[str, Any]
    ) -> ChartTemplate:
        """Save a chart template"""
        template = ChartTemplate(name, description)
        template.config = config
        
        self.templates[template.template_id] = template
        return template
    
    def load_template(self, template_id: str) -> ChartTemplate:
        """Load a template"""
        return self.templates.get(template_id)
    
    def list_templates(self) -> list:
        """List all templates"""
        return list(self.templates.values())
