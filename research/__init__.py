"""
Phase 22: Research Notebooks Module

Provides Jupyter-style notebook integration for quantitative research,
strategy development, and data analysis.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
import json

logger = logging.getLogger(__name__)


class CellType(Enum):
    """Notebook cell types"""
    CODE = "code"
    MARKDOWN = "markdown"
    OUTPUT = "output"


class CellStatus(Enum):
    """Cell execution status"""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class NotebookCell:
    """Single cell in a notebook"""
    cell_id: str
    cell_type: CellType
    content: str
    output: Optional[str] = None
    status: CellStatus = CellStatus.IDLE
    execution_count: int = 0
    execution_time: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchNotebook:
    """Research notebook document"""
    notebook_id: str
    title: str
    description: str
    cells: List[NotebookCell]
    created_at: datetime
    updated_at: datetime
    author: str
    tags: List[str] = field(default_factory=list)
    is_template: bool = False
    version: int = 1


class ResearchNotebookEngine:
    """
    Research Notebook Engine
    
    Provides Jupyter-style notebook functionality for quantitative research.
    
    Features:
    - Create and manage notebooks
    - Execute code cells
    - Render markdown
    - Save and load notebooks
    - Template library
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize research notebook engine."""
        self.config = config or {}
        self.notebooks: Dict[str, ResearchNotebook] = {}
        self.templates: Dict[str, ResearchNotebook] = {}
        
        # Initialize built-in templates
        self._create_templates()
        
        logger.info("Research Notebook Engine initialized")
    
    def _create_templates(self):
        """Create built-in notebook templates."""
        # Strategy Development Template
        strategy_template = self.create_notebook(
            title="Strategy Development Template",
            description="Template for developing and testing trading strategies",
            author="system",
            is_template=True
        )
        
        self.add_cell(strategy_template.notebook_id, CellType.MARKDOWN, """
# Strategy Development Notebook

This notebook provides a structured approach to developing trading strategies.

## Contents
1. Data Loading
2. Feature Engineering
3. Strategy Logic
4. Backtesting
5. Analysis
""")
        
        self.add_cell(strategy_template.notebook_id, CellType.CODE, """
# Import required libraries
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Load market data
# data = load_market_data('XAUUSD', '1H', days=365)
print("Strategy development environment ready")
""")
        
        self.add_cell(strategy_template.notebook_id, CellType.MARKDOWN, """
## 1. Data Loading

Load historical market data for analysis.
""")
        
        self.add_cell(strategy_template.notebook_id, CellType.CODE, """
# Define strategy parameters
SYMBOL = 'XAUUSD'
TIMEFRAME = '1H'
LOOKBACK_DAYS = 365

# Sample data structure
sample_data = {
    'timestamp': pd.date_range(start='2023-01-01', periods=100, freq='h'),
    'open': np.random.uniform(1940, 1960, 100),
    'high': np.random.uniform(1950, 1970, 100),
    'low': np.random.uniform(1930, 1950, 100),
    'close': np.random.uniform(1940, 1960, 100),
    'volume': np.random.randint(1000, 10000, 100)
}
df = pd.DataFrame(sample_data)
print(f"Loaded {len(df)} bars of data")
df.head()
""")
        
        self.templates['strategy_development'] = strategy_template
        
        # Backtesting Analysis Template
        backtest_template = self.create_notebook(
            title="Backtesting Analysis Template",
            description="Analyze backtest results and performance metrics",
            author="system",
            is_template=True
        )
        
        self.add_cell(backtest_template.notebook_id, CellType.MARKDOWN, """
# Backtest Analysis Notebook

Analyze the results of a strategy backtest.

## Metrics Covered
- Returns Analysis
- Risk Metrics
- Trade Analysis
- Drawdown Analysis
""")
        
        self.add_cell(backtest_template.notebook_id, CellType.CODE, """
# Import analysis libraries
import pandas as pd
import numpy as np

# Performance metrics functions
def calculate_sharpe_ratio(returns, risk_free_rate=0.02):
    '''Calculate Sharpe Ratio'''
    excess_returns = returns - risk_free_rate/252
    return np.sqrt(252) * excess_returns.mean() / excess_returns.std()

def calculate_max_drawdown(equity_curve):
    '''Calculate Maximum Drawdown'''
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    return drawdown.min()

print("Analysis functions loaded")
""")
        
        self.templates['backtest_analysis'] = backtest_template
        
        # ML Model Development Template
        ml_template = self.create_notebook(
            title="ML Model Development Template",
            description="Develop and train machine learning models for trading",
            author="system",
            is_template=True
        )
        
        self.add_cell(ml_template.notebook_id, CellType.MARKDOWN, """
# ML Model Development Notebook

Develop machine learning models for price prediction and signal generation.

## Steps
1. Data Preparation
2. Feature Engineering
3. Model Training
4. Evaluation
5. Deployment
""")
        
        self.add_cell(ml_template.notebook_id, CellType.CODE, """
# Import ML libraries
import numpy as np
import pandas as pd

# Note: In production, you would import:
# from sklearn.ensemble import RandomForestClassifier
# from sklearn.model_selection import train_test_split
# from sklearn.metrics import accuracy_score, classification_report

print("ML development environment ready")

# Feature engineering helper
def create_features(df):
    '''Create technical features for ML model'''
    features = pd.DataFrame()
    
    # Price-based features
    features['returns'] = df['close'].pct_change()
    features['volatility'] = features['returns'].rolling(20).std()
    
    # Moving averages
    features['sma_10'] = df['close'].rolling(10).mean()
    features['sma_50'] = df['close'].rolling(50).mean()
    features['sma_ratio'] = features['sma_10'] / features['sma_50']
    
    # Volume features
    features['volume_ma'] = df['volume'].rolling(20).mean()
    features['volume_ratio'] = df['volume'] / features['volume_ma']
    
    return features.dropna()

print("Feature engineering functions ready")
""")
        
        self.templates['ml_development'] = ml_template
        
        logger.info(f"Created {len(self.templates)} notebook templates")
    
    def create_notebook(
        self,
        title: str,
        description: str,
        author: str,
        is_template: bool = False
    ) -> ResearchNotebook:
        """
        Create a new research notebook.
        
        Args:
            title: Notebook title
            description: Notebook description
            author: Author name/ID
            is_template: Whether this is a template
            
        Returns:
            New notebook object
        """
        notebook_id = f"nb_{len(self.notebooks) + 1}_{int(datetime.now().timestamp())}"
        
        notebook = ResearchNotebook(
            notebook_id=notebook_id,
            title=title,
            description=description,
            cells=[],
            created_at=datetime.now(),
            updated_at=datetime.now(),
            author=author,
            is_template=is_template
        )
        
        self.notebooks[notebook_id] = notebook
        logger.info(f"Created notebook: {title}")
        return notebook
    
    def add_cell(
        self,
        notebook_id: str,
        cell_type: CellType,
        content: str
    ) -> Optional[NotebookCell]:
        """
        Add a cell to a notebook.
        
        Args:
            notebook_id: Notebook ID
            cell_type: Type of cell
            content: Cell content
            
        Returns:
            New cell object
        """
        notebook = self.notebooks.get(notebook_id)
        if not notebook:
            logger.error(f"Notebook not found: {notebook_id}")
            return None
        
        cell_id = f"cell_{len(notebook.cells) + 1}"
        
        cell = NotebookCell(
            cell_id=cell_id,
            cell_type=cell_type,
            content=content
        )
        
        notebook.cells.append(cell)
        notebook.updated_at = datetime.now()
        
        return cell
    
    def execute_cell(
        self,
        notebook_id: str,
        cell_id: str,
        execution_context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a code cell.
        
        Args:
            notebook_id: Notebook ID
            cell_id: Cell ID
            execution_context: Optional execution context
            
        Returns:
            Execution result
        """
        notebook = self.notebooks.get(notebook_id)
        if not notebook:
            return None
        
        cell = None
        for c in notebook.cells:
            if c.cell_id == cell_id:
                cell = c
                break
        
        if not cell or cell.cell_type != CellType.CODE:
            return None
        
        cell.status = CellStatus.RUNNING
        cell.execution_count += 1
        
        start_time = datetime.now()
        
        try:
            # In production, this would use a sandboxed Python executor
            # For now, we simulate execution
            result = self._simulate_execution(cell.content)
            
            cell.output = result
            cell.status = CellStatus.COMPLETED
            cell.error_message = None
            
        except Exception as e:
            cell.status = CellStatus.ERROR
            cell.error_message = str(e)
            cell.output = None
        
        cell.execution_time = (datetime.now() - start_time).total_seconds()
        
        return {
            'cell_id': cell_id,
            'status': cell.status.value,
            'output': cell.output,
            'error': cell.error_message,
            'execution_time': cell.execution_time,
            'execution_count': cell.execution_count
        }
    
    def _simulate_execution(self, code: str) -> str:
        """Simulate code execution (placeholder for actual execution engine)."""
        # This would be replaced with actual Python execution in sandbox
        if 'print' in code:
            # Extract print statements and return simulated output
            lines = code.split('\n')
            outputs = []
            for line in lines:
                if line.strip().startswith('print('):
                    # Extract print content
                    content = line.strip()[6:-1]  # Remove print( and )
                    outputs.append(f"Output: {content}")
            return '\n'.join(outputs) if outputs else "Code executed successfully"
        return "Code executed successfully"
    
    def execute_all(self, notebook_id: str) -> List[Dict[str, Any]]:
        """Execute all cells in order."""
        notebook = self.notebooks.get(notebook_id)
        if not notebook:
            return []
        
        results = []
        for cell in notebook.cells:
            if cell.cell_type == CellType.CODE:
                result = self.execute_cell(notebook_id, cell.cell_id)
                if result:
                    results.append(result)
        
        return results
    
    def create_from_template(
        self,
        template_id: str,
        title: str,
        author: str
    ) -> Optional[ResearchNotebook]:
        """Create a notebook from a template."""
        template = self.templates.get(template_id)
        if not template:
            return None
        
        notebook = self.create_notebook(
            title=title,
            description=template.description,
            author=author
        )
        
        # Copy cells from template
        for cell in template.cells:
            self.add_cell(notebook.notebook_id, cell.cell_type, cell.content)
        
        return notebook
    
    def export_notebook(self, notebook_id: str, format: str = 'json') -> Optional[str]:
        """Export notebook to file format."""
        notebook = self.notebooks.get(notebook_id)
        if not notebook:
            return None
        
        if format == 'json':
            data = {
                'notebook_id': notebook.notebook_id,
                'title': notebook.title,
                'description': notebook.description,
                'author': notebook.author,
                'created_at': notebook.created_at.isoformat(),
                'updated_at': notebook.updated_at.isoformat(),
                'cells': [
                    {
                        'cell_id': c.cell_id,
                        'type': c.cell_type.value,
                        'content': c.content,
                        'output': c.output,
                    }
                    for c in notebook.cells
                ]
            }
            return json.dumps(data, indent=2)
        
        elif format == 'python':
            # Export as Python script
            lines = [
                f'# {notebook.title}',
                f'# {notebook.description}',
                f'# Author: {notebook.author}',
                '',
            ]
            
            for cell in notebook.cells:
                if cell.cell_type == CellType.CODE:
                    lines.append(cell.content)
                    lines.append('')
                elif cell.cell_type == CellType.MARKDOWN:
                    # Convert markdown to comments
                    for line in cell.content.split('\n'):
                        lines.append(f'# {line}')
                    lines.append('')
            
            return '\n'.join(lines)
        
        return None
    
    def get_templates(self) -> List[Dict[str, Any]]:
        """Get available templates."""
        return [
            {
                'id': tid,
                'title': t.title,
                'description': t.description,
                'cells_count': len(t.cells)
            }
            for tid, t in self.templates.items()
        ]
    
    def search_notebooks(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        author: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search notebooks."""
        results = []
        
        for nb in self.notebooks.values():
            if nb.is_template:
                continue
            
            match = True
            
            if query and query.lower() not in nb.title.lower():
                match = False
            
            if tags and not any(t in nb.tags for t in tags):
                match = False
            
            if author and nb.author != author:
                match = False
            
            if match:
                results.append({
                    'notebook_id': nb.notebook_id,
                    'title': nb.title,
                    'description': nb.description,
                    'author': nb.author,
                    'created_at': nb.created_at.isoformat(),
                    'updated_at': nb.updated_at.isoformat(),
                    'cells_count': len(nb.cells),
                    'tags': nb.tags
                })
        
        return results


def create_research_router(engine: 'ResearchNotebookEngine'):
    """
    Create a FastAPI router for the Research Notebooks module.

    Args:
        engine: ResearchNotebookEngine instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    from typing import Optional, List

    router = APIRouter(prefix="/api/research", tags=["Research"])

    class CreateNotebookRequest(BaseModel):
        title: str
        description: str
        author: str = "user"
        tags: List[str] = []

    class AddCellRequest(BaseModel):
        cell_type: str = "code"
        content: str = ""

    @router.get("/notebooks")
    async def list_notebooks(query: Optional[str] = None, author: Optional[str] = None):
        """List all research notebooks (excluding templates)."""
        return engine.search_notebooks(query=query, author=author)

    @router.post("/notebooks")
    async def create_notebook(req: CreateNotebookRequest):
        """Create a new research notebook."""
        nb = engine.create_notebook(
            title=req.title,
            description=req.description,
            author=req.author,
            tags=req.tags,
        )
        return {
            "notebook_id": nb.notebook_id,
            "title": nb.title,
            "description": nb.description,
            "author": nb.author,
            "created_at": nb.created_at.isoformat(),
        }

    @router.post("/notebooks/{notebook_id}/cells")
    async def add_cell(notebook_id: str, req: AddCellRequest):
        """Add a cell to a notebook."""
        try:
            cell_type = CellType(req.cell_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid cell_type '{req.cell_type}'")
        cell = engine.add_cell(notebook_id, cell_type, req.content)
        if not cell:
            raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
        return {"cell_id": cell.cell_id, "status": cell.status.value}

    @router.post("/notebooks/{notebook_id}/cells/{cell_id}/execute")
    async def execute_cell(notebook_id: str, cell_id: str):
        """Execute a single notebook cell."""
        result = engine.execute_cell(notebook_id, cell_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Notebook or cell not found")
        return result

    @router.post("/notebooks/{notebook_id}/execute")
    async def execute_all(notebook_id: str):
        """Execute all cells in a notebook."""
        results = engine.execute_all(notebook_id)
        return {"notebook_id": notebook_id, "results": results}

    @router.get("/notebooks/{notebook_id}/export")
    async def export_notebook(notebook_id: str, format: str = "json"):
        """Export a notebook as JSON or Python script."""
        exported = engine.export_notebook(notebook_id, format)
        if exported is None:
            raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
        return {"notebook_id": notebook_id, "format": format, "content": exported}

    @router.get("/templates")
    async def list_templates():
        """List available notebook templates."""
        return engine.get_templates()

    @router.post("/notebooks/from-template/{template_id}")
    async def create_from_template(template_id: str, req: CreateNotebookRequest):
        """Create a notebook from a template."""
        nb = engine.create_from_template(template_id, req.title, req.author)
        if nb is None:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        return {"notebook_id": nb.notebook_id, "title": nb.title}

    return router


# Module exports
__all__ = [
    'ResearchNotebookEngine',
    'ResearchNotebook',
    'NotebookCell',
    'CellType',
    'CellStatus',
    'create_research_router',
]
