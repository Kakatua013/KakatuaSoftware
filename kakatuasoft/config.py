import os


def obter(nome_env, campo_db):
    """Lê uma configuração sensível.
    1) variável de ambiente (painel da hospedagem), se existir;
    2) senão, o valor salvo no /admin (Configuração)."""
    valor = os.environ.get(nome_env)
    if valor:
        return valor
    from .models import Configuracao
    return getattr(Configuracao.atual(), campo_db)
