"""
Tests for the component status utilities module.
"""

import pytest

from utils.component_status import (
    ComponentStatus,
    ComponentHealth,
    get_framework_version,
    get_component_status,
    get_all_component_statuses,
)


class TestComponentStatus:
    """Tests for ComponentStatus utilities."""
    
    def test_get_framework_version(self):
        """Test that framework version is returned."""
        version = get_framework_version()
        assert version == '1.0.0'
    
    def test_component_status_dataclass(self):
        """Test ComponentStatus dataclass creation."""
        status = ComponentStatus(
            name='test',
            available=True,
            version='1.0.0',
            health=ComponentHealth.HEALTHY,
            features=['feature1', 'feature2']
        )
        
        assert status.name == 'test'
        assert status.available is True
        assert status.version == '1.0.0'
        assert status.health == ComponentHealth.HEALTHY
        assert len(status.features) == 2
    
    def test_component_status_to_dict(self):
        """Test ComponentStatus to_dict method."""
        status = ComponentStatus(
            name='test',
            available=True,
            version='1.0.0',
            health=ComponentHealth.HEALTHY,
        )
        
        result = status.to_dict()
        
        assert isinstance(result, dict)
        assert result['name'] == 'test'
        assert result['available'] is True
        assert result['version'] == '1.0.0'
        assert result['health'] == 'healthy'
    
    def test_get_component_status_config(self):
        """Test getting config component status."""
        status = get_component_status('config')
        
        assert status.name == 'config'
        assert status.available is True
        assert status.version == '1.0.0'
        assert status.health == ComponentHealth.HEALTHY
    
    def test_get_component_status_strategies(self):
        """Test getting strategies component status."""
        status = get_component_status('strategies')
        
        assert status.name == 'strategies'
        assert status.available is True
        assert status.version == '1.0.0'
    
    def test_get_component_status_unknown(self):
        """Test getting unknown component status."""
        status = get_component_status('unknown_component')
        
        assert status.name == 'unknown_component'
        assert status.available is False
        assert status.health == ComponentHealth.UNKNOWN
        assert 'Unknown component' in status.error
    
    def test_get_all_component_statuses(self):
        """Test getting all component statuses."""
        statuses = get_all_component_statuses()
        
        assert isinstance(statuses, dict)
        assert 'config' in statuses
        assert 'strategies' in statuses
        assert 'brokers' in statuses
        assert 'risk' in statuses
        
        # Check that available components have correct status
        assert statuses['config'].available is True
        assert statuses['strategies'].available is True
    
    def test_component_health_enum(self):
        """Test ComponentHealth enum values."""
        assert ComponentHealth.HEALTHY.value == 'healthy'
        assert ComponentHealth.DEGRADED.value == 'degraded'
        assert ComponentHealth.UNAVAILABLE.value == 'unavailable'
        assert ComponentHealth.UNKNOWN.value == 'unknown'
