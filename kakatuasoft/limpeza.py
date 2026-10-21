from datetime import timedelta
from django.utils import timezone
from .models import Usuario


def limpar_nao_confirmados(horas=24):
    """Apaga contas com e-mail não confirmado criadas há mais de `horas`."""
    limite = timezone.now() - timedelta(hours=horas)
    contas = Usuario.objects.filter(
        email_verificado=False,
        Email__isnull=False,
        criado_em__lt=limite,
    )
    total = contas.count()
    contas.delete()
    return total