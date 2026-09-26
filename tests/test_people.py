import json

import pytest
from fastapi.testclient import TestClient

from hermes import store
from hermes.web import identity

ME = identity.User("me@example.com", "Vithyea Test", True)
FRIEND = {"Tailscale-User-Login": "Friend@Example.com", "Tailscale-User-Name": "Sam Reader"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LIBRARY", tmp_path)
    monkeypatch.setattr(identity, "owner", lambda: ME)
    monkeypatch.setattr(identity, "LOCAL_CLIENTS", {"testclient"})  # TestClient's address
    from hermes.web import app as web

    monkeypatch.setattr(web, "mac_owner", lambda: ME)
    for slug, owner in [("atomic-habits", None), ("iron-flame", "friend@example.com")]:
        d = tmp_path / slug
        d.mkdir()
        (d / "chapters.json").write_text("[]")
        meta = {"title": slug.replace("-", " ").title()}
        if owner:
            meta["owner"] = owner
        (d / "meta.json").write_text(json.dumps(meta))
    return TestClient(web.app)


def test_each_person_sees_only_their_books(client):
    mine = client.get("/").text
    assert "Atomic Habits" in mine and "Iron Flame" not in mine and "Vithyea's library" in mine
    hers = client.get("/", headers=FRIEND).text
    assert "Iron Flame" in hers and "Atomic Habits" not in hers and "Sam's library" in hers


def test_other_peoples_books_are_hidden(client):
    assert client.get("/book/iron-flame").status_code == 404
    assert client.get("/book/atomic-habits/cast", headers=FRIEND).status_code == 404
    assert client.get("/book/iron-flame/progress", headers=FRIEND).status_code == 200


def test_new_books_belong_to_whoever_made_them(client):
    r = client.post("/scan/new", data={"title": "Atomic Habits"}, headers=FRIEND, follow_redirects=False)
    slug = r.headers["location"].split("/")[2]
    assert slug == "atomic-habits-2"  # same title as mine, but a separate book
    assert json.loads((store.LIBRARY / slug / "meta.json").read_text())["owner"] == "friend@example.com"
    assert client.get(f"/book/{slug}").status_code == 404


def test_identity_headers_only_trusted_from_tailscale_on_this_mac(client, monkeypatch):
    monkeypatch.setattr(identity, "LOCAL_CLIENTS", set())  # request not from this Mac
    assert client.get("/whoami", headers=FRIEND).json()["login"] == "me@example.com"


def test_proxied_request_without_name_never_gets_the_owners_library(client, monkeypatch):
    monkeypatch.setattr(identity, "whois", lambda ip: ("friend@example.com", "Sam Reader"))
    assert client.get("/whoami", headers={"X-Forwarded-For": "100.64.0.9"}).json()["login"] == "friend@example.com"
    monkeypatch.setattr(identity, "whois", lambda ip: (None, ""))
    r = client.get("/", headers={"X-Forwarded-For": "100.64.0.9"}).text
    assert "Atomic Habits" not in r and "Guest's library" in r


def test_only_the_owner_can_delete_a_book(client):
    assert client.post("/book/iron-flame/delete", follow_redirects=False).status_code == 404
    assert (store.LIBRARY / "iron-flame").exists()
    assert client.post("/book/iron-flame/delete", headers=FRIEND, follow_redirects=False).status_code == 303
    assert not (store.LIBRARY / "iron-flame").exists()
