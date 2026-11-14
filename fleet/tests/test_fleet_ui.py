"""`fleet ui`: the JSON endpoints, the static page and the server's limits, against temp stores and a fake ssh."""
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from fleet_testkit import fleet, world  # noqa: F401
from test_fleet_machines import duo
from test_fleet_messaging import thread_id


@pytest.fixture
def server(world):
    srv = fleet.make_ui_server(port=0, ttl=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def get(path, raw=False, headers=None):
        world.here_env()
        h = {"Authorization": "Bearer " + srv.fleet_token}
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        try:
            r = urllib.request.urlopen(urllib.request.Request(base + path, headers=h), timeout=20)
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        body = r.read()
        return r.status, body if raw else json.loads(body)
    get.srv, get.base = srv, base
    yield get
    srv.shutdown()
    srv.server_close()


def test_members_endpoint_shape_across_machines(world, server):
    a, b, bee = duo(world, extra={"gone": {"ssh": "no-such-host", "fleet": "/x/fleet.py"}})
    code, data = server("/api/members")
    assert code == 200
    rows = {m["name"]: m for m in data["members"]}
    assert set(rows) == {"alpha", "beta"}
    assert set(rows["alpha"]) == {"name", "session_id", "host", "cwd", "branch", "status", "respawn", "machine", "joined_at"}
    assert (rows["alpha"]["machine"], rows["beta"]["machine"]) == ("here", "bee")
    assert data["home"] == os.path.expanduser("~")  # the page shortens this machine's folders to ~
    assert rows["alpha"]["status"] == "alive" and rows["alpha"]["session_id"] == a.sid
    assert data["notices"] == [{"machine": "gone", "text":
        "machine gone: unreachable (ssh: connect to host no-such-host port 22: Operation timed out)"}]


def test_members_show_dead_and_left_ones_too(world, server):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    world.run(b, "leave")
    a.die()
    code, data = server("/api/members")
    assert {m["name"]: m["status"] for m in data["members"]} == {"alpha": "dead", "beta": "left"}
    assert {m["machine"] for m in data["members"]} == {fleet.self_machine()}


def test_todos_endpoint_merges_every_machine(world, server):
    a, b, bee = duo(world)
    assert world.run(a, "todo", "add", "first", "--ref", "T-1")[0] == 0
    assert world.run(b, "todo", "add", "second")[0] == 0
    world.run(b, "todo", "claim", "1")
    code, data = server("/api/todos")
    assert code == 200 and data["machine"] == "here" and data["notices"] == []
    got = sorted((t["machine"], t["title"], t["state"], t["claimed_by"], t["ref"]) for t in data["todos"])
    assert got == [("bee", "second", "claimed", "beta", None), ("here", "first", "open", None, "T-1")]
    assert {"id", "title", "ref", "notes", "created_by", "state", "claimed_by", "reserved_for", "machine"} <= set(data["todos"][0])


def test_threads_endpoint_shows_a_cross_machine_ask_once_with_its_answer(world, server):
    a, b, bee = duo(world)
    _, out, _ = world.run(a, "ask", "beta@bee", "what is up")
    th = thread_id(out)
    bid = [r["id"] for r in bee.db().execute("SELECT id FROM messages WHERE kind='ask'")][0]
    assert world.run(b, "answer", str(bid), "nothing much")[0] == 0
    code, data = server("/api/threads")
    assert code == 200 and data["notices"] == []
    assert [t["thread"] for t in data["threads"]] == [th]
    t = data["threads"][0]
    assert [(m["kind"], m["body"]) for m in t["messages"]] == [("ask", "what is up"), ("answer", "nothing much")]
    assert t["open"] == 0


def test_a_waiting_ask_counts_as_open_and_threads_are_newest_first(world, server):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    t1 = thread_id(world.run(a, "ask", "beta", "one")[1])
    t2 = thread_id(world.run(a, "tell", "beta", "two")[1])
    data = server("/api/threads")[1]
    assert [t["thread"] for t in data["threads"]] == [t2, t1]
    assert [t["open"] for t in data["threads"]] == [1, 1]
    mid = data["threads"][1]["messages"][0]["id"]
    assert world.run(b, "answer", str(mid), "done")[0] == 0
    data = server("/api/threads")[1]
    assert {t["thread"]: t["open"] for t in data["threads"]} == {t1: 0, t2: 1}


def test_threads_notice_for_an_unreachable_machine_and_local_threads_still_show(world, server):
    a, b, bee = duo(world, extra={"gone": {"ssh": "no-such-host", "fleet": "/x/fleet.py"}})
    th = thread_id(world.run(a, "tell", "beta@bee", "hi")[1])
    data = server("/api/threads")[1]
    assert [t["thread"] for t in data["threads"]] == [th]
    assert [n["machine"] for n in data["notices"]] == ["gone"]


def test_merge_threads_is_the_union_of_two_stores_without_twins():
    row = dict(thread="t1", kind="ask", sender="a", recipient="b@m2", body="q", in_reply_to=None,
               created_at=5.0, answered_at=None)
    s1 = [{"thread": "t1", "messages": [dict(row, id=1, machine="m2", remote_id=7)]}]
    s2 = [{"thread": "t1", "messages": [dict(row, id=7, sender="a@m1", recipient="b", machine="m1", remote_id=1,
                                              answered_at=9.0)]}]
    out = fleet.merge_threads({"m1": s1, "m2": s2}, 10)
    assert len(out) == 1 and len(out[0]["messages"]) == 1 and out[0]["open"] == 0
    assert out[0]["messages"][0]["store"] == "m1"


def test_the_page_and_its_files_are_served_and_nothing_else(server):
    code, body = server("/", raw=True)
    assert code == 200 and b"<title>Fleet</title>" in body and b'data-view="fleet"' in body
    assert server("/app.js", raw=True)[0] == 200 and server("/app.css", raw=True)[0] == 200
    assert server("/../fleet.py", raw=True)[0] == 404
    assert server("/%2e%2e/fleet.py", raw=True)[0] == 404
    assert server("/nope.html", raw=True)[0] == 404


def test_the_server_takes_its_port_from_ui_json_and_binds_loopback(world):
    import os
    assert fleet.ui_settings() == (8797, "127.0.0.1")
    os.makedirs(world.here.home, exist_ok=True)
    json.dump({"port": 8123}, open(os.path.join(world.here.home, "ui.json"), "w"))
    assert fleet.ui_settings() == (8123, "127.0.0.1")
    assert fleet.ui_settings(9000, "0.0.0.0") == (9000, "0.0.0.0")


def test_the_page_never_uses_innerhtml_or_an_external_script():
    import os
    d = os.path.join(os.path.dirname(fleet.__file__), "ui")
    for name in os.listdir(d):
        text = open(os.path.join(d, name)).read()
        assert "innerHTML" not in text and "http://" not in text and "https://" not in text, name


def test_a_burst_of_requests_costs_one_fan_out_within_the_cache_window(world):
    a, b, bee = duo(world)
    world.here_env()
    srv = fleet.make_ui_server(port=0, ttl=60)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = "http://127.0.0.1:%d/api/members" % srv.server_address[1]
        for _ in range(3):
            req = urllib.request.Request(url, headers={"Authorization": "Bearer " + srv.fleet_token})
            assert len(json.loads(urllib.request.urlopen(req, timeout=20).read())["members"]) == 2
        assert [h for h, _ in world.ssh_log()] == ["bee"]
    finally:
        srv.shutdown()
        srv.server_close()


def open_fds():
    return len(os.listdir("/dev/fd"))


def test_serving_many_requests_leaves_the_open_descriptor_count_flat(world, server):
    a, b, bee = duo(world)
    paths = ["/api/members", "/api/todos", "/api/threads", "/api/inbox", "/api/history", "/", "/app.js", "/app.css", "/nope"]
    for p in paths:  # warm up: caches, lazily opened files
        server(p, raw=True)
    before = open_fds()
    for _ in range(25):
        for p in paths:
            server(p, raw=True)
    assert open_fds() <= before + 3, (before, open_fds())


# ---------------------------------------------------------------- the page's token

def raw_get(srv, path, headers=None):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    out = (r.status, dict(r.getheaders()), r.read())
    c.close()
    return out


def test_nothing_is_served_without_the_token_and_the_401_says_what_to_run(server):
    for path in ("/app.js", "/app.css", "/api/members", "/api/todos", "/api/threads", "/api/inbox", "/api/history",
                 "/api/nope"):
        code, body = server(path, raw=True, headers={"Authorization": None})
        assert code == 401 and b"fleet ui url" in body, path
        assert len(body.decode().strip().splitlines()) == 1


def test_a_wrong_token_or_a_wrong_scheme_is_refused(server):
    for h in ({"Authorization": "Bearer nope"}, {"Authorization": "Basic " + server.srv.fleet_token},
              {"Authorization": None, "Cookie": "fleet_ui=nope"}, {"Authorization": None, "Cookie": "other=" + server.srv.fleet_token}):
        assert server("/api/members", raw=True, headers=h)[0] == 401


def test_the_bearer_header_and_the_cookie_each_open_the_api(server):
    tok = server.srv.fleet_token
    assert server("/api/members", headers={"Authorization": None, "Cookie": "a=b; fleet_ui=%s; c=d" % tok})[0] == 200
    assert server("/api/members", headers={"Authorization": "bearer " + tok})[0] == 200


def test_a_write_without_the_token_is_refused_before_anything_is_stored(world, server):
    host = "127.0.0.1:%d" % server.srv.server_address[1]
    req = urllib.request.Request("http://%s/api/todos/add" % host, data=json.dumps({"title": "x"}).encode(), method="POST",
                                 headers={"Host": host, "Origin": "http://" + host, "Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 401
    world.here_env()
    assert fleet.db().execute("SELECT COUNT(*) FROM todos").fetchone()[0] == 0


def test_login_sets_a_strict_http_only_cookie_and_redirects_without_the_token(server):
    srv, tok = server.srv, server.srv.fleet_token
    code, h, _ = raw_get(srv, "/login?t=" + tok)
    cookie = h["Set-Cookie"]
    assert code == 303 and h["Location"] == "/" and "t=" not in h["Location"]
    assert cookie.startswith("fleet_ui=" + tok) and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert "Secure" not in cookie  # plain http: a Secure cookie would never come back
    assert h["Referrer-Policy"] == "no-referrer"
    assert raw_get(srv, "/api/members", {"Cookie": cookie.split(";")[0]})[0] == 200


def test_login_through_an_https_proxy_marks_the_cookie_secure(server):
    code, h, _ = raw_get(server.srv, "/login?t=" + server.srv.fleet_token, {"X-Forwarded-Proto": "https"})
    assert code == 303 and "; Secure" in h["Set-Cookie"]
    code, h, _ = raw_get(server.srv, "/login?t=" + server.srv.fleet_token, {"X-Forwarded-Proto": "http"})
    assert "Secure" not in h["Set-Cookie"]


def test_login_with_a_wrong_or_missing_token_sets_nothing(server):
    for path in ("/login", "/login?t=", "/login?t=wrong"):
        code, h, _ = raw_get(server.srv, path)
        assert code == 401 and "Set-Cookie" not in h


def test_every_get_and_the_static_files_check_the_host_even_with_the_token(server):
    for path in ("/", "/app.js", "/app.css", "/api/members", "/api/todos", "/api/threads", "/api/inbox", "/api/history",
                 "/login?t=" + server.srv.fleet_token):
        code, body = server(path, raw=True, headers={"Host": "evil.example"})
        assert code == 403 and b"unknown Host" in body, path


def test_the_token_is_made_once_kept_private_and_leaves_the_other_keys(world):
    import stat
    os.makedirs(world.here.home, exist_ok=True)
    path = os.path.join(world.here.home, "ui.json")
    json.dump({"port": 8123, "hosts": ["fleet.proxy.example"]}, open(path, "w"))
    os.chmod(path, 0o644)
    tok = fleet.ui_token()
    assert len(tok) >= 40 and fleet.ui_token() == tok
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert json.load(open(path)) == {"port": 8123, "hosts": ["fleet.proxy.example"], "token": tok}


def test_fleet_ui_url_prints_a_login_link_with_the_token(world):
    world.here_env()
    world.capsys.readouterr()
    assert fleet.main(["ui", "url"]) == 0
    url = world.capsys.readouterr().out.strip()
    assert url == "http://127.0.0.1:8797/login?t=%s" % fleet.ui_token()
    json.dump({"hosts": ["fleet.proxy.example"], "token": fleet.ui_token()}, open(os.path.join(world.here.home, "ui.json"), "w"))
    fleet.main(["ui", "url"])
    assert world.capsys.readouterr().out.strip() == "https://fleet.proxy.example/login?t=%s" % fleet.ui_token()


def test_the_login_link_works_against_a_running_server(world):
    srv = fleet.make_ui_server(port=0, ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = fleet.ui_url(srv.server_address[1])
        assert url.startswith("http://127.0.0.1:%d/login?t=" % srv.server_address[1])
        code, h, _ = raw_get(srv, url[url.index("/login"):])
        assert code == 303 and raw_get(srv, "/api/members", {"Cookie": h["Set-Cookie"].split(";")[0]})[0] == 200
        assert raw_get(srv, "/api/members")[0] == 401
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_page_has_an_inline_svg_favicon_and_the_title_fleet():
    import os, urllib.parse, xml.dom.minidom
    html = open(os.path.join(os.path.dirname(fleet.__file__), "ui", "index.html")).read()
    assert "<title>Fleet</title>" in html
    href = html.split('rel="icon" type="image/svg+xml" href="')[1].split('"')[0]
    assert href.startswith("data:image/svg+xml,")
    svg = urllib.parse.unquote(href.split(",", 1)[1])
    assert xml.dom.minidom.parseString(svg).documentElement.tagName == "svg" and "#00d7d7" in svg and "circle" in svg


def raw_post_form(srv, path, body, headers=None):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    c.request("POST", path, body=body, headers=dict({"Content-Type": "application/x-www-form-urlencoded"}, **(headers or {})))
    r = c.getresponse()
    out = (r.status, dict(r.getheaders()), r.read())
    c.close()
    return out


def test_the_page_without_the_cookie_is_a_sign_in_form(server):
    code, h, body = raw_get(server.srv, "/")
    assert code == 401 and h["Content-Type"].startswith("text/html")
    assert b'<form method="post" action="/login">' in body and b'name="password"' in body
    assert b"not right" not in body


def test_typing_the_password_signs_in_and_a_wrong_one_says_so(server):
    from urllib.parse import quote
    code, h, body = raw_post_form(server.srv, "/login", "password=wrong")
    assert code == 401 and "Set-Cookie" not in h and b"That password is not right." in body
    code, h, _ = raw_post_form(server.srv, "/login", "password=" + quote(server.srv.fleet_token))
    assert code == 303 and h["Location"] == "/" and h["Set-Cookie"].startswith("fleet_ui=")
    assert raw_get(server.srv, "/api/members", {"Cookie": h["Set-Cookie"].split(";")[0]})[0] == 200


def test_the_shared_password_file_is_the_token_unless_ui_json_names_one(world):
    shared = os.environ["FLEET_SHARED_TOKEN_FILE"]
    open(shared, "w").write("blue river\n")
    os.makedirs(world.here.home, exist_ok=True)
    path = os.path.join(world.here.home, "ui.json")
    json.dump({"port": 8123}, open(path, "w"))
    assert fleet.ui_token() == "blue river"
    assert "token" not in json.load(open(path))  # the shared password is never copied into ui.json
    json.dump({"token": "x" * 32}, open(path, "w"))
    assert fleet.ui_token() == "x" * 32
