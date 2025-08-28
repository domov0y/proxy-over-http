import socket
import threading
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib3
urllib3.disable_warnings() 


# === НАСТРОЙКИ ===
API_URL = "http://localhost:5000" 
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8080
# ================


def send_raw_response(handler, raw_response):
    """
    Парсит сырой HTTP-ответ (b'HTTP/1.1 200 OK\\r\\n...') 
    и отправляет его браузеру правильно: заголовки — как заголовки, тело — как тело.
    """
    if b"\r\n\r\n" in raw_response:
        headers_raw, body = raw_response.split(b"\r\n\r\n", 1)
    else:
        headers_raw, body = raw_response, b""

    headers_lines = headers_raw.split(b"\r\n")
    if not headers_lines:
        handler.send_response(502)
        handler.end_headers()
        handler.wfile.write(b"Invalid response")
        return

    # Статус-строка: "HTTP/1.1 200 OK"
    status_line = headers_lines[0].decode("utf-8", errors="ignore")
    if "200" in status_line:
        status_code = 200
    elif "404" in status_line:
        status_code = 404
    elif "500" in status_line:
        status_code = 500
    elif "301" in status_line or "302" in status_line:
        status_code = 302  # редирект
    else:
        status_code = 200

    handler.send_response(status_code)

    # Отправляем заголовки
    for line in headers_lines[1:]:
        if b":" in line:
            try:
                key, value = line.split(b":", 1)
                handler.send_header(
                    key.decode("utf-8").strip(),
                    value.decode("utf-8").strip()
                )
            except:
                pass  # пропускаем кривые заголовки

    handler.end_headers()

    # Только тело
    handler.wfile.write(body)


class ProxyHandler(BaseHTTPRequestHandler):
    def tunnel_browser_to_api(self, client_sock, session_id):
        """Читает от браузера → отправляет в API через /send"""
        while True:
            try:
                data = client_sock.recv(4096)
                if not data:
                     break
                requests.post(f"{API_URL}/session/{session_id}/send", data=data)
            except:
                break

    def tunnel_api_to_browser(self, client_sock, session_id):
        """Опрашивает /recv → отправляет ответ браузеру"""
        while True:  
            try:
                resp = requests.get(f"{API_URL}/session/{session_id}/recv")
                if resp.status_code == 200 and resp.content:
                    client_sock.send(resp.content)
                elif resp.status_code == 204:
                    # Нет данных — подождём
                    time.sleep(0.1)
                else:
                    break
            except:
                break

    def do_GET(self):
        # 1. Парсим URL
        from urllib.parse import urlparse
        url = urlparse(self.path)
        if not url.hostname:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Bad URL")
            return

        host = url.hostname
        port = url.port or 80
        path = url.path or "/"
        if not path.startswith("/"):
            path = "/" + path

        print(f"🎯 GET: {host}:{port} {path}")

        # 2. Формируем простой HTTP-запрос
        request = f"GET {path} HTTP/1.1\r\n"
        request += f"Host: {host}\r\n"
        request += "Connection: close\r\n"
        request += "User-Agent: TinyProxy\r\n"
        request += "\r\n"
        request_bytes = request.encode("utf-8")

        # 3. Открываем сессию через API
        try:
            open_resp = requests.post(f"{API_URL}/session/open", json={"host": host, "port": port})
            if open_resp.status_code != 200:
                print("❌ Ошибка открытия сессии:", open_resp.text)
                self.send_response(502)
                self.end_headers()
                self.wfile.write(b"Failed to open session")
                return	

            session_id = open_resp.json()["session_id"]
            print(f"✅ Сессия открыта: {session_id}")	

            # 4. Отправляем запрос
            send_resp = requests.post(f"{API_URL}/session/{session_id}/send", data=request_bytes)
            if send_resp.status_code != 200:
                print("❌ Ошибка отправки:", send_resp.text)
                self.send_response(502)
                self.end_headers()
                self.wfile.write(b"Send failed")
                return

            print("📤 Данные отправлены")

	        # 5. Читаем ответ кусками
            full_response = b""
            while True:
                recv_resp = requests.get(f"{API_URL}/session/{session_id}/recv")
                if recv_resp.status_code == 200 and recv_resp.content:
                    print(f"📥 Получено {len(recv_resp.content)} байт")
                    full_response += recv_resp.content
                elif recv_resp.status_code == 204:
		            # Нет данных — значит, всё пришло
                    print("📭 recv вернул 204 — данных больше нет")
                    break
                else:
                    print("⚠️ Ошибка recv:", recv_resp.text)
                    break

            # 6. Закрываем сессию

            requests.post(f"{API_URL}/session/{session_id}/close")	

            # 7. Возвращаем ответ браузеру
            if full_response:
                #self.send_response(200)
                #self.end_headers()
                #self.wfile.write(full_response)
                send_raw_response(self, full_response)
                print(f"📤 Браузеру отправлено {len(full_response)} байт")
            else:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(b"Empty response from server")

        except Exception as e:
            print("❌ Ошибка:", str(e))
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Proxy error")


    def do_CONNECT(self):
        # 1. Парсим host:port из CONNECT
        hostname = self.path.split(":")[0]
        port = int(self.path.split(":")[1])

        print(f"🔐 CONNECT: {hostname}:{port}")

        # 2. Открываем сессию через API
        try:
            open_resp = requests.post( f"{API_URL}/session/open",  json={"host": hostname, "port": port} )
            if open_resp.status_code != 200:
                self.send_response(502)
                self.end_headers()
                return

            session_id = open_resp.json()["session_id"]
            print(f"✅ API-сессия: {session_id}")

            # 3. Говорим браузеру: "всё, соединяйся"
            self.send_response(200, "Connection Established")
            self.end_headers()

            # Теперь — туннель: перекидываем байты
            # self.connection — это сокет к браузеру

            # Запускаем две нити
            t1 = threading.Thread(target=self.tunnel_browser_to_api, args=(self.connection, session_id), daemon=True)
            t2 = threading.Thread(target=self.tunnel_api_to_browser, args=(self.connection, session_id), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        except Exception as e:
            print("❌ CONNECT ошибка:", e)
            self.send_response(500)
            self.end_headers()


server = HTTPServer( ("127.0.0.1", 8080),  ProxyHandler)
print("Прокси слушает на 127.0.0.1:8080")
server.serve_forever()