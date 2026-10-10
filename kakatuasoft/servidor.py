

import requests

SERVIDOR_URL = "https://esp32.chobi.com.br/api/sensor/"
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


def _get(path):
    try:
        r = requests.get(SERVIDOR_URL + path, headers=HEADERS, timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Erro ao consultar {path}: {e}")
        return None


def consultar_estacao():
    """True = bloqueada, False = liberada, None = servidor indisponível."""
    dados = _get("estacao/")
    return None if dados is None else bool(dados.get("bloqueada", False))


def consultar_tranca(id_tranca):
    """dict com estado/reservada/atualizado_em, ou None."""
    return _get(f"tranca/{id_tranca}/")
