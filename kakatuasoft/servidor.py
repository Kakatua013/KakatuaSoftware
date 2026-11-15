import requests
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor

SERVIDOR_URL = "https://esp32.chobi.com.br/api/sensor/"

# Sessão única: reaproveita a conexão (keep-alive), então o handshake TCP/TLS
# acontece uma vez e não a cada requisição.
_session = requests.Session()
_session.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=8))

TIMEOUT_LEITURA = (2, 3)    # (conectar, ler) em segundos
TIMEOUT_COMANDO = (2, 4)


def _headers():
    # API key: variável de ambiente API_KEY ou, se não houver, o valor do /admin
    from .config import obter
    return {
        "X-API-Key": obter('API_KEY', 'api_key'),
        "Content-Type": "application/json",
    }


def enviar_acesso(usuario):
    try:
        response = _session.post(
            SERVIDOR_URL + "acesso/",
            json={
                "login": usuario.Login,
                "senha": usuario.Senha,
                "id_tranca": usuario.id_tranca,
                "estado_tranca": str(usuario.estado_tranca),
                "tranca_reservada": bool(usuario.tranca_reservada),
            },
            headers=_headers(),
            timeout=TIMEOUT_COMANDO,
        )
        print(f"Servidor acesso: {response.status_code} - {response.json()}")
        return True
    except Exception as e:
        print(f"Erro ao enviar acesso: {e}")
        return False


def _get(path, headers=None):
    try:
        r = _session.get(SERVIDOR_URL + path,
                         headers=headers or _headers(), timeout=TIMEOUT_LEITURA)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Erro ao consultar {path}: {e}")
        return None


def consultar_estacao():
    """True = OCUPADA, False = LIVRE, None = servidor indisponível."""
    dados = _get("estacao/")
    return None if dados is None else bool(dados.get("bloqueada", False))


def consultar_tranca(id_tranca):
    """dict com estado/reservada/atualizado_em, ou None."""
    return _get(f"tranca/{id_tranca}/")


def consultar_tudo(ids_trancas):
    """Consulta estacao/ e todas as trancas EM PARALELO.
    Retorna (bloqueada, {id: dict|None}). bloqueada=None se o servidor caiu."""
    headers = _headers()   # lido uma vez, na thread principal (evita acesso ao banco nas threads)
    with ThreadPoolExecutor(max_workers=len(ids_trancas) + 1) as ex:
        f_est = ex.submit(_get, "estacao/", headers)
        f_tr = {i: ex.submit(_get, f"tranca/{i}/", headers)
                for i in ids_trancas}
        dados = f_est.result()
        trancas = {i: f.result() for i, f in f_tr.items()}
    bloqueada = None if dados is None else bool(dados.get("bloqueada", False))
    return bloqueada, trancas


def enviar_comando(id_tranca, comando):
    """comando: 'fechar' (guardar bike) ou 'abrir' (retirar bike).
    Retorna True se o servidor aceitou."""
    try:
        r = _session.post(
            SERVIDOR_URL + f"tranca/{id_tranca}/comando/",
            json={"comando": comando},
            headers=_headers(),
            timeout=TIMEOUT_COMANDO,
        )
        r.raise_for_status()
        print(
            f"Comando '{comando}' enviado à tranca {id_tranca}: {r.status_code}")
        return True
    except Exception as e:
        print(f"Erro ao enviar comando '{comando}' à tranca {id_tranca}: {e}")
        return False
