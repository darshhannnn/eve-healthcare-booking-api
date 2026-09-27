"""Centres, tests catalogue, offerings and admin-only management rules."""


def test_admin_can_create_centre(client):
    from tests.helpers import admin_user

    admin = admin_user(client)
    resp = client.post(
        "/centres", headers=admin.headers,
        json={"name": "EVE Diagnostics", "location": "Bengaluru"},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "EVE Diagnostics"


def test_non_admin_cannot_create_centre(client):
    from tests.helpers import make_user

    user = make_user(client)
    resp = client.post(
        "/centres", headers=user.headers,
        json={"name": "Sneaky Centre", "location": "Nowhere"},
    )
    assert resp.status_code == 403


def test_anonymous_cannot_create_centre(client):
    resp = client.post("/centres", json={"name": "X", "location": "Y"})
    assert resp.status_code == 401


def test_list_centres_public_and_paginated(client):
    from tests.helpers import admin_user, create_centre

    admin = admin_user(client)
    for _ in range(3):
        create_centre(client, admin.headers)

    resp = client.get("/centres", params={"page": 1, "page_size": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["pages"] == 2
    assert body["page"] == 1

    resp2 = client.get("/centres", params={"page": 2, "page_size": 2})
    assert len(resp2.json()["items"]) == 1


def test_list_centres_search(client):
    from tests.helpers import admin_user, create_centre

    admin = admin_user(client)
    create_centre(client, admin.headers, name="City Lab", location="Mumbai")
    create_centre(client, admin.headers, name="Town Lab", location="Delhi")

    resp = client.get("/centres", params={"search": "mumbai"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["location"] == "Mumbai"


def test_centre_detail_includes_offerings_with_prices(client):
    from tests.helpers import admin_user, make_centre_with_test

    admin = admin_user(client)
    data = make_centre_with_test(client, admin.headers, price="499.50")
    resp = client.get(f"/centres/{data['centre']['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["offerings"]) == 1
    assert body["offerings"][0]["price"] == "499.50"
    assert body["offerings"][0]["test"]["code"] == data["test"]["code"]


def test_centre_detail_unknown_404(client):
    assert client.get("/centres/99999").status_code == 404


def test_create_test_requires_admin(client):
    from tests.helpers import make_user

    user = make_user(client)
    assert (
        client.post("/tests", headers=user.headers, json={"code": "X1", "name": "X"}).status_code
        == 403
    )


def test_create_test_and_duplicate_code_conflict(client):
    from tests.helpers import admin_user

    admin = admin_user(client)
    resp = client.post("/tests", headers=admin.headers, json={"code": "cbc", "name": "CBC Test"})
    assert resp.status_code == 201
    assert resp.json()["code"] == "CBC"  # normalised to upper case

    dup = client.post("/tests", headers=admin.headers, json={"code": "CBC", "name": "Other"})
    assert dup.status_code == 409


def test_duplicate_offering_conflict(client):
    from tests.helpers import admin_user, create_centre, create_test, add_offering

    admin = admin_user(client)
    test = create_test(client, admin.headers)
    centre = create_centre(client, admin.headers)
    assert add_offering(client, admin.headers, centre["id"], test["id"])
    resp = client.post(
        f"/centres/{centre['id']}/offerings", headers=admin.headers,
        json={"test_id": test["id"], "price": "100.00"},
    )
    assert resp.status_code == 409


def test_offering_unknown_test_404(client):
    from tests.helpers import admin_user, create_centre

    admin = admin_user(client)
    centre = create_centre(client, admin.headers)
    resp = client.post(
        f"/centres/{centre['id']}/offerings", headers=admin.headers,
        json={"test_id": 99999, "price": "100.00"},
    )
    assert resp.status_code == 404


def test_offering_invalid_price_422(client):
    from tests.helpers import admin_user, create_centre, create_test

    admin = admin_user(client)
    test = create_test(client, admin.headers)
    centre = create_centre(client, admin.headers)
    resp = client.post(
        f"/centres/{centre['id']}/offerings", headers=admin.headers,
        json={"test_id": test["id"], "price": "-5.00"},
    )
    assert resp.status_code == 422


def test_update_and_remove_offering(client):
    from tests.helpers import admin_user, make_centre_with_test

    admin = admin_user(client)
    data = make_centre_with_test(client, admin.headers)
    centre_id, test_id = data["centre"]["id"], data["test"]["id"]

    resp = client.patch(
        f"/centres/{centre_id}/offerings/{test_id}", headers=admin.headers,
        json={"price": "750.00"},
    )
    assert resp.status_code == 200 and resp.json()["price"] == "750.00"

    resp = client.delete(f"/centres/{centre_id}/offerings/{test_id}", headers=admin.headers)
    assert resp.status_code == 204
    assert client.get(f"/centres/{centre_id}").json()["offerings"] == []


def test_patch_centre(client):
    from tests.helpers import admin_user, create_centre

    admin = admin_user(client)
    centre = create_centre(client, admin.headers)
    resp = client.patch(
        f"/centres/{centre['id']}", headers=admin.headers, json={"location": "Pune"}
    )
    assert resp.status_code == 200 and resp.json()["location"] == "Pune"


def test_list_tests_public(client):
    from tests.helpers import admin_user, create_test

    admin = admin_user(client)
    create_test(client, admin.headers, name="Blood Panel A")
    resp = client.get("/tests")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
