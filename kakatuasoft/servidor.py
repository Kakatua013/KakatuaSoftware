import requests

SERVIDOR_URL = "https://esp32.chobby-chobby.com.br/api/sensor/"
API_KEY = "ifpDXyrQY13sJJj8T98dr3FoLvjbtxfpsBAEOJcp1p0="
HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
}

def enviar_acesso(usuario):
    try:
        response = requests.post(
            SERVIDOR_URL + "acesso/",
            json={
                "login": usuario.Login,
                "senha": usuario.Senha,
                "id_tranca": usuario.id_tranca,
                "estado_tranca": str(usuario.estado_tranca),
                "tranca_reservada": bool(usuario.tranca_reservada),
            },
            headers=HEADERS,
            timeout=5
        )
        print(f"Servidor acesso: {response.status_code} - {response.json()}")
        return True
    except Exception as e:
        print(f"Erro ao enviar acesso: {e}")
        return False

def consultar_estacao():
    try:
        response = requests.get(
            SERVIDOR_URL + "estacao/",
            headers=HEADERS,
            timeout=5
        )
        dados = response.json()
        return dados.get('bloqueada', False)
    except Exception as e:
        print(f"Erro ao consultar estacao: {e}")
        return False