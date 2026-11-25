import time

from django.core.management.base import BaseCommand

from kakatuasoft import views
from kakatuasoft.models import Estacao


class Command(BaseCommand):
    help = ('Confirma/cancela reservas pendentes e registra objetos encaixados sem reserva, '
            'mesmo sem ninguém com o site aberto. Rode pelo cron (1x por minuto) ou com --loop.')

    def add_arguments(self, parser):
        parser.add_argument('--loop', type=int, default=0, metavar='SEGUNDOS',
                            help='repete a cada N segundos (0 = roda uma vez e sai)')

    def handle(self, *args, **opts):
        while True:
            estacoes = list(Estacao.objects.all().order_by('id'))
            estado = views._estado_servidor(estacoes)
            views._atualizar_reservas(estacoes, estado['trancas'])
            views._atualizar_objetos(estacoes, estado['trancas'])
            if not opts['loop']:
                break
            time.sleep(opts['loop'])
