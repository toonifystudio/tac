from rental_app.web import app


def test_ui_index_served():
    client = app.test_client()
    rv = client.get('/')
    assert rv.status_code == 200
    assert b'TAC' in rv.data
