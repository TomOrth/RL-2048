from fastapi.testclient import TestClient

from app.main import create_app


def test_invalid_model_settings_do_not_echo_credentials():
    with TestClient(create_app()) as client:
        game_id = client.post('/api/games', json={}).json()['state']['id']
        result = client.put(f'/api/games/{game_id}/llm/settings', json={
            'url': 'http://localhost:8001/v1',
            'api_key': 'test-secret-should-never-be-echoed',
        })
        assert result.status_code == 422
        assert result.json()['error']['code'] == 'invalid_request'
        assert 'model' in result.json()['error']['message']
        assert 'test-secret' not in result.text
