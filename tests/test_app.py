import pytest
from fastapi.testclient import TestClient
from main import app

test_client = TestClient(app)

def test_health_endpoint():
    response = test_client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}