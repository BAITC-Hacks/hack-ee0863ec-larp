"""Explicit browser-origin policy for the local API (no wildcard trust)."""
from urllib.parse import urlsplit


def origin_key(value):
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ValueError('Invalid Origin.')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.path or parsed.query or parsed.fragment):
        raise ValueError('Origin must contain only scheme, host and optional port.')
    port = parsed.port  # Validates malformed or out-of-range ports, too.
    return parsed.scheme, parsed.hostname.lower(), port if port is not None else (443 if parsed.scheme == 'https' else 80)


class CORSMixin:
    def check_origin(self, required=False):
        self.cors_origin = None
        origins = self.headers.get_all('Origin', [])
        if not origins:
            if required:
                self.json_response({'error': 'Preflight requires Origin.'}, 400)
                return False
            return True
        if len(origins) != 1:
            self.json_response({'error': 'Only one Origin is allowed.'}, 400)
            return False
        origin = origins[0]
        if origin == 'null':
            self.json_response({'error': 'Недопустимый источник запроса.'}, 403)
            return False
        try:
            key = origin_key(origin)
            hosts = self.headers.get_all('Host', [])
            if len(hosts) != 1:
                raise ValueError('Only one Host is allowed.')
            same = origin_key('http://' + hosts[0])
        except ValueError:
            self.json_response({'error': 'Некорректный заголовок Origin или Host.'}, 400)
            return False
        if key != same and key not in self.server.app.allowed_origins:
            self.json_response({'error': 'Источник не разрешён. Настройте --allow-origin для адреса фронтенда.'}, 403)
            return False
        self.cors_origin = origin
        return True

    def end_headers(self):
        if getattr(self, 'cors_origin', None):
            self.send_header('Access-Control-Allow-Origin', self.cors_origin)
            self.send_header('Access-Control-Expose-Headers', 'Retry-After')
        self.send_header('Vary', 'Origin')
        super().end_headers()

    def do_OPTIONS(self):
        routes = {'/api/recommend': 'POST', '/api/options': 'GET', '/api/catalog': 'GET', '/health': 'GET'}
        method = routes.get(urlsplit(self.path).path)
        if method is None:
            return self.json_response({'error': 'Не найдено'}, 404)
        if not self.check_origin(required=True):
            return
        if self.headers.get('Access-Control-Request-Method') != method:
            return self.json_response({'error': 'Метод не разрешён для этого адреса.'}, 405)
        requested = {part.strip().lower() for part in self.headers.get('Access-Control-Request-Headers', '').split(',') if part.strip()}
        if not requested <= {'content-type'}:
            return self.json_response({'error': 'Заголовки запроса не разрешены.'}, 403)
        self.send_response(204)
        self.send_header('Content-Length', '0')
        self.send_header('Access-Control-Allow-Methods', method)
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Max-Age', '600')
        self.end_headers()
