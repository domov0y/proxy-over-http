# серверная часть 
import socket
import uuid
from flask import Flask, request

app = Flask(__name__)

# Хранилище сессий
sessions = {}

# Маршрут: открыть сессию
@app.route('/session/open', methods=['POST'])
def open_session():
    data = request.get_json()
    if not data:
        return {"error": "JSON required"}, 400

    host = data.get("host")
    port = data.get("port", 80)

    if not host:
        return {"error": "Host required"}, 400

    try:
        sock = socket.create_connection((host, port), timeout=10)
        session_id = str(uuid.uuid4())
        sessions[session_id] = {
            "socket": sock,
            "host": host,
            "port": port,
            "status": "open"
        }
        print(f"✅ Сессия {session_id} открыта → {host}:{port}")
        return {"session_id": session_id, "status": "connected"}, 200
    except Exception as e:
        return {"error": str(e)}, 500

# Маршрут: статус сессии
@app.route('/session/<session_id>/status')
def session_status(session_id):
    sess = sessions.get(session_id)
    if not sess:
        return {"error": "Session not found"}, 404
    return {
        "session_id": session_id,
        "host": sess["host"],
        "port": sess["port"],
        "status": sess["status"]
    }, 200

# Маршрут: отправить данные
@app.route('/session/<session_id>/send', methods=['POST'])
def session_send(session_id):
    sess = sessions.get(session_id)
    if not sess:
        return {"error": "Session not found"}, 404
    if sess["status"] != "open":
        return {"error": "Session closed"}, 400

    data = request.data
    if not data:
        return {"error": "No data"}, 400

    try:
        sess["socket"].send(data)
        print(f"📤 Сессия {session_id}: отправлено {len(data)} байт")
        return {"sent": len(data)}, 200
    except Exception as e:
        sess["status"] = "error"
        return {"error": str(e)}, 500

# Маршрут: получить данные
@app.route('/session/<session_id>/recv')
def session_recv(session_id):
    sess = sessions.get(session_id)
    if not sess:
        return {"error": "Session not found"}, 404
    if sess["status"] != "open":
        return {"error": "Session closed"}, 400

    try:
        sess["socket"].settimeout(5.0)
        data = sess["socket"].recv(4096)
        print(f"📥 Сессия {session_id}: получено {len(data)} байт")
        return data, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except socket.timeout:
        return "", 204
    except Exception as e:
        sess["status"] = "error"
        return {"error": str(e)}, 500

# Маршрут: закрыть сессию
@app.route('/session/<session_id>/close', methods=['POST'])
def session_close(session_id):
    sess = sessions.get(session_id)
    if not sess:
        return {"error": "Session not found"}, 404

    try:
        sess["socket"].close()
        print(f"🔌 Сессия {session_id} закрыта")
    except:
        pass
    finally:
        sessions.pop(session_id, None)

    return {"status": "closed"}, 200

# Запуск
if __name__ == '__main__':
    print("🌍 Запуск сервера на http://localhost:5000")
    app.run(host="localhost", port=5000)