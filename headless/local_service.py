"""Small localhost HTTP service. Routes own application logic; no game or DB imports."""
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import secrets
from urllib.parse import urlsplit


class RequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status=status


@dataclass
class Response:
    body: str
    content_type: str='text/html; charset=utf-8'
    status: int=200


class LocalService(ThreadingHTTPServer):
    """Register (method,path) -> handler(JSON body). A handler returns JSON or Response."""
    daemon_threads=False  # Finish in-flight transactions before server_close returns.
    allow_reuse_address=False

    def __init__(self, routes=None, port=0):
        self.routes=routes if routes is not None else {}
        self.token=secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1',port),Handler)
        self.origin=f'http://127.0.0.1:{self.server_port}'
        self.host=f'127.0.0.1:{self.server_port}'

    def get_request(self):
        connection,address=super().get_request()
        connection.settimeout(5)
        return connection,address


class Handler(BaseHTTPRequestHandler):
    server_version='LocalService/1'

    def log_message(self, format, *args):
        pass  # No request-body/token logging. Unexpected errors still get tracebacks.

    def reply(self, value, status=200):
        if isinstance(value,Response):
            status=value.status;kind=value.content_type;body=value.body.encode('utf-8')
        else:
            kind='application/json; charset=utf-8'
            body=json.dumps(value,ensure_ascii=True,allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self):
        self.body_read=False
        try:
            if self.headers.get('Host')!=self.server.host:
                raise RequestError('Local service host required',403)
            origin=self.headers.get('Origin')
            if origin is not None and origin!=self.server.origin:
                raise RequestError('Same-origin request required',403)
            path=urlsplit(self.path).path
            route=self.server.routes.get((self.command,path))
            if route is None:
                raise RequestError('Route not found',404)
            payload=None
            if self.command!='GET':
                if origin!=self.server.origin or not secrets.compare_digest(
                        self.headers.get('X-Local-Token','').encode('utf-8'),self.server.token.encode('ascii')):
                    raise RequestError('Open the local service page before saving',403)
                if self.headers.get('Transfer-Encoding'):
                    raise RequestError('Transfer encoding not supported',400)
                if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
                    raise RequestError('JSON request body required',415)
                try:length=int(self.headers.get('Content-Length',''))
                except ValueError:raise RequestError('Content-Length required',411)
                if not 0<length<=16384:raise RequestError('Request body must be 1..16384 bytes',413)
                self.body_read=True
                raw=self.rfile.read(length)
                if len(raw)!=length:raise RequestError('Incomplete request body')
                try:
                    payload=json.loads(raw)
                except (ValueError,UnicodeError):raise RequestError('Invalid JSON')
                if not isinstance(payload,dict):raise RequestError('JSON object required')
            self.reply(route(payload))
        except RequestError as error:
            # Windows may reset a connection closed with unread request data,
            # hiding even a valid error response. Drain small rejected bodies only.
            if self.command=='POST' and not self.body_read and not self.headers.get('Transfer-Encoding'):
                try:
                    remaining=int(self.headers.get('Content-Length','0'))
                    if 0<remaining<=65536:self.rfile.read(remaining)
                except (ValueError,OSError):pass
            self.reply({'error':str(error)},error.status)
        except (BrokenPipeError,ConnectionResetError,TimeoutError):
            return
        except Exception:
            import traceback
            traceback.print_exc()
            self.reply({'error':'Local service error; see the service terminal'},500)

    do_GET=dispatch
    do_POST=dispatch
