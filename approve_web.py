import argparse
import html
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nudge_agent import approve, approve_all, history_rows, proposed_rows, push_approved, reject

DECIDED_BY = "web"

CSS = """
body { font-family: system-ui, sans-serif; margin: 2rem; color: #222; }
h1, h2 { font-weight: 600; }
table { border-collapse: collapse; margin-bottom: 2rem; width: 100%; }
th, td { border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; font-size: 0.9rem; }
th { background: #f2f2f2; }
form { display: inline; }
input[type=text] { width: 12rem; }
.bar { margin-bottom: 1.5rem; }
.bar button { margin-right: 0.5rem; }
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _next_cell(url: str | None, title: str | None) -> str:
    if url is None:
        return _e(title)
    return f'<a href="{_e(url)}" target="_top">{_e(title)}</a>'


def _proposed_table() -> str:
    rows = proposed_rows()
    if not rows:
        return "<p>No proposed recommendations.</p>"
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{_e(r.id)}</td><td>{_e(r.rule)}</td><td>{_e(r.user_id)}</td>"
            f"<td>{_e(r.surface)}</td><td>{_e(r.priority)}</td><td>{_e(r.text)}</td>"
            f"<td>{_next_cell(r.next_url, r.next_title)}</td>"
            f'<td><form method="post" action="/approve/{_e(r.id)}">'
            "<button type=\"submit\">Approve</button></form></td>"
            f'<td><form method="post" action="/reject/{_e(r.id)}">'
            '<input type="text" name="note" placeholder="note">'
            "<button type=\"submit\">Reject</button></form></td>"
            "</tr>"
        )
    header = (
        "<tr><th>id</th><th>rule</th><th>user</th><th>surface</th><th>priority</th>"
        "<th>text</th><th>next</th><th></th><th></th></tr>"
    )
    return "<table>" + header + "".join(body) + "</table>"


def _history_table() -> str:
    rows = history_rows()
    if not rows:
        return "<p>Nothing decided yet.</p>"
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{_e(r.id)}</td><td>{_e(r.rule)}</td><td>{_e(r.user_id)}</td>"
            f"<td>{_next_cell(r.next_url, r.next_title)}</td>"
            f"<td>{_e(r.status)}</td><td>{_e(r.decided_by)}</td><td>{_e(r.decided_at)}</td>"
            f"<td>{_e(r.decision_note)}</td><td>{_e(r.pushed_at)}</td><td>{_e(r.push_error)}</td>"
            "</tr>"
        )
    header = (
        "<tr><th>id</th><th>rule</th><th>user</th><th>next</th><th>status</th><th>decided_by</th>"
        "<th>decided_at</th><th>note</th><th>pushed_at</th><th>push_error</th></tr>"
    )
    return "<table>" + header + "".join(body) + "</table>"


def _page() -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>Nudge approvals</title>"
        f"<style>{CSS}</style></head><body>"
        "<h1>Nudge approvals</h1>"
        '<div class="bar">'
        '<form method="post" action="/approve-all"><button type="submit">Approve all</button></form>'
        '<form method="post" action="/push"><button type="submit">Push approved</button></form>'
        "</div>"
        "<h2>Proposed</h2>" + _proposed_table() +
        "<h2>History</h2>" + _history_table() +
        "</body></html>"
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/":
            self.send_error(404)
            return
        payload = _page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        form = self._form()
        parts = self.path.strip("/").split("/")
        try:
            if parts[0] == "approve" and len(parts) == 2:
                approve([int(parts[1])], DECIDED_BY)
            elif parts[0] == "reject" and len(parts) == 2:
                reject(int(parts[1]), form.get("note", [""])[0], DECIDED_BY)
            elif parts == ["approve-all"]:
                approve_all(DECIDED_BY)
            elif parts == ["push"]:
                push_approved()
            else:
                self.send_error(404)
                return
        except ValueError:
            self.send_error(400)
            return
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        return urllib.parse.parse_qs(raw, keep_blank_values=True)

    def log_message(self, fmt: str, *args) -> None:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="approve_web", description="Local approval page for proposed nudges."
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"http://127.0.0.1:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
